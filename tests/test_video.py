import threading
import time

import pytest

from course_factory import listen, voices
from course_factory.catalogue import CATALOGUE
from course_factory.checks import component_errors
from course_factory.video_templates import check_params
from test_listen import PROSE, course

N = "Une phrase qui dit ce que montre la scène."
FLOW = {"title": "Des enregistrements dans des partitions", "narrow": "map", "wide": "reduceByKey", "cache": True,
        "partitions": [[{"key": "a", "value": "1"}, {"key": "b", "value": "2"}], [{"key": "a", "value": "3"}]]}
EQUATION = {"title": "", "steps": [{"latex": "3x + 5 = 20", "note": ""}, {"latex": "3x = 15", "note": "on retire 5"}]}
PLOT = {"title": "Une parabole", "expr": "x**2 - 2", "latex": "f(x) = x^2 - 2", "x_range": [-3, 3], "marks": [{"x": 0, "label": "le minimum"}]}
OVERVIEW = {"title": "Le chapitre", "points": ["Une idée"], "sections": [{"title": "Première", "line": "Ce qu'elle ajoute."}]}
PARAMS = {"partition_flow": (FLOW, 4), "equation_transform": (EQUATION, 2), "function_plot": (PLOT, 3), "chapter_overview": (OVERVIEW, 2)}


def video(template="equation_transform", params=EQUATION, narration=None):
    n = check_params(template, params)[1]
    return {"component": "video", "origin": "model_added", "data": {"template": template, "params": params, "narration": narration or [N] * n}}


def state(client, cid, bid, until=("ready", "failed", "pending", "invalid"), wait=10):
    """The Video's state, once the background job (if any) is over."""
    end = time.time() + wait
    while True:
        s = client.get(f"/api/courses/{cid}/blocks/{bid}/video").json()
        if s["state"] in until or time.time() > end:
            return s
        time.sleep(0.05)


def videos_of(client, cid):
    return [b for ch in client.get(f"/api/courses/{cid}/reader").json() for s in ch["sections"] for b in s["blocks"] if b["component"] == "video"]


def renders(media, bid):
    """The renders of one Block (every Section of the fake Course holds the same Blocks)."""
    return [sp for sp, _, out in media.renders if out.parent.name == str(bid)]


def mine(client, cid):
    return next(b for b in videos_of(client, cid) if b["data"]["template"] != "chapter_overview")


@pytest.mark.parametrize("template", PARAMS)
def test_each_template_validates_its_parameters(template):
    params, scenes = PARAMS[template]
    Video = CATALOGUE["video"]
    ok = Video.model_validate({"template": template, "params": params, "narration": [N] * scenes})
    assert ok.params  # normalised
    with pytest.raises(ValueError, match="scenes"):  # one script per scene
        Video.model_validate({"template": template, "params": params, "narration": [N] * (scenes + 1)})
    with pytest.raises(ValueError):  # unknown parameters are still checked as types
        Video.model_validate({"template": template, "params": {"nonsense": 1}, "narration": [N] * scenes})


def test_parameters_are_held_to_the_template_rules():
    with pytest.raises(ValueError, match="plain text"):
        check_params("partition_flow", FLOW | {"narrow": "$map$"})  # maths goes in a latex field, never on screen as text
    with pytest.raises(ValueError, match="1 to 5"):
        check_params("partition_flow", FLOW | {"partitions": [[], [{"key": "a"}]]})
    with pytest.raises(ValueError):
        check_params("equation_transform", {"steps": [{"latex": "x"}]})  # an equation needs two lines to transform
    with pytest.raises(ValueError):  # the template is one of the fixed ones
        CATALOGUE["video"].model_validate({"template": "nonsense", "params": {}, "narration": [N]})
    data = {"template": "function_plot", "params": check_params("function_plot", PLOT)[0], "narration": [N] * 3}
    assert component_errors("video", data) == []
    bad = {**data, "params": {**data["params"], "marks": [{"x": 9.0, "label": "ailleurs"}]}}
    assert "outside x_range" in component_errors("video", bad)[0]
    assert "does not parse" in component_errors("video", {**data, "params": {**data["params"], "expr": "x +* 2"}})[0]


def test_a_checked_section_queues_its_videos_and_the_run_does_not_wait(client, material, model, media):
    media.video = True
    gate, orig = threading.Event(), media.render
    media.render = lambda spec, audio, out: (gate.wait(10), orig(spec, audio, out))  # a slow render: the Run is not held up by it
    cid, _ = course(client, material, model, [PROSE, video("function_plot", PLOT)])  # returned: the Course got through its gates
    bid = mine(client, cid)["id"]
    s = client.get(f"/api/courses/{cid}/blocks/{bid}/video").json()
    assert s["state"] == "rendering" and s["narration"] == [N] * 3  # the narration is shown as text meanwhile
    gate.set()
    s = state(client, cid, bid)
    assert s["state"] == "ready" and s["url"].endswith(".mp4") and s["poster"].endswith(".png")
    spec, audio = next((sp, a) for sp, a, _ in media.renders if sp["template"] == "function_plot")
    assert len(spec["durations"]) == 3 and all(d >= 3.0 for d in spec["durations"])  # each scene is as long as its narration (and a breath)
    assert spec["params"]["marks"][0]["y"] == -2 and len(spec["curve"]) > 20 and spec["words"]["map"]
    assert audio == (1, 2, 8000)  # the narration keeps the Voice's format: mono, 16-bit, its rate
    assert client.get(s["url"]).content == b"fake mp4" and client.get(s["poster"]).content == b"fake png"
    assert "00:00:00.000 -->" in client.get(s["captions"]).text and N in client.get(s["captions"]).text
    assert client.get(f"/api/courses/{cid}/blocks/{bid}/video/{'0' * 16}.mp4").status_code == 404


def test_nothing_installed_leaves_the_block_pending_with_a_note_and_never_crashes_the_run(client, material, model, media):
    cid, _ = course(client, material, model, [PROSE, video()])  # video rendering is not installed
    bid = mine(client, cid)["id"]
    s = client.get(f"/api/courses/{cid}/blocks/{bid}/video").json()
    assert s["state"] == "pending" and "Install video rendering" in s["note"] and s["narration"] == [N] * 2
    assert not media.renders
    media.video, media.have = True, set()  # rendering is there, but no Voice
    s = client.get(f"/api/courses/{cid}/blocks/{bid}/video").json()
    assert s["state"] == "pending" and "install one in Settings" in s["note"] and not media.renders


def test_a_failed_render_goes_to_the_review_queue_with_its_log(client, material, model, media):
    media.video, media.render_error = True, "manim: LaTeX Error: File not found"
    cid, _ = course(client, material, model, [PROSE, video()])
    bid = mine(client, cid)["id"]
    s = state(client, cid, bid)
    assert s["state"] == "failed" and "LaTeX Error" in s["error"]
    queue = [q for q in client.get("/api/review-blocks").json() if q["id"] == bid]
    assert queue and any(f.startswith("video: ") and "LaTeX Error" in f for f in queue[0]["flags"]) and queue[0]["classes"] == ["video-render"]
    assert len(renders(media, bid)) == 1  # not retried on its own
    state(client, cid, bid)
    assert len(renders(media, bid)) == 1
    media.render_error = None
    assert client.post(f"/api/courses/{cid}/blocks/{bid}/video/retry").status_code == 200
    assert state(client, cid, bid)["state"] == "ready"
    assert not [q["flags"] for q in client.get("/api/review-blocks").json() if q["id"] == bid]  # fixed: out of the queue


def test_a_changed_block_renders_again_another_voice_reuses_the_picture_and_each_voice_keeps_its_own(client, material, model, media, data_dir):
    media.video = True
    media.have |= {"audio8"}
    cid, _ = course(client, material, model, [PROSE, video()])
    bid, orig = mine(client, cid)["id"], mine(client, cid)["data"]
    assert state(client, cid, bid)["state"] == "ready" and len(renders(media, bid)) == 1
    assert state(client, cid, bid)["state"] == "ready" and len(renders(media, bid)) == 1  # unchanged: not rendered again
    edited = {**mine(client, cid)["data"], "narration": [N, "Une autre façon de le dire, avec d'autres mots."]}
    assert client.put(f"/api/courses/{cid}/blocks/{bid}", json={"data": edited}).status_code == 200
    assert state(client, cid, bid)["state"] == "ready" and len(renders(media, bid)) == 2
    assert client.put("/api/voices", json={"voice": "audio8"}).status_code == 200
    assert state(client, cid, bid)["state"] == "ready" and len(renders(media, bid)) == 2  # the picture is kept: only fitted to the new narration
    (picture, old, new, _), = [r for r in media.retimes if r[3].parent.name == str(bid)]
    assert picture.exists() and len(old) == len(new) and all(n >= 1.1 for n in new)  # never shorter than the scene's animations
    assert {v for _, _, v, _ in media.spoken} >= {"kokoro", "audio8"}
    spoken = len(media.spoken)
    assert client.put("/api/voices", json={"voice": "kokoro"}).status_code == 200  # switched back: kokoro's Video was kept
    assert state(client, cid, bid)["state"] == "ready" and len(renders(media, bid)) == 2 and len(media.spoken) == spoken
    assert len(list(data_dir.rglob(f"videos/{bid}/*.mp4"))) == 2  # one per Voice
    assert client.put(f"/api/courses/{cid}/blocks/{bid}", json={"data": orig}).status_code == 200
    assert state(client, cid, bid)["state"] == "ready" and len(renders(media, bid)) == 3
    assert len(media.spoken) == spoken  # the first narration was recorded in kokoro before: reused, not spoken again
    assert len(list(data_dir.rglob(f"videos/{bid}/*.mp4"))) == 1  # the edit made every Voice's old Video stale
    assert len(list(data_dir.rglob(f"videos/{bid}/*.picture"))) == 1  # and the old picture


def test_narration_maths_is_spoken_in_words_and_nothing_with_a_symbol_reaches_a_voice(client, material, model, media, monkeypatch):
    media.video = True
    real = listen.math_speech
    monkeypatch.setattr(listen, "math_speech", lambda latex, lang: real(latex, lang) | {l: None for l in latex if "frac{c}" in l})  # one the engine cannot say
    narration = [r"La formule $\frac{a}{b}$ et un_identifiant. Puis {des accolades} et x^2.", r"Puis $\frac{c}{d}$ que rien ne dit."]
    cid, _ = course(client, material, model, [PROSE, video(narration=narration)])
    blk = mine(client, cid)
    bid = blk["id"]
    assert state(client, cid, bid)["state"] == "ready", (blk["status"], blk["flags"])
    heard = [t for t, *_ in media.spoken]
    assert heard and not [t for t in heard if voices.FORBIDDEN.search(t)]
    assert any("a sur b" in t for t in heard) and any("la formule affichée" in t for t in heard), heard[:6]
    flags = [q for q in client.get("/api/review-blocks").json() if q["id"] == bid]
    assert flags and any(f.startswith("listen:") for f in flags[0]["flags"]), flags[0]["flags"]  # as in Listen: the Block is queued for review


def test_every_chapter_gets_one_overview_video_made_from_its_overview_and_map(client, material, model, media):
    media.video = True
    cid, sections = course(client, material, model, [PROSE])
    overviews = videos_of(client, cid)
    chapters = client.get(f"/api/courses/{cid}/reader").json()
    assert len(overviews) == len(chapters) and all(v["data"]["template"] == "chapter_overview" for v in overviews)
    first = chapters[0]["sections"][0]["blocks"]
    assert first[0]["component"] == "video"  # opens the Chapter
    params = first[0]["data"]["params"]
    assert params["title"] == chapters[0]["title"] and [s["title"] for s in params["sections"]] == [s["title"] for s in chapters[0]["sections"]]
    assert len(first[0]["data"]["narration"]) == 1 + len(params["sections"])
    assert state(client, cid, first[0]["id"])["state"] == "ready"
    assert "chapter_overview" in {sp["template"] for sp, _, _ in media.renders}


def test_an_overview_says_only_what_a_voice_can_say():
    """Course 10 Block 4293 and course 12 Block 4705: a "\\n" escaped twice glued the overview's list of Sections onto its third
    sentence, and maths written without $…$ ("π_n = π_0 P^n", "p_{ij}") left braces and underscores: both sent the Video to review."""
    import json
    import sqlite3
    from course_factory.videos import overview_data
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("CREATE TABLE chapters (id INTEGER PRIMARY KEY, title TEXT, plan TEXT);"
                     "CREATE TABLE sections (id INTEGER PRIMARY KEY, chapter_id INTEGER, position INTEGER, title TEXT);"
                     "INSERT INTO sections VALUES (1, 1, 0, 'Matrice de transition'), (2, 1, 1, 'Loi d''une chaîne');")
    plan = {"overview": "Le chapitre construit la chaîne de Markov. On dérive la loi marginale π_n = π_0 P^n. Elle vaut $\\pi_0 P^n$."
                        "\\n\\n- Matrice de transition : la matrice $P$.",
            "sections": [{"title": "Matrice de transition", "objectives": [{"text": "State la définition de p_{ij} = P(X_1 = x_j | X_0 = x_i)."}]},
                         {"title": "Loi d'une chaîne", "objectives": [{"text": "Calculer la loi $\\pi_n = \\pi_0 P^n$."}]}]}
    db.execute("INSERT INTO chapters VALUES (1, 'Chapitre IV', ?)", (json.dumps(plan),))
    data = overview_data(db, 1)
    assert data["narration"] == ["Le chapitre construit la chaîne de Markov. Elle vaut $\\pi_0 P^n$.", "Matrice de transition.",
                                 "Loi d'une chaîne. Calculer la loi $\\pi_n = \\pi_0 P^n$."]
    assert [s["line"] for s in data["params"]["sections"]][0] == ""


def test_video_rendering_installs_and_removes_from_settings(client, media):
    s = client.get("/api/video").json()
    assert not s["installed"] and s["size_mb"] > 100 and s["version"]
    assert client.post("/api/video/install", json={}).status_code == 422  # confirm it first: it downloads
    assert client.post("/api/video/install", json={"confirm": True}).status_code == 202
    end = time.time() + 5
    while not client.get("/api/video").json()["installed"] and time.time() < end:
        time.sleep(0.05)
    assert client.get("/api/video").json()["installed"] and client.post("/api/video/install", json={"confirm": True}).status_code == 409
    assert client.delete("/api/video").status_code == 204 and not client.get("/api/video").json()["installed"]


def test_a_course_written_before_rendering_was_installed_gets_its_overview_videos_on_request(client, material, model, media):
    cid, _ = course(client, material, model, [PROSE])
    assert videos_of(client, cid) == [] and client.post(f"/api/courses/{cid}/videos/overviews").status_code == 409
    media.video = True
    assert client.post(f"/api/courses/{cid}/videos/overviews").status_code == 200
    client.post(f"/api/courses/{cid}/videos/overviews")  # twice adds nothing more
    assert len(videos_of(client, cid)) == len(client.get(f"/api/courses/{cid}/reader").json())
