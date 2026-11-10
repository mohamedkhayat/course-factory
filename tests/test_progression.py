"""#22: practice tests only what was taught before it, diagrams that should branch do, and only the learner's cohort's
Past papers weigh the Course."""

import json
import sqlite3

import pytest

from conftest import make_pdf
from course_factory.checks import check_blocks
from course_factory.exams import cohort_of, default_scope
from course_factory.failures import failure_class
from pathlib import Path

from course_factory.progression import MARK, ledger_errors, progression_errors, repeat_errors, section_overlaps
from test_chapters import CONVEXES, GRADIENT, chapters, generate

OUTLINE = {"chapters": [
    {"title": "Convexité", "sections": [
        {"title": CONVEXES, "pages": [{"source": "cours.pdf", "page": 1}], "teaches": ["ensemble convexe"]}]},
    {"title": "Méthodes de descente", "sections": [
        {"title": GRADIENT, "pages": [{"source": "cours.pdf", "page": 2}], "teaches": ["pas fixe", "mise à jour partielle"]},
        {"title": "Exercices", "pages": [{"source": "TD1.pdf", "page": 1}], "teaches": ["pas optimal"]}]}]}

# The real Elasticsearch fill_blanks (course 5): the first Section drilled health, index creation and _update.
ES_DRILL = {"title": "Type the ES/Kibana commands", "language": "http",
            "template": "[[1]] /_cluster/health?pretty\n\nPUT /[[2]]\n{\n  \"settings\" : {\n    \"number_of_shards\" : [[3]],\n"
                        "    \"number_of_replicas\" : [[4]]\n  }\n}\n\nPOST /ventes/_[[5]]/transaction_001\n{\n  \"[[6]]\" : { \"Statut\" : \"annulée\" }\n}",
            "blanks": [{"answers": [a]} for a in ("GET", "ventes", "6", "3", "update", "doc")]}


def section(blocks):
    return lambda prompt, files: {"blocks": blocks(prompt) if callable(blocks) else blocks}


def drill(tests=()):
    return {"component": "fill_blanks", "origin": "model_added", "tests": list(tests), "data": ES_DRILL}


def theorem(text):
    return {"component": "theorem_box", "origin": "model_added", "data": {"kind": "definition", "title": "Def", "statement": text}}


def flags(client, cid, title):
    ch = chapters(client, cid)[title]
    return [(b["component"], b["status"], b["flags"]) for s in client.get(f"/api/courses/{cid}/chapters/{ch['id']}").json()["sections"]
            for b in s["blocks"]]


def test_the_outline_plans_what_each_section_teaches_and_the_writer_knows_what_came_before(client, material, model):
    model.handlers["propose_outline"] = lambda prompt, files: OUTLINE
    cid = generate(client, material, model, goal={"goal": "deep"})
    secs = {s["title"]: s for c in client.get(f"/api/courses/{cid}/outline").json()["chapters"] for s in c["sections"]}
    assert secs["Exercices"]["teaches"] == ["pas optimal"]
    prompt = next(p for step, p in model.prompts if step == "write_section" and f"SECTION: Exercices" in p)
    assert '"ensemble convexe", "pas fixe", "mise à jour partielle"' in prompt and '["pas optimal"]' in prompt


def test_practice_testing_a_concept_a_later_section_teaches_is_flagged(client, material, model):
    model.handlers["propose_outline"] = lambda prompt, files: OUTLINE
    model.handlers["write_section"] = section(lambda p: [theorem("PUT, POST, GET, _update, ventes, doc, 6, 3."), drill(
        ["mise à jour partielle"] if f"SECTION: {CONVEXES}" in p else [])])
    cid = generate(client, material, model, goal={"goal": "deep"})
    (_, _, _), (_, status, msgs) = flags(client, cid, "Convexité")
    assert status == "flagged"
    assert any('"mise à jour partielle"' in m and f'"{GRADIENT}"' in m for m in msgs)
    # tested after it is taught; the fake writes the same drill in each Section, which is only a repeat
    assert [m for _, _, ms in flags(client, cid, "Méthodes de descente") for m in ms if "repeat:" not in m] == []


def test_practice_expecting_an_answer_nothing_taught_or_gave_is_flagged_and_an_edit_clears_it(client, material, model):
    model.handlers["write_section"] = section([drill()])
    cid = generate(client, material, model, goal={"goal": "deep"})
    (_, status, msgs), = flags(client, cid, "Convexité")
    assert status == "flagged" and any('"_update"' in m and "nothing teaches it" in m for m in msgs)
    assert any("number 6" in m for m in msgs)
    ch = chapters(client, cid)["Convexité"]
    bid = client.get(f"/api/courses/{cid}/chapters/{ch['id']}").json()["sections"][0]["blocks"][0]["id"]
    given = ES_DRILL | {"title": "Index `ventes` (6 shards, 3 replicas), then a partial `_update` of a `doc`: health with GET, PUT, POST"}
    assert client.put(f"/api/courses/{cid}/blocks/{bid}", json={"data": given}).status_code == 200
    (_, status, msgs), = flags(client, cid, "Convexité")
    assert (status, msgs) == ("ok", [])


def test_a_drill_previewing_what_a_later_section_is_named_after_is_flagged():
    blocks = [
        {"id": 1, "chapter": 1, "section": "Architecture", "component": "terminal", "data": {"entries": [{"command": "GET /_cluster/health"}]}},
        {"id": 2, "chapter": 1, "section": "Architecture", "component": "fill_blanks",
         "data": {"title": "t", "language": "http", "template": "[[1]] /_cluster/[[2]]", "blanks": [{"answers": ["GET"]}, {"answers": ["health"]}]}},
        {"id": 3, "chapter": 1, "section": "Cluster Health", "component": "theorem_box", "data": {"statement": "health"}},
        {"id": 4, "chapter": 1, "section": "Cluster Health", "component": "fill_blanks",
         "data": {"title": "t", "language": "http", "template": "GET /_cluster/[[1]]", "blanks": [{"answers": ["health"]}]}}]
    errors = progression_errors(blocks)
    assert list(errors) == [2] and '"Cluster Health"' in errors[2][0]
    # The real Docker architecture Section: its table explains what each command does, so its drill is not a preview.
    table = {"id": 0, "chapter": 1, "section": "Architecture", "component": "table",
             "data": {"headers": ["Commande", "Rôle"], "rows": [["GET /_cluster/health", "état du cluster"]]}}
    assert progression_errors([table] + blocks) == {}


@pytest.mark.parametrize("edges,caption,bad", [
    ([["doc", "p"], ["p", "r1"], ["r1", "r2"], ["r2", "r3"]], "Le document est routé vers le shard primaire puis répliqué.", True),
    ([["doc", "p"], ["p", "r1"], ["p", "r2"], ["p", "r3"]], "Le document est routé vers le shard primaire puis répliqué.", False),
    ([["a", "b"], ["b", "c"], ["c", "d"], ["d", "e"]], "Ingest, clean, train, deploy.", False),  # a real pipeline is a chain
])
def test_a_chain_diagram_whose_caption_describes_a_fan_out_is_flagged(edges, caption, bad):
    nodes = {n: n.upper() for e in edges for n in e}
    _, (errors,) = check_blocks([{"component": "diagram", "origin": "model_added",
                                  "data": {"nodes": nodes, "edges": edges, "caption": caption}}], {})
    assert bool([e for e in errors if "branch" in e]) == bad


def test_a_route_through_nodes_drawn_as_boxes_holding_shards_is_not_a_chain():
    src = ('flowchart LR\n  doc["Document"]\n  subgraph N1["Node 1 (master)"]\n    a0["a0 primaire"]\n  end\n'
           '  subgraph N2["Node 2"]\n    b3p["b3 primaire"]\n  end\n  subgraph N3["Node 3"]\n    b3r["b3 réplique"]\n  end\n'
           '  doc --> N1\n  N1 -->|"route"| b3p\n  b3p -->|"réplication"| b3r')
    _, (errors,) = check_blocks([{"component": "diagram", "origin": "model_added", "data": {"mermaid": src, "caption": "routé puis répliqué"}}], {})
    assert errors == []


@pytest.fixture
def two_cohorts(material, model):
    make_pdf(material / "examen_5a.pdf", 1)
    make_pdf(material / "examen_4a.pdf", 1)
    headers = {"examen_5a.pdf": "Classe(s) : 5ᵉᵐᵉ ERP-BI / 5ᵉᵐᵉ DS", "examen_4a.pdf": "Classe(s) : 4DS | 4ERP-BI"}
    model.handlers["read_page"] = lambda prompt, files: {
        "text": next((v for k, v in headers.items() if f"SOURCE: {k}" in prompt), "cours"), "readable": True}
    roles = model.handlers["propose_roles"]

    def with_exams(prompt, files):
        out = roles(prompt, files)
        for s in out["sources"]:
            if s["name"].startswith("examen_"):
                s["role"], s["paired_with"] = "past exam", None
        return out
    model.handlers["propose_roles"] = with_exams

    def rebuild(prompt, files):
        fourth = "4DS" in prompt
        return {"title": "4DS" if fourth else "5DS", "duration_min": 60, "questions": [
            {"statement": "HBase ?" if fourth else "Gradient ?", "points": 20, "model_answer": "...",
             "chapter": "Convexité" if fourth else "Méthodes de descente"}]}
    model.handlers["rebuild_past_paper"] = rebuild
    return material


def test_only_the_learners_cohort_weighs_the_course_and_the_other_stays_as_practice(client, two_cohorts, model):
    cid = generate(client, two_cohorts, model)
    ch = chapters(client, cid)
    assert (ch["Convexité"]["exam_weight"], ch["Méthodes de descente"]["exam_weight"]) == (0, 1)
    types = client.get(f"/api/courses/{cid}/cram").json()["question_types"]
    assert [t["name"] for t in types] == ["Type Méthodes de descente"]
    mock_input = next(p for step, p in model.prompts if step == "write_mock_exam")
    assert "Gradient ?" in mock_input and "HBase ?" not in mock_input
    exams = {e["title"]: e for e in client.get(f"/api/courses/{cid}/exams").json()}
    assert (exams["4DS"]["cohort"], exams["4DS"]["in_scope"], exams["5DS"]["in_scope"]) == ("4", False, True)

    calls = len(model.prompts)
    assert client.put(f"/api/courses/{cid}/exams/{exams['4DS']['id']}/scope", json={"in_scope": True}).status_code == 200
    assert chapters(client, cid)["Convexité"]["exam_weight"] == 0.5 and len(model.prompts) == calls  # no model call
    assert json.dumps(client.get(f"/api/courses/{cid}/cram").json()).count("HBase ?") == 1


def test_the_ledger_tells_apart_two_sections_with_the_same_title():
    concepts = {"pas fixe": (1, "Exercices"), "pas optimal": (3, "Exercices")}
    block = {"id": 7, "section": "Exercices", "at": 1, "tests": ["pas fixe", "pas optimal"]}
    errors = ledger_errors([block], concepts)
    assert len(errors[7]) == 1 and '"pas optimal"' in errors[7][0]


def test_a_paper_set_for_two_years_counts_for_either():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE exams (id INTEGER PRIMARY KEY, course_id INT, kind TEXT, cohort TEXT, in_scope INT DEFAULT 1)")
    db.executemany("INSERT INTO exams (id, course_id, kind, cohort) VALUES (?, 1, 'past_paper', ?)",
                   [(1, "5"), (2, "5"), (3, "4"), (4, "4/5")])
    default_scope(db, 1, [1, 2, 3, 4])
    assert {r[0]: r[1] for r in db.execute("SELECT id, in_scope FROM exams")} == {1: 1, 2: 1, 3: 0, 4: 1}
    assert cohort_of("Classe(s) : 4DS | 5DS") == "4/5"


# The real course-5 drill: the doc id and the new status were in an earlier terminal session, never in the drill itself.
UPDATE_DRILL = {"title": "Écrire les commandes ES (6 shards / 3 réplicas + partial update)", "language": "json",
                "template": "PUT /ventes\n{\n  \"settings\": {\n    \"number_of_shards\": [[1]],\n    \"number_of_replicas\": [[2]]\n  }\n}\n\n"
                            "POST /ventes/_update/[[3]]\n{\n  \"doc\": {\n    \"Statut\": \"[[4]]\"\n  }\n}",
                "blanks": [{"answers": [a]} for a in ("6", "3", "transaction_001", "annulée")]}


def test_a_value_only_the_exercise_can_give_must_be_in_the_exercise():
    session = {"id": 1, "chapter": 1, "section": "REST", "component": "terminal", "data": {"entries": [
        {"command": "POST /ventes/_update/transaction_001 {\"doc\": {\"Statut\": \"annulée\"}}"}]}}
    drill = {"id": 2, "chapter": 1, "section": "Shards", "component": "fill_blanks", "data": UPDATE_DRILL}
    errors = progression_errors([session, drill])[2]
    assert any('"transaction_001"' in e for e in errors) and any('"annulée"' in e for e in errors) and len(errors) == 2
    given = UPDATE_DRILL | {"title": "Index `ventes` (6 shards, 3 réplicas), puis passer le Statut du document `transaction_001` à « annulée »"}
    assert progression_errors([session, drill | {"data": given}]) == {}


# The real course-5 pair: the code exercise right after the drill asks the same partial update on the same document.
UPDATE_EXERCISE = {"title": "Partial update d'un document Elasticsearch", "language": "json",
                   "task": "Le document `transaction_001` dans l'index **ventes** a `\"Statut\": \"payée\"`. Mettre à jour uniquement `Statut` à `\"annulée\"`.",
                   "starter": "POST /ventes/_update/____\n{\n  \"____\": {\n    \"Statut\": \"____\"\n  }\n}",
                   "solution": "POST /ventes/_update/transaction_001\n{\n  \"doc\": {\n    \"Statut\": \"annulée\"\n  }\n}", "hints": []}


def test_practice_repeating_an_earlier_one_with_the_same_names_and_values_is_flagged():
    drill = {"id": 1, "chapter": 1, "section": "Shards", "component": "fill_blanks", "data": UPDATE_DRILL}
    again = {"id": 2, "chapter": 1, "section": "Shards", "component": "code_exercise", "data": UPDATE_EXERCISE}
    [err] = repeat_errors([drill, again])[2]
    assert "Écrire les commandes ES" in err and failure_class(MARK + err) == "repeat"
    varied = UPDATE_EXERCISE | {"solution": "POST /clients/_update/client_042\n{\n  \"doc\": {\n    \"Ville\": \"Sfax\"\n  }\n}"}
    assert repeat_errors([drill, again | {"data": varied}]) == {}
    assert repeat_errors([drill, again | {"chapter": 2}]) == {}  # another Chapter's revision may come back to it
    quiz = lambda i: {"id": i, "chapter": 1, "section": "REST", "component": "quiz", "data": {"questions": [
        {"prompt": "Pour une mise à jour partielle d'un seul champ, quelle commande utilise-t-on ?", "options": ["PUT", "POST _update"], "correct": [1]}]}}
    assert list(repeat_errors([quiz(1), quiz(2)])) == [2]


def test_a_name_the_quiz_prompt_gives_is_not_tested():
    q = {"prompt": "L'index `capteurs` est créé avec `number_of_shards: 4` et `number_of_replicas: 2`. Combien de shards ?",
         "options": ["6", "8", "12", "16"], "correct": [2]}
    taught = {"id": 1, "chapter": 1, "section": "S", "component": "table", "data": {"rows": [["number_of_shards", "number_of_replicas"]]}}
    assert progression_errors([taught, {"id": 2, "chapter": 1, "section": "S", "component": "quiz", "data": {"questions": [q]}}]) == {}
    join = {"prompt": "`a` contient `(\"L1\", 5)`. Que renvoie `a.join(b).collect()` ?", "options": ["[(\"L1\", (5, \"Centre\"))]", "[]"], "correct": [0]}
    taught["data"]["rows"].append(["join", "collect", "centre"])
    assert progression_errors([taught, {"id": 2, "chapter": 1, "section": "S", "component": "quiz", "data": {"questions": [join]}}]) == {}


def test_two_sections_teaching_the_same_commands_overlap():
    """The real course-5 ElasticSearch Chapter: "REST API: Request Types" and "CRUD Operations" drill the same document calls;
    PUT index or POST _update, which most of its Sections use, are the Chapter's ground, not an overlap."""
    sections = json.loads((Path(__file__).parent / "es_chapter.json").read_text())
    [(a, b, shared)] = section_overlaps(sections)
    assert (a["title"], b["title"]) == ("REST API: Request Types", "CRUD Operations: PUT, GET, DELETE")
    assert shared == ["DELETE _doc", "GET _doc", "PUT _doc"]
