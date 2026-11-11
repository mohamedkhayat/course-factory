import json
import pytest

from course_factory.chapters import REPAIRS
from test_outline import to_outline_gate

GRADIENT, EXERCICES, CONVEXES = "Gradient", "Exercices", "Ensembles convexes"


def generate(client, material, model, goal=None, priorities=None, blocks=None):
    """Drives a Course through both gates; `blocks` replaces the Blocks the fake model writes for every Section."""
    if blocks is not None:
        model.handlers["write_section"] = lambda prompt, files: {"blocks": blocks}
    cid = to_outline_gate(client, material, model, goal)
    if priorities:
        chapters = client.get(f"/api/courses/{cid}/outline").json()["chapters"]
        for c in chapters:
            c["priority"] = priorities.get(c["title"], "normal")
        assert client.put(f"/api/courses/{cid}/outline", json={"chapters": chapters}).status_code == 200
    assert client.post(f"/api/courses/{cid}/gates/outline").status_code == 200
    return cid


def sections_written(model):
    return [model.section_of(p) for step, p in model.prompts if step == "write_section"]


def chapters(client, cid):
    return {c["title"]: c for c in client.get(f"/api/courses/{cid}/outline").json()["chapters"]}


def first_block(client, cid):
    ch = chapters(client, cid)["Convexité"]
    blocks = client.get(f"/api/courses/{cid}/chapters/{ch['id']}").json()["sections"][0]["blocks"]
    return next((b for b in blocks if b["component"] != "prose"), blocks[0])  # past the orienting opening


def one_block(component, data, origin="model_added", citations=()):
    return [{"component": component, "data": data, "origin": origin, "citations": list(citations)}]


def test_cram_generates_by_priority_and_skips_skip(client, material, model):
    cid = generate(client, material, model, priorities={"Méthodes de descente": "focus"})
    assert sections_written(model) == [GRADIENT, EXERCICES, CONVEXES]
    model.prompts.clear()
    cid = generate(client, material, model, priorities={"Convexité": "skip"})
    assert sections_written(model) == [GRADIENT, EXERCICES]
    assert chapters(client, cid)["Convexité"]["status"] == "planned"
    assert client.get(f"/api/courses/{cid}/run").json()["gate"] == "chapter_review"


def test_deep_generates_in_course_order(client, material, model):
    generate(client, material, model, goal={"goal": "deep"}, priorities={"Méthodes de descente": "focus"})
    assert sections_written(model) == [CONVEXES, GRADIENT, EXERCICES]


def test_section_prompt_has_cited_page_text_and_catalogue(client, material, model):
    generate(client, material, model)
    prompt = next(p for step, p in model.prompts if step == "write_section")
    assert "page text of" in prompt and "iteration_table" in prompt and "explanations, intuitions and hints in English" in prompt


def test_chapters_wait_for_review_and_publishing_makes_them_readable(client, material, model):
    cid = generate(client, material, model)
    assert {c["status"] for c in chapters(client, cid).values()} == {"in_review"}
    assert client.get(f"/api/courses/{cid}/reader").json() == []
    review = client.get(f"/api/courses/{cid}/review").json()
    assert [c["title"] for c in review] == ["Convexité", "Méthodes de descente"]
    assert len(review[1]["blocks"]) == 6 and review[1]["blocks"][0]["section"] == GRADIENT
    chid = review[0]["id"]
    assert client.post(f"/api/courses/{cid}/chapters/{chid}/publish").status_code == 200
    assert client.post(f"/api/courses/{cid}/chapters/{chid}/publish").status_code == 409
    readable = client.get(f"/api/courses/{cid}/reader").json()
    assert [c["title"] for c in readable] == ["Convexité"]
    block = readable[0]["sections"][0]["blocks"][1]
    assert block["component"] == "theorem_box" and block["origin"] == "from_source"
    assert block["citations"] == [{"source": "cours.pdf", "page": 1, "quote": ""}]
    actions = [t["owner_action"] for t in client.get(f"/api/courses/{cid}/traces").json() if t["step"] == "chapter_review_gate"]
    assert actions == ["published"]


def test_failing_block_is_repaired(client, material, model):
    bad = {"questions": [{"prompt": "?", "options": ["a", "b"], "correct": [5], "explanation": "e"}]}
    good = {"questions": [{"prompt": "?", "options": ["a", "b"], "correct": [1], "explanation": "e"}]}
    model.handlers["repair_block"] = lambda prompt, files: (
        {"block": one_block("quiz", good)[0]} if "out of range" in prompt else {"block": {}})
    cid = generate(client, material, model, blocks=one_block("quiz", bad))
    b = first_block(client, cid)
    assert b["status"] == "ok" and b["data"]["questions"][0]["correct"] == [1]


def test_block_is_flagged_and_kept_after_its_repairs_fail(client, material, model):
    cid = generate(client, material, model, blocks=one_block("quiz", {"questions": [
        {"prompt": "?", "options": ["a", "A "], "correct": [0, 1], "explanation": ""}]}))
    b = first_block(client, cid)
    assert b["status"] == "flagged"
    assert any("not distinct" in f for f in b["flags"]) and any("exactly one" in f for f in b["flags"])
    assert any("explanation" in f for f in b["flags"])
    repairs = [p for step, p in model.prompts if step == "repair_block"]
    assert len(repairs) == 3 * REPAIRS  # three Sections, REPAIRS repairs each
    review = client.get(f"/api/courses/{cid}/review").json()
    assert review[0]["blocks"][0]["status"] == "flagged"


def test_flagged_blocks_come_first_in_review(client, material, model):
    blocks = one_block("prose", {"markdown": "fine"}) + one_block("callout", {"tone": "loud", "text": "x"})
    cid = generate(client, material, model, blocks=blocks)
    review = client.get(f"/api/courses/{cid}/review").json()
    assert [b["component"] for b in review[0]["blocks"]] == ["callout", "prose"]


def test_math_and_diagram_errors_are_caught(client, material, model):
    blocks = (one_block("prose", {"markdown": r"Bien: $\frac{1}{2}$ mais $\frac{1}{$"})
              + one_block("diagram", {"mermaid": "graph TD\n  A-->B-->C-->D"})
              + one_block("diagram", {"mermaid": "graph TD\n  A-->"}))
    cid = generate(client, material, model, blocks=blocks)
    ch = chapters(client, cid)["Convexité"]
    got = client.get(f"/api/courses/{cid}/chapters/{ch['id']}").json()["sections"][0]["blocks"]
    assert [b["status"] for b in got] == ["flagged", "ok", "flagged"]


def test_sympy_claims_are_checked(client, material, model):
    def example(expected):
        return one_block("worked_example", {"title": "t", "problem": "p", "steps": ["s"], "answer": "a",
                                            "claims": [{"op": "grad", "expr": "x1**2 + x1*x2", "vars": ["x1", "x2"], "expected": expected}]})
    cid = generate(client, material, model, blocks=example(["2*x1 + x2", "x1"]) + example(["2*x1", "x1"]))
    ch = chapters(client, cid)["Convexité"]
    got = client.get(f"/api/courses/{cid}/chapters/{ch['id']}").json()["sections"][0]["blocks"]
    assert [b["status"] for b in got] == ["ok", "flagged"]
    assert "sympy" in got[1]["flags"][0]


def test_iteration_table_rows_come_from_the_app(client, material, model):
    cid = generate(client, material, model, blocks=one_block("iteration_table", {
        "method": "gradient", "f": "x**2", "vars": ["x"], "x0": [1], "step": 0.25, "iterations": 2,
        "rows": [{"k": 0, "x": [42]}]}))
    rows = first_block(client, cid)["data"]["rows"]
    assert [r["x"] for r in rows] == [[1.0], [0.5], [0.25]] and rows[1]["f"] == 0.25


def test_newton_iteration_converges_in_one_step_on_a_quadratic(client, material, model):
    cid = generate(client, material, model, blocks=one_block("iteration_table", {
        "method": "newton", "f": "(x1-1)**2 + 2*(x2+3)**2", "vars": ["x1", "x2"], "x0": [5, 5], "iterations": 1}))
    assert first_block(client, cid)["data"]["rows"][1]["x"] == [1.0, -3.0]


def test_from_source_block_needs_a_real_citation(client, material, model):
    cid = generate(client, material, model, blocks=one_block("prose", {"markdown": "x"}, origin="from_source")
                   + one_block("prose", {"markdown": "x"}, origin="from_source", citations=[{"source": "cours.pdf", "page": 7}]))
    ch = chapters(client, cid)["Convexité"]
    got = client.get(f"/api/courses/{cid}/chapters/{ch['id']}").json()["sections"][0]["blocks"]
    assert "at least one Citation" in got[0]["flags"][0] and "does not exist" in got[1]["flags"][0]


def test_a_block_going_beyond_its_pages_becomes_model_added(client, material, model):
    model.handlers["judge_grounding"] = lambda prompt, files: {"grounded": False, "reason": "the bound is not in the notes"}
    cid = generate(client, material, model)
    b = first_block(client, cid)
    assert b["status"] == "ok" and b["flags"] == [] and b["origin"] == "model_added"
    assert b["citations"]  # kept as references
    judged = [p for step, p in model.prompts if step == "judge_grounding"]
    assert len(judged) == 3  # only the From source Blocks, one call per Section


def test_a_block_contradicting_its_pages_is_repaired_and_judged_again(client, material, model):
    verdicts = iter([{"results": [{"block": 1, "grounded": False, "contradicts": True, "reason": "Sp(A) is wrong"}]}])
    model.handlers["judge_grounding"] = lambda prompt, files: next(verdicts, {"grounded": True, "reason": ""})
    cid = generate(client, material, model)
    b = first_block(client, cid)
    assert b["status"] == "ok" and b["origin"] == "from_source"
    repairs = [p for step, p in model.prompts if step == "repair_block"]
    assert len(repairs) == 1 and "Sp(A) is wrong" in repairs[0]


def test_owner_edit_is_revalidated(client, material, model):
    cid = generate(client, material, model)
    b = first_block(client, cid)
    r = client.put(f"/api/courses/{cid}/blocks/{b['id']}", json={"data": {"kind": "nonsense", "statement": "s"}})
    assert r.status_code == 422 and "kind" in json.dumps(r.json())
    r = client.put(f"/api/courses/{cid}/blocks/{b['id']}", json={"data": {"kind": "theorem", "statement": "Énoncé"}})
    assert r.status_code == 200 and r.json()["data"]["statement"] == "Énoncé" and r.json()["status"] == "ok"
    assert first_block(client, cid)["data"]["kind"] == "theorem"


def test_owner_approves_a_flagged_block(client, material, model):
    cid = generate(client, material, model, blocks=one_block("prose", {"markdown": r"$\frac{$"}))
    b = first_block(client, cid)
    assert b["status"] == "flagged"
    assert client.post(f"/api/courses/{cid}/blocks/{b['id']}/approve").json()["status"] == "ok"


def test_regenerate_with_a_note(client, material, model):
    cid = generate(client, material, model)
    b = first_block(client, cid)
    model.handlers["repair_block"] = lambda prompt, files: {"block": {**json.loads(prompt.split("BLOCK:", 1)[1]),
        "data": {"kind": "theorem", "statement": "Plus court." if "trop long" in prompt else "?"}}}
    r = client.post(f"/api/courses/{cid}/blocks/{b['id']}/regenerate", json={"note": "trop long"})
    assert r.status_code == 200 and r.json()["data"]["statement"] == "Plus court."
    actions = [t["owner_action"] for t in client.get(f"/api/courses/{cid}/traces").json() if t["step"] == "chapter_review_gate"]
    assert actions == ["regenerated"]


def test_resume_regenerates_only_unfinished_chapters(client, material, model):
    calls = {"n": 0}
    original = model.handlers["write_section"]

    def flaky(prompt, files):
        calls["n"] += 1
        if model.section_of(prompt) == GRADIENT and calls["n"] < 5:
            return "not json"
        return original(prompt, files)
    model.handlers["write_section"] = flaky
    cid = generate(client, material, model)
    run = client.get(f"/api/courses/{cid}/run").json()
    assert run["status"] == "failed"
    assert chapters(client, cid)["Convexité"]["status"] == "in_review"
    model.prompts.clear()
    assert client.post(f"/api/courses/{cid}/run/retry").status_code == 200
    assert sections_written(model) == [GRADIENT, EXERCICES]
    assert {c["status"] for c in chapters(client, cid).values()} == {"in_review"}
    assert client.get(f"/api/courses/{cid}/run").json()["gate"] == "chapter_review"


def test_run_progress_streams_until_the_run_stops(client, material, model):
    cid = to_outline_gate(client, material, model)
    body = client.get(f"/api/courses/{cid}/run/events").text
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert body.startswith("event: status") and events[-1]["gate"] == "outline"
    assert client.get("/api/courses/999/run/events").status_code == 404


def test_run_pauses_at_chapter_review_until_the_last_chapter_is_published(client, material, model):
    cid = generate(client, material, model)
    run = client.get(f"/api/courses/{cid}/run").json()
    assert (run["status"], run["gate"]) == ("waiting", "chapter_review")
    first, second = client.get(f"/api/courses/{cid}/review").json()
    assert client.post(f"/api/courses/{cid}/gates/chapter_review").status_code == 409  # Chapters still wait
    client.post(f"/api/courses/{cid}/chapters/{first['id']}/publish")
    assert client.get(f"/api/courses/{cid}/run").json()["gate"] == "chapter_review"
    client.post(f"/api/courses/{cid}/chapters/{second['id']}/publish")
    assert client.get(f"/api/courses/{cid}/run").json()["status"] == "done"


def test_traces_record_check_results_and_durations(client, material, model):
    cid = generate(client, material, model, blocks=one_block("theorem_box", {"kind": "theorem", "statement": r"$\frac{1}{$"}))
    traces = client.get(f"/api/courses/{cid}/traces").json()
    section = next(t for t in traces if t["step"] == "write_section" and "block" in (t["checks"] or ""))
    [check] = json.loads(section["checks"])
    assert check["block"] == 0 and check["errors"]  # still broken after the repairs
    repair = next(t for t in traces if t["step"] == "repair_block")
    assert json.loads(repair["checks"])["errors"]
    assert all(t["duration_ms"] is not None for t in traces if t["step"] in ("write_section", "read_page"))


def test_time_left_comes_from_past_step_timings(client, material, model, data_dir):
    from course_factory import db as dbm
    from course_factory.generation import seconds_left
    cid = to_outline_gate(client, material, model)
    db = dbm.connect(data_dir / "course-factory.db")
    db.execute("INSERT INTO traces (course_id, step, harness_version, inputs, duration_ms) VALUES (?,?,?,?,?)",
               (cid, "write_section", "x", "{}", 3000))
    db.execute("INSERT INTO traces (course_id, step, harness_version, inputs, duration_ms) VALUES (?,?,?,?,?)",
               (cid, "repair_block", "x", "{}", 1000))
    assert seconds_left(db, cid) == 3 * 4  # 3 Sections to write, 4 s each with repairs; no past papers or Labs here
    from course_factory.generation import time_left
    assert time_left(db, cid)[0] == {"stage": "Sections", "left": 3, "seconds": 12}
    assert {s["stage"] for s in time_left(db, cid)} >= {"Sections", "Mock exams"}


def test_run_shows_each_chapter_with_its_sections_written(client, material, model):
    cid = to_outline_gate(client, material, model)
    before = client.get(f"/api/courses/{cid}/run").json()["progress"]
    assert (before["sections_done"], before["sections_total"]) == (0, 3)
    assert [s["state"] for c in before["chapters"] for s in c["sections"]] == ["waiting"] * 3
    client.post(f"/api/courses/{cid}/gates/outline")
    after = client.get(f"/api/courses/{cid}/run").json()["progress"]
    assert (after["sections_done"], after["sections_total"], after["fraction"]) == (3, 3, 1)
    ch = {c["title"]: c for c in after["chapters"]}["Méthodes de descente"]
    assert (ch["done"], ch["total"]) == (2, 2) and ch["sections"][0]["blocks"] > 0 and ch["sections"][0]["state"] == "done"
    assert sum(ch["components"].values()) == sum(s["blocks"] for s in ch["sections"])


def test_a_practical_subject_is_written_as_tutorials(client, material, model):
    plan = model.handlers["propose_outline"]
    model.handlers["propose_outline"] = lambda prompt, files: {**plan(prompt, files), "kind": "practical"}
    generate(client, material, model)
    prompts = [p for step, p in model.prompts if step == "write_section"]
    assert prompts and all("Subject: practical" in p for p in prompts)


def test_the_subject_defaults_to_mixed_when_the_outline_does_not_say(client, material, model):
    generate(client, material, model)
    assert all("Subject: mixed" in p for step, p in model.prompts if step == "write_section")


def test_run_shows_a_section_checking_repairing_judging_then_flagged(client, material, model):
    cid, seen = None, []
    states = lambda: [s["state"] for c in client.get(f"/api/courses/{cid}/run").json()["progress"]["chapters"] for s in c["sections"]]
    repair, judge = model.handlers["repair_block"], model.handlers["judge_grounding"]
    model.handlers["repair_block"] = lambda prompt, files: (seen.append(states()), repair(prompt, files))[1]
    model.handlers["judge_grounding"] = lambda prompt, files: (seen.append(states()), judge(prompt, files))[1]
    plan = model.handlers["propose_outline"]
    model.handlers["propose_outline"] = lambda prompt, files: {"chapters": plan(prompt, files)["chapters"][:1]}
    bad = one_block("key_formula", {"name": "f", "latex": "\\frac{1}{"}, "from_source", [{"source": "cours.pdf", "page": 1}])
    model.handlers["write_section"] = lambda prompt, files: {"blocks": bad + one_block(
        "callout", {"tone": "tip", "text": "ok"}, "from_source", [{"source": "cours.pdf", "page": 1}])}
    cid = to_outline_gate(client, material, model)
    client.post(f"/api/courses/{cid}/gates/outline")
    assert ["repairing"] in seen and ["judging"] in seen
    assert states() == ["flagged"]


def test_a_placeholder_section_is_written_again(client, material, model, monkeypatch):
    from course_factory import chapters as chm
    monkeypatch.setattr(chm, "MIN_SECTION_WORDS", 25)
    real = model.handlers["write_section"]
    seen = []
    def stub_first(prompt, files):
        seen.append(prompt)
        if len(seen) == 1:
            return {"blocks": [{"component": "prose", "data": {"markdown": "test"}, "origin": "model_added"}]}
        out = real(prompt, files)
        out["blocks"] += one_block("prose", {"markdown": "Un ensemble est convexe quand le segment entre deux de ses points reste dedans, ce qui garantit l'unicité du minimum."})
        return out
    model.handlers["write_section"] = stub_first
    generate(client, material, model)
    assert sum("RETRY FEEDBACK" in p and "is a placeholder" in p for p in seen) == 1  # only the stub is written again, told why


@pytest.mark.parametrize("language,rule", [("en", "Write everything in English"), ("fr", "Write everything in French"),
                                           (None, "Write your own explanations, intuitions and hints in English")])
def test_the_course_language_chosen_before_generation_reaches_every_prompt(client, material, model, language, rule):
    cid = generate(client, material, model, goal={"goal": "deep"} | ({"language": language} if language else {}))
    prompts = [p for step, p in model.prompts if step in ("plan_chapter", "write_section")]
    assert prompts and all(rule in p for p in prompts)
    assert client.patch(f"/api/courses/{cid}", json={"goal": "deep", "language": "fr"}).json()["language"] == "fr"
    assert client.patch(f"/api/courses/{cid}", json={"goal": "deep"}).json()["language"] == "fr"  # a goal change keeps it


CRUD = [{"component": "terminal", "origin": "model_added", "data": {"title": "CRUD", "shell": "http", "entries": [
            {"command": f"{m} /boutique/_doc/1", "output": "{}", "note": ""} for m in ("PUT", "GET", "DELETE")]}},
        {"component": "quiz", "origin": "model_added", "data": {"questions": [
            {"prompt": "Quel verbe supprime ?", "options": ["DELETE", "GET"], "correct": [0], "explanation": "DELETE supprime."}]}}]


def test_merging_a_section_keeps_each_distinct_block_once(client, material, model):
    cid = generate(client, material, model, blocks=CRUD)
    ch = chapters(client, cid)["Méthodes de descente"]
    first, second = client.get(f"/api/courses/{cid}/chapters/{ch['id']}").json()["sections"]
    assert second["overlaps"][0]["id"] == first["id"]  # the fake writes the same Blocks in both
    kept = client.post(f"/api/courses/{cid}/sections/{second['id']}/merge", json={"into": first["id"]}).json()
    [merged] = kept["sections"]
    assert merged["id"] == first["id"] and len(merged["blocks"]) == len(first["blocks"]) and not merged["overlaps"]
    assert client.post(f"/api/courses/{cid}/sections/{first['id']}/merge", json={"into": first["id"]}).status_code == 422
