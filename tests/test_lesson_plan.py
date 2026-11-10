"""#23: one Chapter plan before the Sections are written (objectives, misconceptions, a practice ramp, the visual), held to
the rules in docs/research/learning-design.md; quiz item-writing and diagram readability checks."""

import json

import pytest

from course_factory.checks import block_warnings, check_blocks
from course_factory.failures import failure_class
from course_factory.lesson_plan import LessonPlan, plan_errors, plan_gaps
from test_chapters import EXERCICES, GRADIENT, chapters, generate, sections_written

SECTIONS = [{"title": "Pas fixe", "teaches": ["pas fixe"]}, {"title": "Pas optimal", "teaches": ["pas optimal"]}]


def lesson(title, objectives, practice, misconceptions=(), visual=None):
    return {"title": title, "objectives": objectives, "practice": practice, "misconceptions": list(misconceptions),
            **({"visual": visual} if visual else {})}


def obj(level, concepts=(), exam_types=(), id="o1"):
    return {"id": id, "level": level, "text": "…", "concepts": list(concepts), "exam_types": list(exam_types)}


def item(kind, component, objective="o1"):
    return {"objective": objective, "kind": kind, "component": component}


GOOD = [lesson("Pas fixe", [obj("apply", ["gradient", "pas fixe"], ["Type descente"])],
               [item("worked", "worked_example"), item("faded", "fill_blanks"), item("exam", "exercise")],
               visual={"relation": "quantity", "shows": "the iterates", "component": "iteration_table"}),
        lesson("Pas optimal", [obj("remember", ["pas optimal"])], [item("retrieval", "quiz")], [{"id": "m1", "text": "…"}])]


def errors(sections, exam_types=("Type descente",)):
    return plan_errors(LessonPlan.model_validate({"sections": sections}), SECTIONS, ["gradient"], list(exam_types))


@pytest.mark.parametrize("change,expected", [
    (lambda p: p, None),
    (lambda p: p[::-1], "exact titles"),
    (lambda p: [p[0] | {"practice": [item("exam", "exercise")]}, p[1]], "a worked example, then"),
    (lambda p: [p[0] | {"practice": [item("exam", "exercise"), item("worked", "worked_example")]}, p[1]], "in that order"),
    (lambda p: [p[0] | {"objectives": [obj("apply", ["pas optimal"], ["Type descente"])]}, p[1]], "no Section up to this one teaches"),
    (lambda p: [p[0], p[1] | {"misconceptions": []}], "misconceptions"),
    (lambda p: [p[0], p[1] | {"practice": [item("retrieval", "exercise")]}], "retrieval practice must be one of"),
    (lambda p: [p[0], p[1] | {"objectives": [obj("understand")], "practice": [item("worked", "worked_example")]}], "retrieval item"),
    (lambda p: [p[0] | {"visual": {"relation": "fan_out", "shows": "replicas", "component": "table"}}, p[1]], "fan_out is drawn"),
    (lambda p: [p[0] | {"objectives": [obj("apply", ["pas fixe"])]}, p[1]], "Question Types ['Type descente']"),
])
def test_a_plan_is_held_to_the_learning_design_rules(change, expected):
    found = errors(change(json.loads(json.dumps(GOOD))))
    assert (found == []) if expected is None else any(expected in e for e in found), found


def test_plan_gaps_name_the_missing_practice_and_visual():
    blocks = [{"component": "worked_example"}, {"component": "exercise"}]
    gaps = plan_gaps(GOOD[0] | {"visual": GOOD[0]["visual"]}, blocks)
    assert len(gaps) == 2 and "fill_blanks" in gaps[0] and "iteration_table" in gaps[1]
    assert plan_gaps(GOOD[0], blocks + [{"component": "fill_blanks"}, {"component": "iteration_table"}]) == []


def test_one_plan_per_chapter_reaches_the_writer_and_the_reader(client, material, model):
    cid = generate(client, material, model)
    plans = [p for step, p in model.prompts if step == "plan_chapter"]
    assert len(plans) == 2 and all("SECTIONS:" in p for p in plans)
    writes = [p for step, p in model.prompts if step == "write_section"]
    assert len(writes) == 3 and all('"State it."' in p and "Confuses it with its converse." in p for p in writes)
    ch = chapters(client, cid)["Méthodes de descente"]
    secs = client.get(f"/api/courses/{cid}/chapters/{ch['id']}").json()["sections"]
    assert [s["objectives"] for s in secs] == [["State it."], ["State it."]]


def test_an_invalid_plan_is_sent_back_once_and_never_stalls_the_run(client, material, model):
    def bad(prompt, files):  # an apply objective with no worked example, every time
        titles = [s["title"] for s in json.loads(prompt.split("SECTIONS:", 1)[1].split("\n", 1)[0])]
        return {"sections": [lesson(t, [obj("apply")], [item("independent", "exercise")]) for t in titles]}
    model.handlers["plan_chapter"] = bad
    cid = generate(client, material, model)
    plans = [p for step, p in model.prompts if step == "plan_chapter"]
    assert len(plans) == 4  # two Chapters, one retry each
    assert "Errors in your previous plan, fix every one: none" in plans[0] and "a worked example, then" in plans[1]
    assert {c["status"] for c in chapters(client, cid).values()} == {"in_review"}
    traces = client.get(f"/api/courses/{cid}/traces").json()
    assert [failure_class(m) for t in traces if t["step"] == "plan_chapter" and t["checks"]
            for m in json.loads(t["checks"])[0]["errors"]][:1] == ["plan"]


def test_a_section_missing_planned_practice_is_rewritten_once(client, material, model):
    theorem = {"component": "theorem_box", "origin": "model_added",
               "data": {"kind": "definition", "title": "Def", "statement": "Un ensemble est convexe si..."}}
    model.handlers["write_section"] = lambda prompt, files: {"blocks": [theorem]}  # never writes the planned quiz
    generate(client, material, model)
    writes = [p for step, p in model.prompts if step == "write_section"]
    assert len(writes) == 6
    assert sum("the plan has 1 quiz Block(s) for objectives ['o1'], the Section has 0" in p for p in writes) == 3


def test_a_resumed_chapter_reuses_its_plan(client, material, model):
    original, calls = model.handlers["write_section"], {"n": 0}

    def flaky(prompt, files):
        calls["n"] += 1
        if model.section_of(prompt) == GRADIENT and calls["n"] < 5:
            return "not json"
        return original(prompt, files)
    model.handlers["write_section"] = flaky
    cid = generate(client, material, model)
    assert client.get(f"/api/courses/{cid}/run").json()["status"] == "failed"
    model.prompts.clear()
    assert client.post(f"/api/courses/{cid}/run/retry").status_code == 200
    assert sections_written(model) == [GRADIENT, EXERCICES]
    assert not [s for s, _ in model.prompts if s == "plan_chapter"]


# The real course-2 quiz (Gaussian vectors): its last option is a catch-all, not a mistake anyone makes.
GAUSS = {"prompt": "Quel énoncé est correct pour un vecteur gaussien $X = (X_1, X_2)$ ?", "options": [
    "$X_1$ et $X_2$ non corrélées ⟹ indépendantes.", "$X_1$ et $X_2$ non corrélées ⟹ $\\Gamma$ n'est pas diagonale.",
    "$X_1$ et $X_2$ indépendantes ⟹ $\\mathrm{Cov}(X_1,X_2) = 0$, mais $\\Gamma$ peut avoir d'autres termes hors diagonale.",
    "Aucune des réponses n'est correcte."], "correct": [0], "explanation": "Pour un vecteur gaussien, non corrélées ⟺ indépendantes."}


def test_an_all_or_none_of_the_above_option_is_an_error():
    _, (errs,) = check_blocks([{"component": "quiz", "origin": "model_added", "data": {"questions": [GAUSS]}}], {})
    assert [failure_class(e) for e in errs] == ["quiz-cue"]


def test_the_right_option_always_longest_is_a_warning():
    q = {"prompt": "?", "options": ["court", "la réponse juste et longue"], "correct": [1], "explanation": "."}
    quiz = lambda n: {"component": "quiz", "data": {"questions": [q] * n}}
    assert block_warnings(quiz(2)) == [] and failure_class(block_warnings(quiz(3))[0]) == "quiz-cue"


# The real course-3 modularisation diagram: 13 nodes in one view.
MODULES = ('flowchart TD\n    A["Notebook Jupyter fonctionnel"] --> B{"Identifier les blocs logiques"}\n'
           '    B --> C1["Chargement & pretraitement des donnees"]\n    B --> C2["Entrainement du modele"]\n'
           '    B --> C3["Evaluation des performances"]\n    B --> C4["Sauvegarde & chargement du modele"]\n'
           '    C1 --> D1["prepare_data()"]\n    C2 --> D2["train_model()"]\n    C3 --> D3["evaluate_model()"]\n'
           '    C4 --> D4["save_model() / load_model()"]\n    D1 --> E["model_pipeline.py"]\n    D2 --> E\n    D3 --> E\n'
           '    D4 --> E\n    E --> F["main.py (execution via CLI)"]\n    F --> G["Tester chaque fonction individuellement"]')


def test_a_big_diagram_or_a_long_label_is_a_warning():
    [size] = block_warnings({"component": "diagram", "data": {"mermaid": MODULES}})
    assert "13 nodes" in size and failure_class(size) == "diagram-size"
    assert block_warnings({"component": "step_diagram", "data": {"mermaid": MODULES}}) == []  # already walked a stage at a time
    long = 'flowchart LR\n  a["CI : relance les jobs d\'entraînement à chaque changement de code"] --> b["$b \\cdot Y = b \\cdot a + M^t b X$"]'
    [label] = block_warnings({"component": "diagram", "data": {"mermaid": long}})
    assert "CI : relance" in label and "cdot" not in label
