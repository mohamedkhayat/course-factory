"""The Derivation Component (#30): the course's derivation line by line, gap notes the only model text in it."""
from course_factory.learner import card_faces

from test_chapters import chapters, generate, one_block
from test_exams import with_exam  # noqa: F401  # a fixture

LINES = [{"math": "$$J(x_{k+1}) = J(x_k - \\rho \\nabla J(x_k))$$"},
         {"math": "$$\\le J(x_k) - \\rho \\|\\nabla J(x_k)\\|^2 + \\frac{L\\rho^2}{2}\\|\\nabla J(x_k)\\|^2$$",
          "note": "On applique l'inégalité de Lipschitz du gradient avec $y = x_{k+1}$."},
         {"math": "$$< J(x_k)$$ pour $0 < \\rho < 2/L$"}]


def derivation(**extra):
    return one_block("derivation", {"title": "Décroissance du gradient à pas fixe", "lines": LINES} | extra,
                     origin="from_source", citations=[{"source": "cours.pdf", "page": 1}])


def blocks_of(client, cid):
    ch = chapters(client, cid)["Convexité"]
    return client.get(f"/api/courses/{cid}/chapters/{ch['id']}").json()["sections"][0]["blocks"]


def test_a_derivation_is_checked_and_its_gap_notes_are_never_judged_as_the_course(client, material, model):
    cid = generate(client, material, model, blocks=derivation())
    b = next(b for b in blocks_of(client, cid) if b["component"] == "derivation")
    assert b["status"] == "ok" and b["origin"] == "from_source" and b["data"]["lines"][1]["note"].startswith("On applique")
    judged = [p for step, p in model.prompts if step == "judge_grounding"]
    assert any("J(x_{k+1})" in p for p in judged) and not any("inégalité de Lipschitz" in p for p in judged)


def test_a_derivation_needs_two_lines_short_gap_notes_and_right_claims(client, material, model):
    long_note = [LINES[0], LINES[1] | {"note": "Un. Deux. Trois."}]
    claim = {"op": "grad", "expr": "x1**2", "vars": ["x1"], "expected": ["x1"]}  # wrong: 2*x1
    cid = generate(client, material, model, blocks=derivation(lines=LINES[:1]) + derivation(lines=long_note) + derivation(claims=[claim]))
    got = [b for b in blocks_of(client, cid) if b["component"] == "derivation"]
    assert [b["status"] for b in got] == ["flagged"] * 3
    assert "lines" in got[0]["flags"][0] and "two sentences" in got[1]["flags"][0] and "sympy" in got[2]["flags"][0]


def test_a_derivation_card_hides_the_line_the_course_skips_to():
    [(_, front, back)] = card_faces({"component": "derivation", "data": {"title": "t", "statement": "", "lines": LINES, "conclusion": ""}})
    assert "J(x_{k+1})" in front and "What comes next?" in front and "\\frac{L\\rho^2}{2}" not in front
    assert "\\frac{L\\rho^2}{2}" in back and "Lipschitz" in back
    [(_, front, back)] = card_faces({"component": "derivation", "data": {"title": "t", "lines": [{"math": "a"}, {"math": "b"}]}})
    assert "a" in front and back == "b"  # no gap note: the last line


# Course-first Section writing (#30 step 4)

def theoretical_outline(model):
    outline = model.handlers["propose_outline"]
    model.handlers["propose_outline"] = lambda prompt, files: outline(prompt, files) | {"kind": "theoretical"}


def written(model, step="write_section", section="Ensembles convexes"):
    return next(p for s, p in model.prompts if s == step and (step != "write_section" or model.section_of(p) == section))


def test_a_theoretical_course_is_planned_and_written_course_first_with_its_past_questions_in_deep_too(client, with_exam, model):
    theoretical_outline(model)
    generate(client, with_exam, model, goal={"goal": "deep"})
    prompt = written(model)
    assert "Course-first" in prompt and "derivation Block" in prompt and "Nothing that neither the pages" in prompt
    assert "Montrer que $f$ est convexe" in prompt.split("Past Questions on this Chapter:")[1]  # Deep has no Cram brief: given here
    assert "Course-first" in written(model, "plan_chapter") and "component derivation" in written(model, "plan_chapter")
    assert '"source"' in written(model, "plan_chapter") and "overrides \"give every practice Block its own case\"" in prompt
    assert "never a model-made worked_example in its place" in written(model, "plan_chapter")  # lecture notes: the course's derivations


def test_a_planned_practice_items_course_source_reaches_the_writer(client, material, model):
    theoretical_outline(model)
    plan = model.handlers["plan_chapter"]
    model.handlers["plan_chapter"] = lambda prompt, files: (p := plan(prompt, files)) | {"sections": [
        s | {"practice": [x | {"source": "TD1.pdf p.1, Exercice 1"} for x in s["practice"]]} for s in p["sections"]]}
    generate(client, material, model)
    assert "TD1.pdf p.1, Exercice 1" in written(model)


def test_a_mixed_course_is_written_as_before(client, material, model):
    generate(client, material, model)
    assert "Course-first" not in written(model) and "Course-first" not in written(model, "plan_chapter")


def test_a_derivation_stands_for_a_planned_worked_example():
    from course_factory.lesson_plan import plan_gaps
    lesson = {"practice": [{"objective": "o1", "kind": "worked", "component": "worked_example"}], "visual": {"relation": "none"}}
    assert plan_gaps(lesson, [{"component": "derivation"}]) == []
    assert plan_gaps(lesson, [{"component": "quiz"}]) != []


def test_a_theoretical_section_mostly_of_model_text_is_flagged_on_review_and_counted(client, material, model):
    theoretical_outline(model)
    section = model.handlers["write_section"]
    model.handlers["write_section"] = lambda prompt, files: {"blocks": section(prompt, files)["blocks"] + [
        {"component": "callout", "origin": "model_added", "data": {"tone": "tip", "text": "Astuce."}}]}
    cid = generate(client, material, model)
    review = client.get(f"/api/courses/{cid}/review").json()
    shares = [s for ch in review for s in ch["course_share"]]
    assert shares and "33%" in shares[0]["note"] and all(b["status"] != "flagged" or "course share" not in " ".join(b["flags"])
                                                           for ch in review for b in ch["blocks"])  # flagged on Review, never refused
    low = next(c for c in client.get("/api/failures", params={"course": cid}).json() if c["class"] == "low-course-share")
    assert low["count"] == len(shares)


def test_a_theoretical_section_from_the_course_is_not_flagged(client, material, model):
    theoretical_outline(model)
    cid = generate(client, material, model)
    assert [s for ch in client.get(f"/api/courses/{cid}/review").json() for s in ch["course_share"]] == []


def test_the_gaps_found_when_writing_reach_the_failure_report(client, material, model):
    plan = model.handlers["plan_chapter"]  # the plan wants a worked example the fake writer never writes
    model.handlers["plan_chapter"] = lambda prompt, files: (p := plan(prompt, files)) | {"sections": [
        s | {"practice": s["practice"] + [{"objective": s["objectives"][0]["id"], "kind": "worked", "component": "worked_example"}]}
        for s in p["sections"]]}
    cid = generate(client, material, model)
    examples = [e for c in client.get("/api/failures", params={"course": cid}).json() for e in c["examples"]]
    assert any(e.startswith("plan: the plan has 1 worked_example") for e in examples)
