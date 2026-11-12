"""#23: one Chapter plan before the Sections are written (objectives, misconceptions, a practice ramp, the visual), held to
the rules in docs/research/learning-design.md; quiz item-writing and diagram readability checks."""

import json

import pytest

from course_factory.checks import block_warnings, check_blocks
from course_factory.failures import failure_class
from course_factory.lesson_plan import LessonPlan, order_gaps, plan_errors, plan_gaps
from test_chapters import EXERCICES, GRADIENT, chapters, generate, sections_written

SECTIONS = [{"title": "Pas fixe", "teaches": ["pas fixe"]}, {"title": "Pas optimal", "teaches": ["pas optimal"]}]


def lesson(title, objectives, practice, misconceptions=(), visual=None):
    return {"title": title, "objectives": objectives, "practice": practice, "misconceptions": list(misconceptions),
            **({"visual": visual} if visual else {})}


def obj(level, concepts=(), exam_types=(), id="o1"):
    return {"id": id, "level": level, "text": "…", "concepts": list(concepts), "exam_types": list(exam_types)}


def item(kind, component, objective="o1"):
    return {"objective": objective, "kind": kind, "component": component}


GOOD = [lesson("Pas fixe", [obj("understand", ["pas fixe"], id="o0"), obj("apply", ["gradient", "pas fixe"], ["Type descente"])],
               [item("retrieval", "fill_blanks", "o0"), item("worked", "worked_example"), item("faded", "fill_blanks"),
                item("exam", "exercise")],
               visual={"relation": "quantity", "shows": "the iterates", "component": "iteration_table"}),
        lesson("Pas optimal", [obj("remember", ["pas optimal"])], [item("retrieval", "quiz")], [{"id": "m1", "text": "…"}])]


def errors(sections, exam_types=("Type descente",)):
    overview = "Le pas fixe d'abord, la méthode la plus simple qui converge, puis le pas optimal qui choisit le meilleur pas à chaque itération."
    return plan_errors(LessonPlan.model_validate({"overview": overview, "sections": sections}), SECTIONS, ["gradient"], list(exam_types))


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
    (lambda p: [p[0] | {"objectives": [obj("understand", ["pas fixe"], id="o0"), obj("apply", ["pas fixe"])]}, p[1]],
     "Question Types ['Type descente']"),
    # the real plan of course 6, Chapter 22 "Fonctions convexes": objectives remember, apply, understand
    (lambda p: [p[0] | {"objectives": p[0]["objectives"][::-1]}, p[1]], "lowest level to the highest"),
    # 25/4 opened at analyse; a Chapter opening at apply has nothing to orient the learner
    (lambda p: [p[0] | {"objectives": [p[0]["objectives"][1]], "practice": p[0]["practice"][1:]}, p[1]], "opens the Chapter"),
    (lambda p: [p[0] | {"practice": p[0]["practice"][1:] + p[0]["practice"][:1]}, p[1]], "practise the objectives in their order"),
    (lambda p: [p[0], p[1] | {"objectives": [obj("apply", ["pas optimal"])], "practice": [item("exam", "exercise"), item("worked", "worked_example")]}],
     "the first practice is exam"),
    # the stored plan of Chapter 23, "Algorithme du gradient", has 5 drills for 2 objectives
    (lambda p: [p[0] | {"practice": p[0]["practice"] + [item("exam", "exercise")]}, p[1]], "its objectives need 2"),
    # one retrieval item covers every remember/understand objective, and explain_back is one
    (lambda p: [p[0], p[1] | {"objectives": [obj("remember", id="o1"), obj("understand", id="o2")],
                              "practice": [item("retrieval", "explain_back", "o2")]}], None),
])
def test_a_plan_is_held_to_the_learning_design_rules(change, expected):
    found = errors(change(json.loads(json.dumps(GOOD))))
    assert (found == []) if expected is None else any(expected in e for e in found), found


def test_plan_gaps_name_the_missing_practice_and_visual():
    blocks = [{"component": "worked_example"}, {"component": "exercise"}]
    gaps = plan_gaps(GOOD[0] | {"visual": GOOD[0]["visual"]}, blocks)
    assert len(gaps) == 2 and "fill_blanks" in gaps[0] and "iteration_table" in gaps[1]
    assert plan_gaps(GOOD[0], blocks + [{"component": "fill_blanks"}] * 2 + [{"component": "iteration_table"}]) == []


# Course 2, "Vecteurs gaussiens : définition et fonction caractéristique": opened on a definition, cold.
GAUSS_OPENING = [{"component": "theorem_box", "data": {"kind": "definition", "title": "Définition du vecteur gaussien",
                                                       "statement": "On dit qu'un vecteur aléatoire $X$ est un vecteur gaussien si..."}},
                 {"component": "key_formula", "data": {"name": "Fonction caractéristique", "latex": "\\Phi_X(u)"}}]
# Course 6, "Application : régression linéaire par moindres carrés": the worked example says "minimiseur exact" for the Concept.
NORMAL = "résolution exacte du minimum (X* = N⁻¹C)"
SOLVE = {"component": "exercise", "tests": [NORMAL], "data": {"title": "Exercice — résoudre le système normal", "statement": "..."}}
WORKED = {"component": "worked_example", "data": {"title": "Système normal et minimum exact",
                                                  "problem": "Déterminer le minimiseur exact $X^*$ du problème."}}
OPENING = {"component": "prose", "data": {"markdown": "C'est la mise en application de tout le chapitre."}}


def test_order_gaps_flag_a_cold_opening_and_a_concept_asked_before_it_is_explained():
    assert "opens with a theorem_box" in order_gaps(GAUSS_OPENING, [])[0]
    definition = GAUSS_OPENING[0]
    assert "Block 2 (theorem_box) states the formal version" in order_gaps([OPENING, definition], [])[0]
    assert order_gaps([OPENING, WORKED, definition], []) == []  # a case first, then the definition
    worked_case = {"component": "prose", "data": {"markdown": "Prenons deux gaussiennes $X_1$, $X_2$ : leur couple l'est-il ?"}}
    assert order_gaps([worked_case, definition], []) == []
    assert order_gaps([OPENING, WORKED, SOLVE], [NORMAL]) == []  # "minimiseur exact" explains it: stems, not exact words
    gaps = order_gaps([OPENING, SOLVE, WORKED], [NORMAL])
    assert gaps == [f'Block 2 (exercise) tests "{NORMAL}" before any Block explains it']
    assert order_gaps([OPENING], [NORMAL]) == [f'no Block explains "{NORMAL}", which this Section teaches']
    intuition = {"component": "intuition", "data": {"idea": "Une combinaison de gaussiennes reste gaussienne."}}
    assert order_gaps([OPENING, intuition, definition], []) == []  # an intuition is the concrete case before the definition


def test_a_section_mostly_practice_gets_an_order_warning_and_a_recap_counts_as_neither():
    quiz = {"component": "quiz", "data": {"question": "Le pas fixe converge-t-il toujours vers le minimum ?"}}
    recap = {"component": "recap", "data": {"takeaways": ["un", "deux"]}}
    assert any("practice outweighs explanation (2 of 3 Blocks" in g for g in order_gaps([OPENING, quiz, quiz], []))
    assert order_gaps([OPENING, WORKED, quiz, recap], []) == []
    short = {"component": "prose", "data": {"markdown": "Court."}}
    assert any("practice words" in g for g in order_gaps([short, short, quiz], []))  # 1 Block in 3, but fewer teaching words


def test_one_plan_per_chapter_reaches_the_writer_and_the_reader(client, material, model):
    cid = generate(client, material, model)
    plans = [p for step, p in model.prompts if step == "plan_chapter"]
    assert len(plans) == 2 and all("SECTIONS:" in p for p in plans)
    writes = [p for step, p in model.prompts if step == "write_section"]
    assert len(writes) == 3 and all('"State it."' in p and "Confuses it with its converse." in p for p in writes)
    ch = chapters(client, cid)["Méthodes de descente"]
    secs = client.get(f"/api/courses/{cid}/chapters/{ch['id']}").json()["sections"]
    assert [s["objectives"] for s in secs] == [["State it."], ["State it."]]
    chapter = client.get(f"/api/courses/{cid}/chapters/{ch['id']}").json()
    assert chapter["overview"].endswith("Gradient, puis Exercices.")  # the map at the top of the Chapter
    assert all('"overview": "Ce chapitre' in p for p in writes)  # and the writer of each Section sees it


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
    assert sum("order: the Section opens with a theorem_box" in p for p in writes) == 3


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


# The real course-5 definition that packed three terms into one paragraph, and its one-term rewrite.
CRAMMED = ("**PrimaryShard:** the index is split into 5 (default value) primary shards; it is *not* possible to change the number of "
           "partitions after its creation. **SecondaryShard (replica):** these are replicated partitions; an index can have zero to many "
           "per primary shard. **Node:** each node is an Elasticsearch instance; a master node is chosen and is replaced by another node "
           "in case of failure. *Why it matters:* replicas spread the read load across nodes.")
NODE = ("A **node** is one Elasticsearch instance (one running server). The nodes together form the **cluster**. One node is chosen "
        "as **master**; if it fails, another node replaces it.\n\n*Why it matters:* a node holds **many shards**, not one.")


def test_a_definition_of_three_terms_at_once_is_a_warning():
    box = lambda s: {"component": "theorem_box", "data": {"kind": "definition", "title": "T", "statement": s}}
    [w] = block_warnings(box(CRAMMED))
    assert failure_class(w) == "definition-cram" and "PrimaryShard, SecondaryShard (replica), Node" in w
    assert block_warnings(box(NODE)) == []


# The slide on p.7 of the course-5 Elasticsearch deck, transcribed by hand: four nodes, each holding several shards.
ES_FIGURE = {"kind": "architecture", "entities": ["Document à indexer", "Node 1 (Master)", "Node 2", "Node 3", "Node 4",
                                                  "a0", "a1", "b0", "b1", "b2", "b3", "b4"],
             "contains": [["Node 1 (Master)", "a0"], ["Node 1 (Master)", "b2"], ["Node 1 (Master)", "b1"], ["Node 2", "a1"],
                          ["Node 2", "b3"], ["Node 2", "b0"], ["Node 2", "b2"], ["Node 3", "b0"], ["Node 3", "b4"], ["Node 3", "a0"],
                          ["Node 3", "b3"], ["Node 4", "b1"], ["Node 4", "a1"], ["Node 4", "b4"]],
             "relations": [["Document à indexer", "Node 1 (Master)", "Route"], ["Node 2", "Node 3", "Réplication"]]}
ES_PAGE = {"source": "Ch6-elasticsearch_en.pdf", "page": 7, "text": "", "figures": [ES_FIGURE]}
# The real course-5 routing diagram: the cluster flattened to a chain of nodes, no shard inside any of them.
ES_FLAT = ('flowchart TD\n  doc["Document à indexer"]\n  master["Node 1 (Master) — Elasticsearch instance"]\n'
           '  n2["Node 2 — Elasticsearch instance"]\n  n3["Node 3 — Elasticsearch instance"]\n  n4["Node 4 — Elasticsearch instance"]\n'
           '  doc -->|"Route"| master\n  master -->|"shard primaire"| n2\n  n2 -->|"réplication"| n3\n  n3 -->|"réplication"| n4')
# Its hand fix: a subgraph per node, holding its shards.
ES_NODES = ('flowchart LR\n  doc["Document à indexer"]\n  subgraph N1["Node 1 (Master)"]\n    a0p["a0 primaire"]\n    b1r["b1 réplique"]\n  end\n'
            '  subgraph N2["Node 2"]\n    b3p["b3 primaire"]\n    a1p["a1 primaire"]\n  end\n  subgraph N3["Node 3"]\n    b3r["b3 réplique"]\n'
            '    a0r["a0 réplique"]\n  end\n  subgraph N4["Node 4"]\n    a1r["a1 réplique"]\n  end\n'
            '  doc -->|"via le master"| N1\n  N1 -->|"route"| b3p\n  b3p -->|"réplication"| b3r')


def test_a_diagram_that_drops_its_slides_shards_and_nodes_containment_is_a_warning():
    diagram = lambda src: {"component": "diagram", "data": {"mermaid": src}, "citations": [{"source": ES_PAGE["source"], "page": 7}]}
    [flat] = block_warnings(diagram(ES_FLAT), [ES_PAGE])
    assert failure_class(flat) == "figure-fidelity" and "a0" in flat and "subgraph" in flat
    assert block_warnings(diagram(ES_NODES), [ES_PAGE]) == []
    assert block_warnings(diagram(ES_FLAT), [{**ES_PAGE, "figures": []}]) == []  # pages read before figures: nothing to compare
    big = ES_NODES + "".join(f'\n  N4 --> x{i}["x{i}"]' for i in range(8))  # a faithful redraw may be big
    assert block_warnings(diagram(big), [ES_PAGE]) == []


def test_a_figure_read_from_a_page_reaches_the_prompt_of_the_section_citing_it(client, material, model):
    model.handlers["read_page"] = lambda prompt, files: {"text": f"page text of {files[0].name}", "readable": True, "figures": [ES_FIGURE]}
    generate(client, material, model)
    prompt = next(p for step, p in model.prompts if step == "write_section")
    assert '"figures"' in prompt and "Node 1 (Master)" in prompt


def test_a_section_whose_pages_carry_a_figure_must_show_it_before_drawing_its_own():
    """Advanced BD, Ch4 p.6: the slide's window diagram was only redrawn. A logo is not a figure to show."""
    from course_factory.lesson_plan import figure_gaps
    pages = [{"source": "Ch4.pdf", "page": 1, "text": "[figure: logo ESPRIT]"},
             {"source": "Ch4.pdf", "page": 6, "text": "Windows\n[figure: two timelines, original DStream and windowed DStream]"}]
    (gap,) = figure_gaps(pages, [{"component": "diagram"}])
    assert "1 figure" in gap and "Ch4.pdf p.6" in gap
    assert figure_gaps(pages, [{"component": "figure"}, {"component": "diagram"}]) == [] and figure_gaps(pages[:1], []) == []
