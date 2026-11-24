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


def page_photo(turn: int = 0) -> bytes:
    """A sheet with left-aligned lines of uneven length on a darker table, turned by `turn` degrees, as a phone JPEG."""
    from PIL import ImageDraw
    page = Image.new("RGB", (420, 560), (240, 238, 230))
    d = ImageDraw.Draw(page)
    for i, n in enumerate([300, 120, 260, 200, 90, 310, 180, 240, 140, 280, 100, 220]):
        d.rectangle((40, 40 + i * 40, 40 + n, 52 + i * 40), fill=(30, 40, 90))
    table = Image.new("RGB", (640, 760), (110, 80, 50))
    table.paste(page, (110, 100))
    buf = io.BytesIO()
    table.rotate(turn, expand=True).save(buf, "JPEG")
    return buf.getvalue()


def test_a_photo_is_cropped_to_the_sheet_flattened_and_turned_upright(monkeypatch):
    import numpy as np
    from course_factory import scan
    # SAM 3 stands in as "the bright region": the test checks what is done with the sheet it finds, not the model
    monkeypatch.setattr(scan, "page_mask", lambda im: np.asarray(im.convert("L")) > 200)
    for turn in (0, 90, 180, 270):
        out = scan.clean_photo(page_photo(turn))
        assert abs(out.width - 420) < 25 and abs(out.height - 560) < 25, (turn, out.size)  # just the sheet, portrait
        ink = np.asarray(out.convert("L")) < 128
        assert ink[:, :35].sum() == 0 and ink[:, 35:60].sum() > 0, turn  # the lines start at the left margin: upright
        assert np.asarray(out.convert("L"))[5:30, 5:400].mean() > 235  # the paper comes out white
    monkeypatch.setattr(scan, "page_mask", lambda im: (_ for _ in ()).throw(RuntimeError("no GPU")))
    assert scan.clean_photo(page_photo(0)).size == (640, 760)  # SAM 3 can't run: no crop, the photo is still kept


def test_a_page_photographed_on_one_device_shows_on_another_and_can_be_removed(client, with_exam, model, monkeypatch):
    from course_factory import scan
    monkeypatch.setattr(scan, "page_mask", lambda im: None)
    cid, copy_id, q1, _ = sat_past_paper(client, with_exam, model)
    eid = client.get(f"/api/courses/{cid}/copies/{copy_id}").json()["exam_id"]
    exam = next(e for e in client.get(f"/api/courses/{cid}/exams").json() if e["id"] == eid)
    assert exam["open_copy"] == copy_id  # the phone finds the sitting the computer started
    url = f"/api/courses/{cid}/copies/{copy_id}/files"
    for _ in range(2):
        assert client.post(url, files={"file": ("p.jpg", page_photo(), "image/jpeg")}, data={"question_id": str(q1["id"])}).status_code == 201
    assert [f["question_id"] for f in client.get(f"/api/courses/{cid}/copies/{copy_id}").json()["files"]] == [q1["id"], q1["id"]]
    assert client.get(f"{url}/0").content[:2] == b"\xff\xd8"  # stored as the cleaned JPEG
    assert [f["index"] for f in client.delete(f"{url}/0").json()["files"]] == [0]
    assert client.delete(f"{url}/3").status_code == 404
    client.post(f"/api/courses/{cid}/copies/{copy_id}/hand-in")
    assert client.delete(f"{url}/0").status_code == 409
    assert next(e for e in client.get(f"/api/courses/{cid}/exams").json() if e["id"] == eid)["open_copy"] is None
