import io

from PIL import Image

from conftest import make_pdf
from test_chapters import generate
from test_exams import exam_by_kind, with_exam  # noqa: F401  (fixture)


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(buf, "PNG")
    return buf.getvalue()


def sat_past_paper(client, material, model):
    cid = generate(client, material, model)
    eid = exam_by_kind(client, cid)["past_paper"][0]["id"]
    q1, q2 = client.get(f"/api/courses/{cid}/exams/{eid}").json()["questions"]
    copy = client.post(f"/api/courses/{cid}/exams/{eid}/copies").json()
    client.put(f"/api/courses/{cid}/copies/{copy['id']}/answers", json={"answers": {str(q1["id"]): "La hessienne est positive."}})
    return cid, copy["id"], q1, q2


def test_copy_is_transcribed_and_graded_step_by_step(client, with_exam, model, tmp_path):
    cid, copy_id, q1, q2 = sat_past_paper(client, with_exam, model)
    url = f"/api/courses/{cid}/copies/{copy_id}"
    r = client.post(f"{url}/files", files={"file": ("ink.png", png(), "image/png")}, data={"kind": "ink", "question_id": str(q2["id"])})
    assert r.status_code == 201
    make_pdf(tmp_path / "scan.pdf", 2)
    r = client.post(f"{url}/files", files={"file": ("scan.pdf", (tmp_path / "scan.pdf").read_bytes(), "application/pdf")}, data={"kind": "pdf"})
    assert [f["question_id"] for f in r.json()["files"]] == [q2["id"], None, None]  # the PDF became two page images
    assert client.post(f"{url}/grade").status_code == 409  # not handed in yet
    client.post(f"{url}/hand-in")
    grade = client.post(f"{url}/grade").json()["grade"]
    g1, g2 = grade["questions"]
    # Q1 had a scheme (4 + 2): first step clamped to its 4 points, typed answer plus the loose PDF pages transcribed
    assert [(s["step"], s["awarded"]) for s in g1["steps"]] == [("Hessienne", 4), ("Conclusion", 0)]
    assert g1["answer"].startswith("La hessienne est positive.") and "(2 images)" in g1["answer"]
    assert not g1["scheme_derived"] and g1["files"] == [1, 2]
    # Q2 had none: one is derived and scaled to its 14 points, and shown
    assert g2["scheme_derived"] and [(s["step"], s["points"]) for s in g2["steps"]] == [("Poser le pas", 7), ("Calculer", 7)]
    assert "(3 images)" in g2["answer"] and g2["files"] == [0, 1, 2]
    assert g2["steps"][1]["comment"] == "missing" and g2["steps"][1]["page"]["source"]  # lost points link a course page
    assert g1["steps"][0]["page"] is None  # full marks: nothing to review
    assert (grade["total"], grade["max"]) == (11, 20)
    correction = client.get(url).json()["correction"]
    assert correction["questions"][1]["scheme"] == [{"step": "Poser le pas", "points": 7}, {"step": "Calculer", "points": 7}]
    assert client.get(f"/api/courses/{cid}/copies").json()[0]["total"] == 11
    assert client.get(f"{url}/files/0").content[:4] == b"\x89PNG"
    assert client.post(f"{url}/files", files={"file": ("x.png", png(), "image/png")}).status_code == 409  # graded: closed
    assert all(t["error"] is None for t in client.get(f"/api/courses/{cid}/traces").json()
               if t["step"] in ("derive_scheme", "transcribe_copy", "grade_answer"))


def test_uploads_are_validated(client, with_exam, model):
    cid, copy_id, q1, _ = sat_past_paper(client, with_exam, model)
    url = f"/api/courses/{cid}/copies/{copy_id}/files"
    assert client.post(url, files={"file": ("a.txt", b"hi", "text/plain")}).status_code == 415
    assert client.post(url, files={"file": ("a.pdf", b"not a pdf", "application/pdf")}).status_code == 422
    assert client.post(url, files={"file": ("a.png", png(), "image/png")}, data={"kind": "video"}).status_code == 422
    other = exam_by_kind(client, cid)["mock"][0]["id"]
    other_q = client.get(f"/api/courses/{cid}/exams/{other}").json()["questions"][0]["id"]
    assert client.post(url, files={"file": ("a.png", png(), "image/png")}, data={"question_id": str(other_q)}).status_code == 422
    assert client.get(f"/api/courses/{cid}/copies/{copy_id}/files/5").status_code == 404
