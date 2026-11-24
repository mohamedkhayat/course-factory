import json

from conftest import make_pdf
from course_factory import ocw

COURSE = "/courses/6-079-convex-fall-2009"
LEC = f"{ocw.SITE}{COURSE}/resources/lec01/"
EXAM = f"{ocw.SITE}{COURSE}/resources/final/"


def fake_ocw(monkeypatch, tmp_path, contentfiles: list[dict]):
    make_pdf(tmp_path / "one.pdf", 1)
    pdf = (tmp_path / "one.pdf").read_bytes()
    search = {"results": [{"id": 5284, "title": "Introduction to Convex Optimization", "url": f"{ocw.SITE}{COURSE}/",
                           "description": "<p>Convex sets &amp; functions.</p>", "course_feature": ["Exams", "Lecture Notes"],
                           "course": {"course_numbers": [{"value": "6.079"}]}, "runs": [{"semester": "Fall", "year": 2009}],
                           "image": None}]}
    pages = {LEC: f'<a href="{COURSE}/{"a" * 32}_lec01.pdf">Download</a>', EXAM: f'<a href="{COURSE}/{"b" * 32}_final.pdf">x</a>'}

    def fetch(url: str) -> bytes:
        if "learning_resources_search" in url:
            return json.dumps(search).encode()
        if "contentfiles" in url:
            return json.dumps({"results": contentfiles, "next": None}).encode()
        if url in pages:
            return pages[url].encode()
        if url.endswith(".pdf"):
            return pdf
        raise OSError(url)
    monkeypatch.setattr(ocw, "fetch", fetch)


FILES = [
    {"content_type": "pdf", "file_extension": ".pdf", "title": "lec01.pdf", "url": LEC, "content_feature_type": ["Lecture Notes"]},
    {"content_type": "pdf", "file_extension": ".pdf", "title": "final", "url": EXAM, "content_feature_type": ["Exams"]},
    {"content_type": "file", "file_extension": ".m", "title": "data.m", "url": LEC, "content_feature_type": ["Exams"]},  # MATLAB: left out
    {"content_type": "pdf", "file_extension": ".pdf", "title": "../evil.pdf", "url": LEC, "content_feature_type": ["Exams"]},  # path stripped, then no link: skipped
    {"content_type": "page", "file_extension": None, "title": "Syllabus", "url": LEC, "content_feature_type": []},
]


def test_search_lists_ocw_courses(client, monkeypatch, tmp_path):
    fake_ocw(monkeypatch, tmp_path, FILES)
    [c] = client.get("/api/ocw/search", params={"q": "convex"}).json()
    assert c["id"] == 5284 and c["number"] == "6.079" and c["year"] == 2009 and c["description"] == "Convex sets & functions."


def test_an_ocw_course_is_downloaded_by_kind_and_imported(client, monkeypatch, tmp_path):
    fake_ocw(monkeypatch, tmp_path, FILES)
    r = client.post("/api/courses/ocw", json={"resource_id": 5284, "name": "Convex (MIT)"})
    assert r.status_code == 201, r.text
    names = sorted(s["name"] for s in client.get(f"/api/courses/{r.json()['id']}/found").json()["sources"])
    assert names == ["Exams/final.pdf", "Lecture Notes/lec01.pdf"]


def test_a_course_with_nothing_to_download_is_refused(client, monkeypatch, tmp_path):
    fake_ocw(monkeypatch, tmp_path, FILES[2:])
    r = client.post("/api/courses/ocw", json={"resource_id": 5284, "name": "Videos only"})
    assert r.status_code == 422 and client.get("/api/courses").json() == []


def test_fetch_talks_only_to_ocw():
    import pytest
    with pytest.raises(ValueError):
        ocw.fetch("https://example.com/x.pdf")
