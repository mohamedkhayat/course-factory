import time

import pytest

from conftest import FakeMedia  # noqa: F401
from course_factory import listen, voices
from course_factory.media import speak_checked
from test_animation import GOOD as ANIMATION
from test_chapters import generate
from test_kind_diagram import CITE, GOOD as KINDS
from test_learner import clock, published  # noqa: F401  (fixture)
from test_tutor import events

PROSE = {"component": "prose", "origin": "model_added", "data": {"markdown": "Le gradient est une idée. Il pointe vers la montée, par exemple $\\frac{a}{b}$."}}
CODE = {"component": "code", "origin": "model_added", "data": {"language": "python", "code": "def f(x):\n    return x\n\nprint(f(1))"}}
QUIZ = {"component": "quiz", "origin": "model_added", "data": {"questions": [
    {"prompt": "SECRET ANSWER ?", "options": ["oui", "non"], "correct": [0], "explanation": "Par définition."}]}}
TREE = {"component": "kind_diagram", "origin": "from_source", "citations": [CITE], "data": KINDS["tree"]}
STEPS = {"component": "stepped_animation", "origin": "from_source", "citations": [CITE], "data": ANIMATION}


def course(client, material, model, blocks, language="fr"):
    cid = generate(client, material, model, goal={"goal": "deep", "language": language}, blocks=blocks)
    for c in client.get(f"/api/courses/{cid}/outline").json()["chapters"]:
        client.post(f"/api/courses/{cid}/chapters/{c['id']}/publish")
    sections = [s for ch in client.get(f"/api/courses/{cid}/reader").json() for s in ch["sections"]]
    return cid, sections


def wait_idle(client):
    for _ in range(200):
        if not client.get("/api/media").json()["jobs"]:
            return
        time.sleep(0.02)
    raise AssertionError("the media lane did not empty")


def listen_to(client, cid, sid):
    r = client.post(f"/api/courses/{cid}/sections/{sid}/listen")
    assert r.status_code == 200, r.text
    evs = events(r)
    return dict(evs[0][1]) | {"clips": [d for e, d in evs if e == "clip"], "last": evs[-1][0]}


def test_the_script_follows_the_blocks_in_order_and_skips_practice(client, material, model, media):
    cid, sections = course(client, material, model, [PROSE, QUIZ, CODE, TREE, STEPS])
    s = listen_to(client, cid, sections[0]["id"])
    texts = [x["text"] for x in s["sentences"]]
    joined = " ".join(texts)
    assert texts[0].startswith(sections[0]["title"])  # the title opens it
    assert "SECRET ANSWER" not in joined and "oui" not in joined  # practice is not read
    assert "a sur b" in joined and "$" not in joined  # maths is words
    assert "Un exemple Python, 4 lignes." in texts  # code is one announcement
    order = [joined.index(w) for w in ("Le gradient est une idée", "Un exemple Python", "Etape a", "Etape d", "Les enregistrements arrivent", "Le jeton continue")]
    assert order == sorted(order)
    assert [x["n"] for x in s["sentences"]] == list(range(len(texts)))
    assert all(x["end"] > x["start"] for x in s["sentences"]) and s["last"] == "done" and len(s["clips"]) == len(texts)
    assert s["sentences"][1]["block_id"] is not None and s["sentences"][0]["block_id"] is None
    assert [c[0] for c in media.spoken if c[0] in texts] == texts  # in order (the other Sections were spoken ahead too)


def test_a_diagram_is_read_item_by_item_in_walk_order():
    tree = {**KINDS["tree"]}
    assert listen.walk(tree) == ["a", "b", "d", "c"]  # depth first, not item order
    assert listen.walk(KINDS["fan_out"]) == ["a", "b", "c"] and listen.walk(KINDS["pipeline"]) == ["a", "b", "c"]


FORMULAS = [r"\frac{a}{b}", r"\frac{\partial f}{\partial x}", r"x^2 + y^{n+1}", r"\sum_{i=1}^{n} i^2", r"\prod_{k=0}^{m} x_k",
            r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}", r"\alpha + \beta - \gamma", r"\lambda_{\min}(A)", r"\nabla f(x) = 0",
            r"\int_0^1 x\,dx", r"\|x\|_2^2", r"x_{k+1} = x_k - \eta \nabla f(x_k)"]


@pytest.mark.parametrize("language", ["en", "fr"])
def test_formulas_never_reach_a_voice_with_a_symbol_in_them(language, media):
    spoken = listen.math_speech(FORMULAS, language)
    for latex, words in spoken.items():
        assert words and not voices.FORBIDDEN.search(words), latex  # every real formula becomes plain words
    assert listen.math_speech([r"\badmacro{"], language) == {r"\badmacro{": None}
    with pytest.raises(ValueError):  # and the last line of defence refuses anything left
        for bad in ("x_1", "a^2", r"\alpha", "$x$", "{x}"):
            speak_checked(media, bad, language, "kokoro")
    assert media.spoken == []


def test_a_formula_that_cannot_be_spoken_is_said_as_on_screen_and_the_block_goes_to_the_review_queue(client, material, model, media, monkeypatch):
    monkeypatch.setattr(listen, "math_speech", lambda latex, lang: {l: None for l in latex})
    cid, sections = course(client, material, model, [PROSE], language="en")
    listen_to(client, cid, sections[0]["id"])
    said = " ".join(c[0] for c in media.spoken)
    assert "the formula on screen" in said and "$" not in said and "frac" not in said
    queue = [q for q in client.get("/api/review-blocks").json() if q["course_id"] == cid]
    assert queue and queue[0]["classes"] == ["listen-formula"]


def test_language_runs_go_to_the_voice_for_their_language(client, material, model, media, monkeypatch):
    monkeypatch.setitem(voices.REGISTRY["klein"], "languages", ["en"])  # Klein reads English only here
    monkeypatch.setitem(voices.REGISTRY["kokoro"], "languages", ["en"])  # so the French run has to fall back
    media.have = {"kokoro", "klein", "audio8"}
    client.put("/api/voices", json={"voice": "kokoro"})
    english = {**PROSE, "origin": "model_added", "data": {"markdown": "The gradient points uphill."}}
    quote = {"component": "theorem_box", "origin": "from_source", "citations": [CITE],
             "data": {"kind": "definition", "title": "Gradient", "statement": "Le gradient pointe vers la plus forte croissance dans le cours."}}
    cid, sections = course(client, material, model, [english, quote], language="mixed")
    monkeypatch.setattr(listen, "page_texts", lambda ctx, cid, refs: [{"text": "le gradient est une fonction dans le cours des"}])
    listen_to(client, cid, sections[0]["id"])
    by = {(lang, voice) for _, lang, voice, _ in media.spoken}
    assert ("en", "kokoro") in by and ("fr", "audio8") in by  # the first installed Voice that reads French
    assert client.get("/api/voices").json()["reads"]["fr"] == {"voice": "audio8", "fallback": True, "sample": voices.SAMPLE["fr"]}


def test_in_a_mixed_course_each_paragraph_of_the_models_words_keeps_its_own_language(client, material, model, media):
    media.have = {"kokoro"}
    caption = {"component": "intuition", "origin": "model_added", "data": {
        "idea": "The step is the size of the move, and it is the one thing that decides if the run of the method is stable or not.",
        "analogy": "Au-delà de $\\frac{2}{L}$, les itérés divergent."}}
    cid, sections = course(client, material, model, [caption], language="mixed")
    s = listen_to(client, cid, sections[0]["id"])
    french = [x for x in s["sentences"] if x["text"].startswith("Au-delà")]
    assert french and french[0]["language"] == "fr" and "divided" not in french[0]["text"]  # the maths is spoken in French too


def test_a_single_language_course_is_read_in_that_language(client, material, model, media):
    cid, sections = course(client, material, model, [PROSE], language="en")
    listen_to(client, cid, sections[0]["id"])
    assert {lang for _, lang, _, _ in media.spoken} == {"en"}


def test_audio_is_cached_per_section_and_voice_and_a_changed_section_invalidates_it(client, material, model, media):
    cid, sections = course(client, material, model, [PROSE, CODE])
    sid = sections[0]["id"]
    first = listen_to(client, cid, sid)
    n = len(media.spoken)
    again = listen_to(client, cid, sid)
    assert len(media.spoken) == n and again["key"] == first["key"]  # replayed, not spoken again
    clip = client.get(first["clips"][0]["url"])
    assert clip.status_code == 200 and clip.headers["content-type"] == "audio/wav" and clip.content[:4] == b"RIFF"
    assert client.get(first["clips"][0]["url"].replace(first["key"], "0" * 16)).status_code == 404

    media.have.add("klein")  # another Voice has its own audio
    client.put("/api/voices", json={"voice": "klein"})
    other = listen_to(client, cid, sid)
    assert other["voice"] == "klein" and other["key"] != first["key"] and len(media.spoken) > n
    assert client.get(first["clips"][0]["url"]).status_code == 200  # kokoro's audio is still there

    block = client.get(f"/api/courses/{cid}/reader").json()[0]["sections"][0]["blocks"][0]
    client.put("/api/voices", json={"voice": "kokoro"})
    assert client.put(f"/api/courses/{cid}/blocks/{block['id']}", json={"data": {"markdown": "Autre texte entièrement."}}).status_code == 200
    changed = listen_to(client, cid, sid)
    assert changed["key"] != first["key"]
    assert client.get(first["clips"][0]["url"]).status_code == 404  # the stale audio is gone


def test_a_section_with_nothing_to_read_is_refused_and_without_an_installed_voice_too(client, material, model, media):
    cid, sections = course(client, material, model, [QUIZ])
    assert client.post(f"/api/courses/{cid}/sections/{sections[0]['id']}/listen").status_code == 409
    cid, sections = course(client, material, model, [PROSE])
    media.have.clear()
    r = client.post(f"/api/courses/{cid}/sections/{sections[0]['id']}/listen")
    assert r.status_code == 409 and "install" in r.json()["detail"].lower()


def test_the_registry_holds_the_pinned_facts():
    r = voices.REGISTRY
    assert {v: x["revision"] for v, x in r.items()} == {
        "kokoro": "f3ff3571791e39611d31c381e3a41a3af07b4987", "audio8": "4d02073010389bdcc86e2f0bc52137b3e2ab7580",
        "klein": "25e0e73bebba71e5985bc369628ebdcb81bf7116", "omnivoice": "c5fdb5ccb189668d56333f77ba2629f4cd7535f4"}
    assert r["kokoro"]["repo"] == "hexgrad/Kokoro-82M" and r["kokoro"]["default"] and voices.DEFAULT == "kokoro"
    assert "CC-BY-NC" in r["omnivoice"]["licence"] and r["kokoro"]["licence"] == "Apache-2.0"
    assert [v for v, x in r.items() if x["custom_code"]] == ["audio8", "klein"]
    assert {"regex", "phonemizer-fork", "espeakng-loader"} <= {p.split("==")[0] for p in r["klein"]["packages"]}
    assert all("==" in p or " @ " in p for x in r.values() for p in x["packages"])  # every package pinned
    from course_factory.media import WORKERS
    assert "KLEINTTS_NO_AUTO_INSTALL" in (WORKERS / "klein_worker.py").read_text()


def test_install_needs_a_confirmation_that_shows_the_size_and_voices_can_be_chosen_and_removed(client, media):
    voices_ = {v["id"]: v for v in client.get("/api/voices").json()["voices"]}
    assert voices_["kokoro"]["installed"] and voices_["kokoro"]["selected"] and voices_["kokoro"]["default"] and not voices_["audio8"]["installed"]
    assert voices_["omnivoice"]["licence"].startswith("Code Apache-2.0; weights CC-BY-NC")
    refused = client.post("/api/voices/audio8/install", json={})
    assert refused.status_code == 422 and "2600 MB" in refused.json()["detail"] and media.installs == []
    assert client.put("/api/voices", json={"voice": "audio8"}).status_code == 409  # not installed yet

    assert client.post("/api/voices/audio8/install", json={"confirm": True}).status_code == 202
    assert media.installs == ["audio8"]
    assert client.post("/api/voices/audio8/install", json={"confirm": True}).status_code == 409  # already there
    assert client.put("/api/voices", json={"voice": "audio8"}).json()["selected"] == "audio8"
    assert client.put("/api/voices", json={"voice": "nope"}).status_code == 404

    assert client.put("/api/voices", json={"speakers": {"klein": {"fr": "Camille"}}}).status_code == 200
    assert client.put("/api/voices", json={"speakers": {"klein": {"fr": "Sarah"}}}).status_code == 422  # not a French speaker
    assert client.put("/api/voices", json={"fallback": {"fr": "audio8"}}).json()["fallback"] == {"fr": "audio8"}
    assert client.put("/api/voices", json={"gpu": True}).json()["gpu"] is True and media.gpu
    assert client.put("/api/voices", json={"gpu": False}).json()["gpu"] is False
    assert client.get("/api/voices").json()["gpu"] is False  # off by default

    assert client.delete("/api/voices/audio8").status_code == 204
    assert client.get("/api/voices").json()["selected"] == "kokoro" and "audio8" not in media.have  # the choice falls back to the default
    assert client.delete("/api/voices/audio8").status_code == 409


def test_preview_speaks_the_sample_sentence_in_the_picked_speaker(client, media):
    media.have.add("klein")
    client.put("/api/voices", json={"speakers": {"klein": {"en": "Owen"}}})
    r = client.post("/api/voices/klein/preview", json={"language": "en"})
    assert r.status_code == 200 and r.content[:4] == b"RIFF"
    assert media.spoken == [(voices.SAMPLE["en"], "en", "klein", "Owen")]
    assert client.post("/api/voices/audio8/preview", json={"language": "en"}).status_code == 409


def test_dictation_transcribes_in_the_course_language_and_deletes_the_recording(client, material, model, media, data_dir):
    cid, _ = course(client, material, model, [PROSE], language="fr")
    r = client.post(f"/api/courses/{cid}/dictate", files={"audio": ("rec.webm", b"fake-opus-bytes", "audio/webm")})
    assert r.status_code == 200 and r.json() == {"text": "bonjour, la convexité"}
    (path, languages, existed), = media.heard
    assert languages == ["fr", "en"] and existed and not path.exists()  # it was there to be heard, and is gone now
    assert not list((data_dir / "courses" / str(cid) / "dictation").iterdir())

    media.transcribe = lambda audio, languages: (_ for _ in ()).throw(RuntimeError("boom"))  # a failure deletes it too
    assert client.post(f"/api/courses/{cid}/dictate", files={"audio": ("rec.webm", b"x", "audio/webm")}).status_code == 502
    assert not list((data_dir / "courses" / str(cid) / "dictation").iterdir())
    assert client.post("/api/courses/999/dictate", files={"audio": ("r.webm", b"x", "audio/webm")}).status_code == 404


def test_listening_from_a_block_speaks_that_blocks_sentences_first(client, material, model, media):
    client.post("/api/media/pause", json={"paused": True})  # the audio made ahead while the Course is written waits
    cid, sections = course(client, material, model, [PROSE, CODE])
    for j in client.get("/api/media").json()["jobs"]:
        assert j["kind"] == "listen" and j["background"] and j["course"] == cid
        assert client.post(f"/api/media/jobs/{j['id']}/stop").status_code == 200
    client.post("/api/media/pause", json={"paused": False})
    wait_idle(client)
    sid, code = sections[0]["id"], sections[0]["blocks"][1]["id"]
    r = client.post(f"/api/courses/{cid}/sections/{sid}/listen?block={code}")
    assert r.status_code == 200, r.text
    script = events(r)[0][1]["sentences"]
    first = next(x for x in script if x["block_id"] == code)
    assert media.spoken[0][0] == first["text"]  # the Block the learner picked is spoken before the Section's title
    assert sorted(t for t, *_ in media.spoken) == sorted(x["text"] for x in script)  # then the rest, each once


def test_written_sections_get_their_audio_ahead_and_a_voice_switched_back_reuses_its_recordings(client, material, model, media):
    cid, sections = course(client, material, model, [PROSE, CODE])
    wait_idle(client)
    ahead = len(media.spoken)
    assert ahead > 0  # made while the Course was written, in the chosen Voice
    first = listen_to(client, cid, sections[0]["id"])
    assert len(media.spoken) == ahead and first["voice"] == "kokoro"  # Listen starts with nothing left to speak

    media.have.add("klein")
    client.put("/api/voices", json={"voice": "klein"})
    listen_to(client, cid, sections[0]["id"])
    assert len(media.spoken) > ahead and media.spoken[-1][2] == "klein"
    n = len(media.spoken)
    client.put("/api/voices", json={"voice": "kokoro"})
    back = listen_to(client, cid, sections[0]["id"])
    assert len(media.spoken) == n and back["key"] == first["key"]  # kokoro's recordings were kept

    block = sections[0]["blocks"][1]  # one Block changes: only its sentences are spoken again
    client.put(f"/api/courses/{cid}/blocks/{block['id']}", json={"data": {"language": "python", "code": "print(2)"}})
    listen_to(client, cid, sections[0]["id"])
    assert [t for t, *_ in media.spoken[n:]] == ["Un exemple Python, 1 ligne."]

