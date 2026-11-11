import json

from course_factory.failures import failure_class
from test_chapters import chapters, generate, one_block

PAGE = [{"source": "cours.pdf", "page": 1}]


def errors_in(prompt):
    return prompt.split("ERRORS:", 1)[1].split("BLOCK:", 1)[0]


def chapter_blocks(client, cid, title="Convexité"):
    ch = chapters(client, cid)[title]
    return ch["id"], [b for s in client.get(f"/api/courses/{cid}/chapters/{ch['id']}").json()["sections"] for b in s["blocks"]]


def test_auto_resolve_repairs_with_the_flag_as_note_keeps_an_undo_and_queues_the_rest(client, material, model):
    blocks = (one_block("key_formula", {"name": "a", "latex": "\\frac{1}{", "meaning": "m"})
              + one_block("key_formula", {"name": "b", "latex": "\\sqrt{", "meaning": "m"}))
    cid = generate(client, material, model, blocks=blocks)  # the fake repair fixes nothing: both stay flagged
    chid, (a, b, *_) = chapter_blocks(client, cid)
    assert a["status"] == b["status"] == "flagged"

    notes = []
    def repair(prompt, files):
        notes.append(errors_in(prompt))
        block = json.loads(prompt.split("BLOCK:", 1)[1])
        if "\\frac{1}{" in errors_in(prompt):  # the flag (KaTeX's message quotes the formula) tells it what is wrong
            block["data"]["latex"] = "\\frac{1}{2}"
        return {"block": block}
    model.handlers["repair_block"] = repair
    out = client.post(f"/api/courses/{cid}/chapters/{chid}/auto-resolve").json()
    assert a["id"] in out["resolved"] and b["id"] in out["queued"], (out, notes)
    assert any("owner note:" in n and "KaTeX" in n for n in notes)

    _, (a2, b2, *_) = chapter_blocks(client, cid)
    assert a2["status"] == "ok" and a2["data"]["latex"] == "\\frac{1}{2}" and a2["previous"]["data"]["latex"] == "\\frac{1}{"
    assert not a2["review_queue"] and b2["review_queue"]
    queue = client.get("/api/review-blocks").json()
    assert [q["id"] for q in queue if q["course_id"] == cid] == [b["id"]]
    assert queue[0]["classes"] == ["katex-parse"] and queue[0]["pages"] is not None

    undone = client.post(f"/api/courses/{cid}/blocks/{a['id']}/undo").json()
    assert undone["data"]["latex"] == "\\frac{1}{" and undone["status"] == "flagged" and undone["previous"] is None
    assert client.post(f"/api/courses/{cid}/blocks/{a['id']}/undo").status_code == 409

    # a reviewer's fix (Claude Code through the API) takes the Block off the queue
    assert client.put(f"/api/courses/{cid}/blocks/{b['id']}", json={"data": {"name": "b", "latex": "\\sqrt{2}", "meaning": "m"}}).status_code == 200
    assert not [q for q in client.get("/api/review-blocks").json() if q["course_id"] == cid]

    report = {r["class"]: r for r in client.get("/api/failures", params={"course": cid}).json()}
    assert report["katex-parse"]["count"] >= 2 and report["katex-parse"]["sources"].get("auto_resolved") == 2
    assert report["katex-parse"]["examples"] and report["katex-parse"]["handler"] == "none"


def test_a_source_error_keeps_the_block_and_adds_a_note(client, material, model):
    verdict = {"contradicts": True, "source_error": False}
    model.handlers["judge_grounding"] = lambda prompt, files: {"results": [
        {"block": 0, "grounded": False, "reason": "la correction écrit 3 au lieu de 2", **verdict}]}
    blocks = one_block("callout", {"tone": "tip", "text": "La dérivée vaut 2."}, "from_source", PAGE)
    cid = generate(client, material, model, blocks=blocks)
    chid, (b, *_) = chapter_blocks(client, cid)
    assert b["status"] == "flagged" and "contradicts its cited pages" in b["flags"][0]

    verdict.update(contradicts=False, source_error=True)
    assert b["id"] in client.post(f"/api/courses/{cid}/chapters/{chid}/auto-resolve").json()["resolved"]
    _, (b, *_) = chapter_blocks(client, cid)
    assert b["status"] == "ok" and b["data"]["text"] == "La dérivée vaut 2."
    assert b["flags"] == ["source error: la correction écrit 3 au lieu de 2"]


def test_auto_resolve_can_run_as_soon_as_a_chapter_is_written(client, material, model):
    from test_outline import to_outline_gate
    cid = to_outline_gate(client, material, model)
    assert client.put(f"/api/courses/{cid}/auto-resolve", json={"on": True}).json()["auto_resolve"] == 1
    model.handlers["write_section"] = lambda prompt, files: {"blocks": one_block("key_formula", {"name": "a", "latex": "\\frac{1}{", "meaning": "m"})}
    calls = []
    def repair(prompt, files):
        block = json.loads(prompt.split("BLOCK:", 1)[1])
        calls.append("owner note:" in errors_in(prompt))
        return {"block": block}
    model.handlers["repair_block"] = repair
    client.post(f"/api/courses/{cid}/gates/outline")
    assert any(calls)  # the auto-resolve pass ran after the normal repair rounds
    assert any(t["owner_action"] == "auto_resolved" for t in client.get(f"/api/courses/{cid}/traces").json())


def test_check_messages_map_to_failure_classes():
    cases = {
        "claims.3.op: Input should be 'equal', 'diff', 'grad' or 'hessian'": "schema:claims.op:enum",
        "claims.0.expected.list[list[str]]: Input should be a valid list": "schema:claims.expected.list:type",
        "questions.1.correct: Input should be a valid list": "schema:questions.correct:type",
        "steps.2.highlight: Field required": "schema:steps.highlight:missing",
        "KaTeX parse error: Undefined control sequence: \\mu at position 4": "katex-parse",
        "Element is not defined": "render-dom-global",
        "Parse error on line 2: ...": "mermaid-render",
        "edges use node ids that are not in nodes: C": "diagram-ids",
        "text writes a formula as code near 'sqrt(n)': write it as LaTeX inside $…$": "ascii-math",
        "sympy: equal of 2 + 2 is 4, not 5": "sympy-wrong",
        "sympy could not check claim {'op': 'grad'}": "sympy-unparsable",
        "contradicts its cited pages: wrong sign": "contradicts-pages",
        "grounding: adds an example": "beyond-pages",
        "grounding judge failed: judge_grounding: Expecting value": "judge-failed",
        "citation to cours.pdf page 9 does not exist": "citation-missing-page",
        "question 1: single-choice must have exactly one correct option": "quiz-answers",
        "repair_block: Extra data: line 1 column 5 (char 4)": "bad-json",
        "the Section is a placeholder (under 120 words): write its real content": "placeholder-section",
        "source error: typo": "source-error",
        "something new": "unclassified",
    }
    assert {m: failure_class(m) for m in cases} == cases
