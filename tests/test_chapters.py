import json

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
    return client.get(f"/api/courses/{cid}/chapters/{ch['id']}").json()["sections"][0]["blocks"][0]


def one_block(component, data, origin="model_added", citations=()):
    return [{"component": component, "data": data, "origin": origin, "citations": list(citations)}]


def test_cram_generates_by_priority_then_exam_weight_and_skips_skip(client, material, model):
    cid = generate(client, material, model, priorities={"Méthodes de descente": "focus"})
    assert sections_written(model) == [GRADIENT, EXERCICES, CONVEXES]
    model.prompts.clear()
    cid = generate(client, material, model)  # equal Priority: Exam Weight 0.75 beats 0.25
    assert sections_written(model) == [CONVEXES, GRADIENT, EXERCICES]
    model.prompts.clear()
    cid = generate(client, material, model, priorities={"Convexité": "skip"})
    assert sections_written(model) == [GRADIENT, EXERCICES]
    assert chapters(client, cid)["Convexité"]["status"] == "planned"
    assert client.get(f"/api/courses/{cid}/run").json()["status"] == "done"


def test_deep_generates_in_course_order(client, material, model):
    generate(client, material, model, goal={"goal": "deep"}, priorities={"Méthodes de descente": "focus"})
    assert sections_written(model) == [CONVEXES, GRADIENT, EXERCICES]


def test_section_prompt_has_cited_page_text_and_catalogue(client, material, model):
    generate(client, material, model)
    prompt = next(p for step, p in model.prompts if step == "write_section")
    assert "page text of" in prompt and "iteration_table" in prompt and "language of the source pages" in prompt


def test_chapters_wait_for_review_and_publishing_makes_them_readable(client, material, model):
    cid = generate(client, material, model)
    assert {c["status"] for c in chapters(client, cid).values()} == {"in_review"}
    assert client.get(f"/api/courses/{cid}/reader").json() == []
    review = client.get(f"/api/courses/{cid}/review").json()
    assert [c["title"] for c in review] == ["Convexité", "Méthodes de descente"]
    assert len(review[1]["blocks"]) == 4 and review[1]["blocks"][0]["section"] == GRADIENT
    chid = review[0]["id"]
    assert client.post(f"/api/courses/{cid}/chapters/{chid}/publish").status_code == 200
    assert client.post(f"/api/courses/{cid}/chapters/{chid}/publish").status_code == 409
    readable = client.get(f"/api/courses/{cid}/reader").json()
    assert [c["title"] for c in readable] == ["Convexité"]
    block = readable[0]["sections"][0]["blocks"][0]
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


def test_block_is_flagged_and_kept_after_three_failed_repairs(client, material, model):
    cid = generate(client, material, model, blocks=one_block("quiz", {"questions": [
        {"prompt": "?", "options": ["a", "A "], "correct": [0, 1], "explanation": ""}]}))
    b = first_block(client, cid)
    assert b["status"] == "flagged"
    assert any("not distinct" in f for f in b["flags"]) and any("exactly one" in f for f in b["flags"])
    assert any("explanation" in f for f in b["flags"])
    repairs = [p for step, p in model.prompts if step == "repair_block"]
    assert len(repairs) == 3 * 3  # three Sections, three repairs each
    review = client.get(f"/api/courses/{cid}/review").json()
    assert review[0]["blocks"][0]["status"] == "flagged"


def test_flagged_blocks_come_first_in_review(client, material, model):
    blocks = one_block("prose", {"markdown": "fine"}) + one_block("callout", {"tone": "loud", "text": "x"})
    cid = generate(client, material, model, blocks=blocks)
    review = client.get(f"/api/courses/{cid}/review").json()
    assert [b["component"] for b in review[0]["blocks"]] == ["callout", "prose"]


def test_math_and_diagram_errors_are_caught(client, material, model):
    blocks = (one_block("prose", {"markdown": r"Bien: $\frac{1}{2}$ mais $\frac{1}{$"})
              + one_block("diagram", {"mermaid": "graph TD\n  A-->B"})
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


def test_grounding_judge_warns_without_flagging(client, material, model):
    model.handlers["judge_grounding"] = lambda prompt, files: {"grounded": False, "reason": "the bound is not in the notes"}
    cid = generate(client, material, model)
    b = first_block(client, cid)
    assert b["status"] == "ok" and b["flags"] == ["grounding: the bound is not in the notes"]
    judged = [p for step, p in model.prompts if step == "judge_grounding"]
    assert len(judged) == 3  # only the From source Blocks, one per Section


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
    assert client.get(f"/api/courses/{cid}/run").json()["status"] == "done"
