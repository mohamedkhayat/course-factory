import pytest


def to_outline_gate(client, material, model, goal=None, exclude=()):
    cid = client.post("/api/courses", json={"name": "Optimisation", "folder": str(material)}).json()["id"]
    for s in client.get(f"/api/courses/{cid}/found").json()["sources"]:
        if s["name"] in exclude:
            client.patch(f"/api/courses/{cid}/sources/{s['id']}", json={"excluded": True})
    client.post(f"/api/courses/{cid}/gates/found", json=goal or {"goal": "cram", "exam_date": "2027-01-15"})
    return cid


@pytest.fixture
def worded_pages(model):
    words = {"cours.pdf, page 1": "ensemble convexe définition", "cours.pdf, page 2": "méthode du gradient pas fixe",
             "TD1.pdf, page 1": "exercice gradient", "TD1_corrige.pdf, page 1": "corrigé exercice"}
    model.handlers["read_page"] = lambda prompt, files: {
        "text": next(v for k, v in words.items() if f"SOURCE: {k}" in prompt), "readable": True}


def test_found_approval_leads_to_outline_gate(client, material, model):
    cid = to_outline_gate(client, material, model)
    assert client.get(f"/api/courses/{cid}/run").json()["gate"] == "outline"
    chapters = client.get(f"/api/courses/{cid}/outline").json()["chapters"]
    assert [c["title"] for c in chapters] == ["Convexité", "Méthodes de descente"]
    assert [c["exam_weight"] for c in chapters] == [0, 0]  # known once the past papers are rebuilt
    assert all(c["priority"] == "normal" for c in chapters)
    # references to unknown Sources or pages past the end are dropped
    assert chapters[0]["sections"][0]["pages"] == [{"source": "cours.pdf", "page": 1}]
    assert chapters[1]["sections"][0]["pages"] == [{"source": "cours.pdf", "page": 2}]


def test_outline_proposal_sees_goal_and_not_excluded_sources(client, material, model):
    prompts = []
    original = model.handlers["propose_outline"]
    model.handlers["propose_outline"] = lambda prompt, files: prompts.append(prompt) or original(prompt, files)
    to_outline_gate(client, material, model, goal={"goal": "deep"}, exclude={"TD1_corrige.pdf"})
    assert "Goal: deep" in prompts[0] and "TD1_corrige.pdf" not in prompts[0] and "TD1.pdf" in prompts[0]


def test_search_finds_cited_page_and_skips_excluded(client, material, model, worded_pages):
    cid = to_outline_gate(client, material, model, exclude={"TD1_corrige.pdf"})
    hits = client.get(f"/api/courses/{cid}/search", params={"q": "gradient pas fixe"}).json()
    assert hits[0]["source"] == "cours.pdf" and hits[0]["page"] == 2
    assert all(h["source"] != "TD1_corrige.pdf" for h in client.get(f"/api/courses/{cid}/search", params={"q": "corrigé"}).json())


def test_owner_edits_outline_then_approves(client, material, model):
    cid = to_outline_gate(client, material, model)
    edited = {"chapters": [
        {"title": "Méthodes de descente", "priority": "focus",
         "sections": [{"title": "Gradient", "pages": [{"source": "cours.pdf", "page": 2}]}]},
        {"title": "Convexité", "priority": "skip", "sections": []}]}
    r = client.put(f"/api/courses/{cid}/outline", json=edited)
    assert r.status_code == 200, r.text
    chapters = r.json()["chapters"]
    assert [(c["title"], c["priority"]) for c in chapters] == [("Méthodes de descente", "focus"), ("Convexité", "skip")]
    bad = {"chapters": [{"title": "x", "priority": "urgent", "sections": []}]}
    assert client.put(f"/api/courses/{cid}/outline", json=bad).status_code == 422
    assert client.put(f"/api/courses/{cid}/outline", json={"chapters": []}).status_code == 422

    assert client.post(f"/api/courses/{cid}/gates/outline").status_code == 200
    run = client.get(f"/api/courses/{cid}/run").json()
    assert run["gate"] != "outline", run
    assert client.put(f"/api/courses/{cid}/outline", json=edited).status_code == 409


def test_goal_can_be_switched_after_found_gate(client, material, model):
    cid = to_outline_gate(client, material, model, goal={"goal": "deep"})
    assert client.patch(f"/api/courses/{cid}", json={"goal": "cram"}).status_code == 422
    r = client.patch(f"/api/courses/{cid}", json={"goal": "cram", "exam_date": "2027-01-20"})
    assert r.json()["goal"] == "cram" and r.json()["exam_date"] == "2027-01-20"


def test_an_outline_that_stops_before_some_course_notes_is_retried_naming_them(client, material, model):
    from conftest import make_pdf
    make_pdf(material / "cours2.pdf", 1)
    full = model.handlers["propose_outline"]
    prompts = []

    def stops_early(prompt, files):
        prompts.append(prompt)
        plan = full(prompt, files)
        if "RETRY FEEDBACK" in prompt:
            plan["chapters"].append({"title": "Newton", "sections": [{"title": "Newton", "pages": [{"source": "cours2.pdf", "page": 1}], "teaches": ["Newton"]}]})
        return plan
    model.handlers["propose_outline"] = stops_early
    cid = to_outline_gate(client, material, model)
    assert "cours2.pdf" in prompts[1].split("RETRY FEEDBACK", 1)[1]
    assert [c["title"] for c in client.get(f"/api/courses/{cid}/outline").json()["chapters"]][-1] == "Newton"


def test_an_uncited_page_of_the_notes_joins_the_section_citing_the_page_before_it(client, material, model):
    """Course 6: the outline cited no Section for the definition of a norm (chap1 pp5-6), real content; the Quasi-Newton
    pages marked "[hors programme]" stay out, and so does a title page."""
    from conftest import make_pdf
    make_pdf(material / "cours.pdf", 5)
    texts = {3: "Définition d'une norme : une application N de E dans R+ telle que... " * 8,
             4: "Quasi-Newton [hors programme] : BFGS met à jour une approximation de la hessienne... " * 8, 5: "Fin"}
    model.handlers["read_page"] = lambda prompt, files: {
        "text": next((t for n, t in texts.items() if f"SOURCE: cours.pdf, page {n}" in prompt), "page"), "readable": True}
    cid = to_outline_gate(client, material, model)
    pages = {s["title"]: s["pages"] for c in client.get(f"/api/courses/{cid}/outline").json()["chapters"] for s in c["sections"]}
    assert pages["Gradient"] == [{"source": "cours.pdf", "page": 2}, {"source": "cours.pdf", "page": 3}]
    assert pages["Ensembles convexes"] == [{"source": "cours.pdf", "page": 1}]


def test_a_section_teaching_no_concept_is_sent_back_unless_it_is_for_practice(client, material, model):
    """Courses 2, 3 and 5 were outlined with no Concepts: every progression check then passed without checking anything."""
    full, prompts = model.handlers["propose_outline"], []

    def no_concepts(prompt, files):
        prompts.append(prompt)
        plan = full(prompt, files)
        if "RETRY FEEDBACK" not in prompt:
            plan["chapters"][1]["sections"][0]["teaches"] = []
        return plan
    model.handlers["propose_outline"] = no_concepts
    to_outline_gate(client, material, model)
    feedback = prompts[1].split("RETRY FEEDBACK", 1)[1]
    assert '["Gradient"]' in feedback and "Exercices" not in feedback.split("teaches", 2)[1]


def test_concepts_are_named_for_an_outline_made_before_them_without_touching_it(client, material, model, data_dir):
    """Courses 2, 3 and 5: teaches=[] everywhere and no Chapter plan. Backfilled, their Chapters regenerate with both."""
    import json
    from course_factory import db as dbm
    from course_factory.context import Ctx
    from course_factory.outline import backfill_concepts
    cid = to_outline_gate(client, material, model)
    db = dbm.connect(data_dir / "course-factory.db")
    db.execute("UPDATE sections SET teaches='[]'")
    before = [tuple(r) for r in db.execute("SELECT id, chapter_id, position, title, pages FROM sections ORDER BY id")]
    model.handlers["name_concepts"] = lambda prompt, files: {"chapters": [
        {"title": ch["title"], "sections": [{"title": s["title"], "teaches": [f"idée de {s['title']}", "gradient"]} for s in ch["sections"]]}
        for ch in json.loads(prompt.split("OUTLINE (each Section with the start of the pages it is built from):\n", 1)[1])]}
    backfill_concepts(Ctx(db, model, data_dir, None), cid)  # type: ignore[arg-type]
    assert [tuple(r) for r in db.execute("SELECT id, chapter_id, position, title, pages FROM sections ORDER BY id")] == before
    teaches = [json.loads(r[0]) for r in db.execute("SELECT teaches FROM sections ORDER BY id")]
    assert teaches == [["idée de Ensembles convexes", "gradient"], ["idée de Gradient"], ["idée de Exercices"]]  # once each
