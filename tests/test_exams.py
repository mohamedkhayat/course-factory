import datetime as dt

import pytest

from conftest import make_pdf
from course_factory import exams
from test_chapters import generate


@pytest.fixture
def with_exam(material):
    make_pdf(material / "examen_2024.pdf", 2)
    make_pdf(material / "examen_2024_corrige.pdf", 1)
    return material


def exam_by_kind(client, cid):
    out = {}
    for e in client.get(f"/api/courses/{cid}/exams").json():
        out.setdefault(e["kind"], []).append(e)
    return out


def test_past_paper_rebuilt_from_exam_and_corrige_then_mocks(client, with_exam, model):
    cid = generate(client, with_exam, model)
    assert client.get(f"/api/courses/{cid}/run").json()["gate"] == "chapter_review"
    prompt = next(p for step, p in model.prompts if step == "rebuild_past_paper")
    assert "examen_2024_corrige.pdf" in prompt.split("CORRECTION:", 1)[1].split("EXAM:", 1)[0]
    assert "examen_2024.pdf" in prompt.split("EXAM:", 1)[1]
    by_kind = exam_by_kind(client, cid)
    past = by_kind["past_paper"][0]
    convexite = next(c["id"] for c in client.get(f"/api/courses/{cid}/outline").json()["chapters"] if c["title"] == "Convexité")
    assert past["title"] == "Examen 2024" and past["duration_min"] == 120 and past["chapters"] == [convexite]  # unknown titles dropped
    assert [m["title"] for m in by_kind["mock"]] == ["Examen blanc 1", "Examen blanc 2"]
    mock_prompt = next(p for step, p in model.prompts if step == "write_mock_exam")
    assert "Montrer que" in mock_prompt and "exam_weight" in mock_prompt
    assert "Hessienne positive" not in mock_prompt  # past papers go in without their answers


def test_scheme_must_add_up_and_is_retried(client, with_exam, model):
    answers = iter([
        {"title": "E", "duration_min": 60, "questions": [{"statement": "Q", "points": 5, "model_answer": "A",
                                                          "scheme": [{"step": "s", "points": 2}]}]},
        {"title": "E", "duration_min": 60, "questions": [{"statement": "Q", "points": 5, "model_answer": "A",
                                                          "scheme": [{"step": "s", "points": 5}]}]}])
    model.handlers["rebuild_past_paper"] = lambda prompt, files: next(answers)
    cid = generate(client, with_exam, model)
    past = exam_by_kind(client, cid)["past_paper"][0]
    traces = [t for t in client.get(f"/api/courses/{cid}/traces").json() if t["step"] == "rebuild_past_paper"]
    assert [bool(t["error"]) for t in traces] == [True, False] and "add up" in traces[0]["error"]
    assert past["title"] == "E"


def test_broken_math_in_a_question_is_flagged(client, with_exam, model):
    model.handlers["rebuild_past_paper"] = lambda prompt, files: {"title": "E", "duration_min": 60, "questions": [
        {"statement": r"Soit $\frac{1}{$", "points": 5, "model_answer": "A"}]}
    cid = generate(client, with_exam, model)
    eid = exam_by_kind(client, cid)["past_paper"][0]["id"]
    copy = client.post(f"/api/courses/{cid}/exams/{eid}/copies").json()
    client.post(f"/api/courses/{cid}/copies/{copy['id']}/hand-in")
    q = client.get(f"/api/courses/{cid}/copies/{copy['id']}").json()["correction"]["questions"][0]
    assert q["flags"]


def test_exam_mode_hides_answers_saves_continuously_and_hands_in(client, with_exam, model):
    cid = generate(client, with_exam, model)
    eid = exam_by_kind(client, cid)["past_paper"][0]["id"]
    sheet = client.get(f"/api/courses/{cid}/exams/{eid}").json()
    assert sheet["total_points"] == 20 and "model_answer" not in sheet["questions"][0] and "scheme" not in sheet["questions"][0]
    copy = client.post(f"/api/courses/{cid}/exams/{eid}/copies").json()
    assert 7190 <= copy["remaining_seconds"] <= 7200 and "correction" not in copy
    q1, q2 = (str(q["id"]) for q in sheet["questions"])
    client.put(f"/api/courses/{cid}/copies/{copy['id']}/answers", json={"answers": {q1: "brouillon"}})
    r = client.put(f"/api/courses/{cid}/copies/{copy['id']}/answers", json={"answers": {q2: "$x_1=0.5$"}})
    assert r.json()["answers"] == {q1: "brouillon", q2: "$x_1=0.5$"}
    assert client.put(f"/api/courses/{cid}/copies/{copy['id']}/answers", json={"answers": {"999": "x"}}).status_code == 422
    done = client.post(f"/api/courses/{cid}/copies/{copy['id']}/hand-in").json()
    assert done["handed_in_at"] and done["correction"]["questions"][0]["model_answer"] == "Hessienne positive."
    assert done["correction"]["questions"][0]["scheme"][0] == {"step": "Hessienne", "points": 4}
    assert client.put(f"/api/courses/{cid}/copies/{copy['id']}/answers", json={"answers": {q1: "late"}}).status_code == 409
    assert client.post(f"/api/courses/{cid}/copies/{copy['id']}/hand-in").status_code == 409


def test_answers_refused_once_time_is_up(client, with_exam, model, monkeypatch):
    cid = generate(client, with_exam, model)
    eid = exam_by_kind(client, cid)["mock"][0]["id"]
    copy = client.post(f"/api/courses/{cid}/exams/{eid}/copies").json()
    qid = str(client.get(f"/api/courses/{cid}/exams/{eid}").json()["questions"][0]["id"])
    start = exams.now()
    monkeypatch.setattr(exams, "now", lambda: start + dt.timedelta(minutes=90, seconds=30))
    assert client.put(f"/api/courses/{cid}/copies/{copy['id']}/answers", json={"answers": {qid: "just in"}}).status_code == 200
    monkeypatch.setattr(exams, "now", lambda: start + dt.timedelta(minutes=92))
    assert client.get(f"/api/courses/{cid}/copies/{copy['id']}").json()["remaining_seconds"] == 0
    assert client.put(f"/api/courses/{cid}/copies/{copy['id']}/answers", json={"answers": {qid: "late"}}).status_code == 409
    assert client.post(f"/api/courses/{cid}/copies/{copy['id']}/hand-in").status_code == 200


def test_resume_after_failed_mock_keeps_built_exams(client, with_exam, model):
    original = model.handlers["write_mock_exam"]
    model.handlers["write_mock_exam"] = lambda prompt, files: "nope" if "number 2" in prompt else original(prompt, files)
    cid = generate(client, with_exam, model)
    assert client.get(f"/api/courses/{cid}/run").json()["status"] == "failed"
    model.handlers["write_mock_exam"] = original
    model.prompts.clear()
    client.post(f"/api/courses/{cid}/run/retry")
    assert [s for s, _ in model.prompts] == ["write_mock_exam"]
    assert len(exam_by_kind(client, cid)["mock"]) == 2 and len(exam_by_kind(client, cid)["past_paper"]) == 1


def test_exam_weight_comes_from_the_past_papers_and_orders_cram(client, with_exam, model):
    from test_chapters import CONVEXES, EXERCICES, GRADIENT, chapters, sections_written
    cid = generate(client, with_exam, model)  # 6 points test Convexité, 14 test Méthodes de descente
    ch = chapters(client, cid)
    assert (ch["Convexité"]["exam_weight"], ch["Méthodes de descente"]["exam_weight"]) == (0.3, 0.7)
    assert (ch["Convexité"]["exam_hits"], ch["Méthodes de descente"]["exam_hits"]) == (1, 1)
    steps = [step for step, _ in model.prompts]
    assert steps.index("rebuild_past_paper") < steps.index("write_section")
    assert sections_written(model) == [GRADIENT, EXERCICES, CONVEXES]  # equal Priority: the heavier Chapter first


def test_one_more_mock_exam_on_demand_is_grounded_in_what_the_chapters_teach(client, with_exam, model):
    cid = generate(client, with_exam, model)
    model.prompts.clear()
    assert client.post(f"/api/courses/{cid}/exams/mock").status_code == 202
    assert client.get(f"/api/courses/{cid}/job").json()["state"] == "done"
    assert len(exam_by_kind(client, cid)["mock"]) == 3
    prompt = next(p for step, p in model.prompts if step == "write_mock_exam")
    digest = prompt.split("DIGEST:", 1)[1].split("PAST:", 1)[0]
    assert "Convexité" in digest and "commands_and_code" in digest
    assert "Examen blanc 2" in prompt.split("PAST:", 1)[1]  # the Mock exams already written, so the new one differs


def test_digest_lists_each_chapters_commands_once():
    import json, sqlite3
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("CREATE TABLE chapters (id, course_id, title, priority, position); CREATE TABLE sections (id, chapter_id, position, teaches);"
                     "CREATE TABLE blocks (section_id, position, component, data);")
    db.execute("INSERT INTO chapters VALUES (1, 7, 'Docker', 'focus', 0)")
    db.execute("INSERT INTO sections VALUES (1, 1, 0, ?)", (json.dumps(["image", "conteneur"]),))
    run = json.dumps({"entries": [{"command": "docker build -t api ."}, {"command": "docker run -p 8000:8000 api"}]})
    for pos, (comp, data) in enumerate([("terminal", run), ("terminal", run), ("code", json.dumps({"code": "FROM python:3.11"})),
                                        ("prose", json.dumps({"markdown": "texte"}))]):
        db.execute("INSERT INTO blocks VALUES (1, ?, ?, ?)", (pos, comp, data))
    ctx = type("Ctx", (), {"db": db})()
    assert exams.course_digest(ctx, 7) == [{"chapter": "Docker", "concepts": ["image", "conteneur"], "commands_and_code": [
        "docker build -t api .\ndocker run -p 8000:8000 api", "FROM python:3.11"]}]
