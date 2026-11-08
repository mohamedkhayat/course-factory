from fastapi.testclient import TestClient

from conftest import FakeSearch
from course_factory.app import create_app


def start(client, material):
    r = client.post("/api/courses", json={"name": "Optimisation", "folder": str(material)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_new_course_stops_at_found_gate_with_proposals(client, material):
    cid = start(client, material)

    run = client.get(f"/api/courses/{cid}/run").json()
    assert run["status"] == "waiting" and run["gate"] == "found"

    found = client.get(f"/api/courses/{cid}/found").json()
    by_name = {s["name"]: s for s in found["sources"]}
    assert set(by_name) == {"cours.pdf", "TD1.pdf", "TD1_corrige.pdf", "data.csv"}
    assert by_name["cours.pdf"]["pages"] == 2
    assert by_name["TD1.pdf"]["role"] == "exercise sheet"
    assert by_name["TD1.pdf"]["paired_with"] == by_name["TD1_corrige.pdf"]["id"]
    assert by_name["TD1_corrige.pdf"]["role"] == "correction"
    assert by_name["data.csv"]["role"] == "data"
    assert found["unreadable_pages"] == []


def test_sources_are_copies_and_original_is_untouched(client, material, data_dir):
    before = sorted(p.name for p in material.iterdir())
    start(client, material)
    assert sorted(p.name for p in material.iterdir()) == before
    assert any(p.name == "cours.pdf" for p in data_dir.rglob("*.pdf"))


def test_every_page_is_read_and_traced(client, material, model):
    cid = start(client, material)
    assert sum(1 for step, _ in model.calls if step == "read_page") == 4
    traces = client.get(f"/api/courses/{cid}/traces").json()
    assert {t["step"] for t in traces} == {"read_page", "propose_roles"}
    assert all(t["harness_version"] and t["error"] is None for t in traces)


def test_unreadable_pages_are_called_out(client, material, model):
    model.handlers["read_page"] = lambda prompt, files: {"text": "", "readable": "SOURCE: TD1.pdf, page 1" not in prompt}
    cid = start(client, material)
    found = client.get(f"/api/courses/{cid}/found").json()
    assert found["unreadable_pages"] == [{"source": "TD1.pdf", "page": 1}]


def test_owner_edits_then_approves_with_goal(client, material):
    cid = start(client, material)
    srcs = {s["name"]: s for s in client.get(f"/api/courses/{cid}/found").json()["sources"]}

    r = client.patch(f"/api/courses/{cid}/sources/{srcs['cours.pdf']['id']}", json={"role": "past exam"})
    assert r.status_code == 200 and r.json()["role"] == "past exam"
    assert client.patch(f"/api/courses/{cid}/sources/{srcs['data.csv']['id']}", json={"excluded": True}).json()["excluded"]
    assert client.patch(f"/api/courses/{cid}/sources/{srcs['cours.pdf']['id']}", json={"role": "nonsense"}).status_code == 422

    r = client.post(f"/api/courses/{cid}/gates/found", json={"goal": "cram", "exam_date": "2027-01-15"})
    assert r.status_code == 200, r.text
    course = client.get(f"/api/courses/{cid}").json()
    assert course["goal"] == "cram" and course["exam_date"] == "2027-01-15"
    assert client.get(f"/api/courses/{cid}/run").json()["gate"] != "found"


def test_cram_needs_exam_date(client, material):
    cid = start(client, material)
    assert client.post(f"/api/courses/{cid}/gates/found", json={"goal": "cram"}).status_code == 422


def test_run_resumes_after_restart(data_dir, model, material):
    with TestClient(create_app(data_dir, model, FakeSearch())) as c:
        cid = start(c, material)
    with TestClient(create_app(data_dir, model, FakeSearch())) as c:
        assert c.get(f"/api/courses/{cid}/run").json()["gate"] == "found"
        assert c.post(f"/api/courses/{cid}/gates/found", json={"goal": "deep"}).status_code == 200
        assert c.get(f"/api/courses/{cid}").json()["goal"] == "deep"


def test_failed_run_reports_failure_and_retry_resumes_without_rereading(client, material, model):
    from course_factory.pi_step import StepFailed

    def flaky(prompt, files):
        if "TD1_corrige.pdf" in prompt and model.broken:
            raise StepFailed("pi exited 1")
        return {"text": "ok", "readable": True}

    model.broken = True
    model.handlers["read_page"] = flaky
    cid = start(client, material)
    run = client.get(f"/api/courses/{cid}/run").json()
    assert run["status"] == "failed" and "pi exited 1" in run["error"]

    reads_before = sum(1 for s, _ in model.calls if s == "read_page")
    model.broken = False
    assert client.post(f"/api/courses/{cid}/run/retry").status_code == 200
    run = client.get(f"/api/courses/{cid}/run").json()
    assert run["gate"] == "found" and run["error"] is None
    assert sum(1 for s, _ in model.calls if s == "read_page") - reads_before == 3  # failed page + cours.pdf x2; TD1.pdf, read before the failure, is not reread
    assert len(client.get(f"/api/courses/{cid}/found").json()["sources"]) == 4  # import not duplicated


def test_run_reports_reading_progress(client, material):
    cid = start(client, material)
    run = client.get(f"/api/courses/{cid}/run").json()
    assert run["pages_read"] == run["pages_total"] == 4


def test_second_approval_is_rejected(client, material):
    cid = start(client, material)
    assert client.post(f"/api/courses/{cid}/gates/found", json={"goal": "deep"}).status_code == 200
    assert client.post(f"/api/courses/{cid}/gates/found", json={"goal": "deep"}).status_code == 409


def test_null_role_or_exclusion_is_rejected_but_unpairing_works(client, material):
    cid = start(client, material)
    td = next(s for s in client.get(f"/api/courses/{cid}/found").json()["sources"] if s["name"] == "TD1.pdf")
    assert client.patch(f"/api/courses/{cid}/sources/{td['id']}", json={"excluded": None}).status_code == 422
    assert client.patch(f"/api/courses/{cid}/sources/{td['id']}", json={"role": None}).status_code == 422
    assert client.patch(f"/api/courses/{cid}/sources/{td['id']}", json={"paired_with": None}).json()["paired_with"] is None
