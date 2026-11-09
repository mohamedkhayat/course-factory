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
