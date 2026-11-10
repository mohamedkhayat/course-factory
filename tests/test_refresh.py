import json

import pypdfium2 as pdfium

from conftest import make_pdf
from test_chapters import chapters, generate, sections_written


def section_blocks(client, cid):
    out = {}
    for c in chapters(client, cid).values():
        for s in client.get(f"/api/courses/{cid}/chapters/{c['id']}").json()["sections"]:
            out[s["title"]] = s["blocks"]
    return out


def test_refresh_redoes_only_what_changed(client, material, model):
    cid = generate(client, material, model)
    before = section_blocks(client, cid)
    exercise = before["Exercices"][0]
    assert client.put(f"/api/courses/{cid}/blocks/{exercise['id']}", json={"data": exercise["data"]}).status_code == 200  # an owner edit

    assert client.get(f"/api/courses/{cid}/refresh").json() | {"last": None} == {
        "new": [], "changed": [], "removed": [], "sections": [], "edited_sections": [], "last": None}

    pdf = pdfium.PdfDocument.new()  # cours.pdf: page 1 the same, page 2 different
    pdf.new_page(595, 842)
    pdf.new_page(600, 842)
    pdf.save(str(material / "cours.pdf"))
    make_pdf(material / "TD2.pdf", 1)
    (material / "TD1.pdf").unlink()

    diff = client.get(f"/api/courses/{cid}/refresh").json()
    assert (diff["new"], diff["changed"], diff["removed"]) == (["TD2.pdf"], ["cours.pdf"], ["TD1.pdf"])
    assert [s["title"] for s in diff["edited_sections"]] == ["Exercices"]

    read = []
    def read_page(prompt, files):
        read.append(prompt.split("SOURCE: ", 1)[1].split("\n", 1)[0])
        return {"text": "nouvelle version" if "cours.pdf, page 2" in prompt else "même texte", "readable": True}
    model.handlers["read_page"] = read_page
    model.prompts.clear()
    assert client.post(f"/api/courses/{cid}/refresh", json={"edited": "keep"}).status_code == 202

    last = client.get(f"/api/courses/{cid}/refresh").json()["last"]
    assert last["state"] == "done", last
    assert sorted(read) == ["TD2.pdf, page 1", "cours.pdf, page 2"]  # the unchanged page is not re-read
    assert last["result"]["changed_pages"] == [["cours.pdf", 2]]
    assert sections_written(model) == ["Gradient"]  # only the Section citing the changed page

    after = section_blocks(client, cid)
    assert [b["id"] for b in after["Ensembles convexes"]] == [b["id"] for b in before["Ensembles convexes"]]
    assert [b["id"] for b in after["Gradient"]] == [b["id"] for b in before["Gradient"]]  # rewritten in place: Cards keep history
    assert all("source removed: TD1.pdf" in b["flags"] and b["status"] == "flagged" for b in after["Exercices"])  # edited: kept, flagged
    found = {s["name"]: s for s in client.get(f"/api/courses/{cid}/found").json()["sources"]}
    assert found["TD1.pdf"]["excluded"] and "TD2.pdf" in found
    assert chapters(client, cid)["Méthodes de descente"]["status"] == "in_review"

    assert client.get(f"/api/courses/{cid}/refresh").json()["changed"] == []  # nothing left to do


def test_refresh_can_regenerate_edited_sections_with_the_edits_as_notes(client, material, model):
    cid = generate(client, material, model)
    exercise = section_blocks(client, cid)["Exercices"][0]
    edited = {**exercise["data"], "statement": "Énoncé corrigé à la main."} if "statement" in exercise["data"] else exercise["data"]
    assert client.put(f"/api/courses/{cid}/blocks/{exercise['id']}", json={"data": edited}).status_code == 200
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(600, 842)
    pdf.save(str(material / "TD1.pdf"))
    model.handlers["read_page"] = lambda prompt, files: {"text": "TD1 v2", "readable": True}
    model.prompts.clear()
    client.post(f"/api/courses/{cid}/refresh", json={"edited": "notes"})
    prompt = next(p for step, p in model.prompts if step == "write_section")
    notes = prompt.split("Owner notes from an earlier version of this Section", 1)[1].split("\n", 1)[0]
    assert json.dumps(edited, ensure_ascii=False)[1:40] in notes  # the owner's edit, for the model to keep
