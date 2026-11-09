from fastapi.testclient import TestClient

from conftest import FakeSearch, make_pdf
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
    with TestClient(create_app(data_dir, model, FakeSearch()), base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000)) as c:
        cid = start(c, material)
    with TestClient(create_app(data_dir, model, FakeSearch()), base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000)) as c:
        assert c.get(f"/api/courses/{cid}/run").json()["gate"] == "found"
        assert c.post(f"/api/courses/{cid}/gates/found", json={"goal": "deep"}).status_code == 200
        assert c.get(f"/api/courses/{cid}").json()["goal"] == "deep"


def test_a_page_that_keeps_failing_is_marked_unreadable_and_the_run_goes_on(client, material, model):
    from course_factory.pi_step import StepFailed

    def flaky(prompt, files):
        if "TD1.pdf" in prompt:
            raise StepFailed("pi exited 1")
        return {"text": "ok", "readable": True}

    model.handlers["read_page"] = flaky
    cid = start(client, material)
    assert client.get(f"/api/courses/{cid}/run").json()["gate"] == "found"
    assert client.get(f"/api/courses/{cid}/found").json()["unreadable_pages"] == [{"source": "TD1.pdf", "page": 1}]


def test_failed_run_reports_failure_and_retry_resumes_without_rereading(client, material, model):
    from course_factory.pi_step import StepFailed

    roles = model.handlers["propose_roles"]

    def flaky(prompt, files):
        if model.broken:
            raise StepFailed("pi exited 1")
        return roles(prompt, files)

    model.broken = True
    model.handlers["propose_roles"] = flaky
    cid = start(client, material)
    run = client.get(f"/api/courses/{cid}/run").json()
    assert run["status"] == "failed" and "pi exited 1" in run["error"]

    reads_before = sum(1 for s, _ in model.calls if s == "read_page")
    model.broken = False
    assert client.post(f"/api/courses/{cid}/run/retry").status_code == 200
    run = client.get(f"/api/courses/{cid}/run").json()
    assert run["gate"] == "found" and run["error"] is None
    assert sum(1 for s, _ in model.calls if s == "read_page") == reads_before  # pages read before the failure are not reread
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


def test_status_shows_the_pipeline_with_the_current_step(client, material):
    cid = start(client, material)
    pipe = client.get(f"/api/courses/{cid}/run").json()["pipeline"]
    states = {p["name"]: p["state"] for p in pipe}
    assert [p["name"] for p in pipe][:4] == ["import_sources", "read_pages", "propose_roles", "found_gate"]
    assert states["read_pages"] == "done" and states["found_gate"] == "current" and states["build_labs"] == "waiting"
    assert all(p["label"] for p in pipe) and [p["gate"] for p in pipe].count(True) == 3


def test_newest_traces_feed_the_run_screen(client, material):
    cid = start(client, material)
    feed = client.get(f"/api/courses/{cid}/traces?limit=2").json()
    assert [t["step"] for t in feed] == ["propose_roles", "read_page"]  # newest first


def test_a_running_model_step_is_visible_while_it_thinks(client, material, model):
    from course_factory.pi_step import report
    seen = []

    def reading(prompt, files):
        report("thinking", "Je lis la page")
        report("output", '{"text": "')
        seen.append(client.get("/api/courses/1/run").json()["activity"])
        return {"text": "ok", "readable": True}

    model.handlers["read_page"] = reading
    cid = start(client, material)
    a = seen[0]
    assert a["step"] == "read_page" and a["inputs"]["page"] == "1" and a["inputs"]["source"]
    assert a["thinking"] == "Je lis la page" and a["output"] == '{"text": "' and a["elapsed"] >= 0
    assert client.get(f"/api/courses/{cid}/run").json()["activity"] is None  # nothing runs at the gate


def picked(material, top="optimisation"):
    """What a folder picker sends: each file with its path relative to the picked folder's parent."""
    return [("files", (f"{top}/{p.relative_to(material).as_posix()}", p.read_bytes(), "application/pdf"))
            for p in sorted(material.rglob("*")) if p.is_file()]


def test_a_picked_folder_is_uploaded_and_imported(client, material):
    r = client.post("/api/courses/upload", data={"name": "Optimisation"}, files=picked(material))
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert client.get(f"/api/courses/{cid}/run").json()["gate"] == "found"
    names = sorted(s["name"] for s in client.get(f"/api/courses/{cid}/found").json()["sources"])
    assert names == sorted(p.relative_to(material).as_posix() for p in material.rglob("*") if p.is_file())


def test_uploaded_paths_cannot_escape_the_course(client, material):
    bad = [("files", ("optimisation/../../evil.pdf", b"%PDF", "application/pdf"))]
    assert client.post("/api/courses/upload", data={"name": "x"}, files=bad).status_code == 422
    assert client.post("/api/courses/upload", data={"name": "x"}, files=[]).status_code == 422


def test_the_course_list_summarises_each_course_for_the_home_hub(client, material):
    cid = start(client, material)
    c = next(c for c in client.get("/api/courses").json() if c["id"] == cid)
    assert c["run"]["gate"] == "found" and c["run"]["pages_read"] == c["run"]["pages_total"] == 4
    assert c["chapters_published"] == c["chapters_total"] == 0 and c["cards_due"] == 0 and c["exam_countdown_days"] is None


def test_system_reports_model_and_gpu(client):
    assert set(client.get("/api/system").json()) == {"model", "gpu"}


def test_virtualenvs_caches_and_hidden_folders_are_not_imported(client, material):
    for junk in ("viz/.venv/lib/site.py", "viz/venv/lib/python3.13/site-packages/m/icon.pdf", "viz/__pycache__/a.pyc",
                 "web/node_modules/x/index.js", ".git/HEAD"):
        (material / junk).parent.mkdir(parents=True, exist_ok=True)
        (material / junk).write_text("x")
    (material / "viz" / "plot.py").write_text("print(1)")
    cid = start(client, material)
    names = {s["name"] for s in client.get(f"/api/courses/{cid}/found").json()["sources"]}
    assert names == {"cours.pdf", "TD1.pdf", "TD1_corrige.pdf", "data.csv", "viz/plot.py"}


def test_the_course_map_lists_every_file_with_its_pages_read(client, material):
    cid = start(client, material)
    files = {f["name"]: f for f in client.get(f"/api/courses/{cid}/map").json()}
    assert files["cours.pdf"] == {"name": "cours.pdf", "pages": 2, "read": 2, "unreadable": 0, "role": files["cours.pdf"]["role"]}
    assert files["data.csv"]["pages"] == 0 and files["data.csv"]["role"] == "data"
    assert client.get("/api/courses/999/map").status_code == 404


def test_run_shows_each_folder_with_its_sources_and_pages_read(client, material):
    (material / "tp").mkdir()
    make_pdf(material / "tp" / "TP1.pdf", 3)
    cid = start(client, material)
    folders = {f["name"]: f for f in client.get(f"/api/courses/{cid}/run").json()["progress"]["folders"]}
    assert set(folders) == {"", "tp"}
    assert folders["tp"]["sources"] == [{"name": "tp/TP1.pdf", "pages": 3, "read": 3}]
    assert (folders[""]["pages"], folders[""]["read"], len(folders[""]["sources"])) == (4, 4, 4)
