"""Refresh Sources (#21): after files in the Course folder changed, redo only what changed.
Unchanged files are skipped by content hash; a changed PDF's pages are compared one by one, and only pages whose text
differs after reading count as changed. Only Sections citing a changed or removed page are regenerated."""
import unicodedata
import hashlib
import json
import shutil
from pathlib import Path

import pypdfium2 as pdfium

from . import chapters as chm
from . import cram, exams, ingest, search
from .context import Ctx
from .pi_step import record_owner_action


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _folder_files(ctx: Ctx, cid: int) -> dict[str, Path]:
    folder = Path(ctx.db.execute("SELECT folder FROM courses WHERE id=?", (cid,)).fetchone()["folder"])
    if not folder.is_dir():
        return {}
    return {unicodedata.normalize("NFC", p.relative_to(folder).as_posix()): p for p in sorted(folder.rglob("*"))
            if p.is_file() and ingest.is_material(p.relative_to(folder))}


def _known(ctx: Ctx, cid: int) -> dict:
    """The folder's Sources (uploaded notes live only in the Course, so they are never "removed")."""
    return {r["name"]: r for r in ctx.db.execute("SELECT * FROM sources WHERE course_id=? AND role IS NOT 'personal notes'", (cid,))}


def _stored_hash(row) -> str | None:
    """The hash of the Source as last imported: stored, or (Courses from before #21) taken from the imported copy."""
    if row["sha256"]:
        return row["sha256"]
    return sha256(Path(row["path"])) if Path(row["path"]).exists() else None


def _edited_sections(ctx: Ctx, cid: int, section_ids: set[int]) -> dict[int, list[dict]]:
    """Sections with Blocks the owner edited by hand, with those edits."""
    out: dict[int, list[dict]] = {}
    for t in ctx.db.execute("SELECT inputs FROM traces WHERE course_id=? AND owner_action='edited' ORDER BY id", (cid,)):
        edit = json.loads(t["inputs"] or "{}")
        row = ctx.db.execute("SELECT section_id FROM blocks WHERE id=?", (edit.get("block"),)).fetchone()
        if row and row["section_id"] in section_ids:
            out.setdefault(row["section_id"], []).append(edit.get("data"))
    return out


def _citing(ctx: Ctx, cid: int, names: set[str]) -> list:
    """Sections whose pages come from any of these Sources."""
    return [s for s in ctx.db.execute("SELECT s.*, c.title chapter FROM sections s JOIN chapters c ON c.id=s.chapter_id "
                                      "WHERE c.course_id=? ORDER BY c.position, s.position", (cid,)).fetchall()
            if {p["source"] for p in json.loads(s["pages"])} & names]


def diff(ctx: Ctx, cid: int) -> dict:
    """What changed in the folder, before anything is re-read or regenerated."""
    files, known = _folder_files(ctx, cid), _known(ctx, cid)
    new = [n for n in files if n not in known]
    changed = [n for n, row in known.items() if n in files and not row["excluded"] and _stored_hash(row) != sha256(files[n])]
    removed = [n for n, row in known.items() if n not in files and not row["excluded"]]
    touched = _citing(ctx, cid, set(changed) | set(removed))
    edited = _edited_sections(ctx, cid, {s["id"] for s in touched})
    return {"new": new, "changed": changed, "removed": removed,
            "sections": [{"id": s["id"], "title": s["title"], "chapter": s["chapter"]} for s in touched],
            "edited_sections": [{"id": s["id"], "title": s["title"], "chapter": s["chapter"]} for s in touched if s["id"] in edited]}


def _page_fingerprints(path: Path) -> list[str]:
    """One hash per page of a PDF: its text layer and its rendering, so identical pages are skipped without the model."""
    out = []
    pdf = pdfium.PdfDocument(str(path))
    try:
        for page in pdf:
            text = page.get_textpage().get_text_range()
            pixels = page.render(scale=0.5).to_pil().tobytes()
            out.append(hashlib.sha256(text.encode() + b"\0" + pixels).hexdigest())
    finally:
        pdf.close()
    return out


def apply(ctx: Ctx, cid: int, edited: str = "keep") -> dict:
    """Runs the Refresh. `edited` says what to do with owner-edited Sections: keep, regenerate, or notes (regenerate with the
    owner's edits given to the model as notes)."""
    db = ctx.db
    files, known = _folder_files(ctx, cid), _known(ctx, cid)
    d = diff(ctx, cid)
    dest = ctx.course_dir(cid) / "sources"
    changed_pages: set[tuple[str, int]] = set()
    rebuilt_exams = []

    for name in d["removed"]:
        db.execute("UPDATE sources SET excluded=1 WHERE id=?", (known[name]["id"],))

    old_texts: dict[str, dict[int, str]] = {}
    for name in d["changed"]:
        row, new_file = known[name], files[name]
        old_texts[name] = {r["n"]: r["text"] or "" for r in db.execute("SELECT n, text FROM pages WHERE source_id=?", (row["id"],))}
        stale = set()
        if row["pages"]:  # a PDF: drop only the pages that look different, so read_pages re-reads just those
            before = _page_fingerprints(Path(row["path"])) if Path(row["path"]).exists() else []
            after = _page_fingerprints(new_file)
            stale = {n for n in range(1, max(len(before), len(after)) + 1)
                     if n > len(before) or n > len(after) or before[n - 1] != after[n - 1]}
            for n in stale:
                db.execute("DELETE FROM pages WHERE source_id=? AND n=?", (row["id"], n))
            db.execute("UPDATE sources SET pages=? WHERE id=?", (len(after), row["id"]))
        shutil.copy2(new_file, row["path"])
        db.execute("UPDATE sources SET sha256=? WHERE id=?", (sha256(new_file), row["id"]))
        if row["role"] == "past exam" or row["role"] == "correction":
            exam_src = row["id"] if row["role"] == "past exam" else row["paired_with"]
            exam = db.execute("SELECT id FROM exams WHERE source_id=?", (exam_src,)).fetchone() if exam_src else None
            if exam and not db.execute("SELECT 1 FROM copies WHERE exam_id=?", (exam["id"],)).fetchone():
                db.execute("DELETE FROM exams WHERE id=?", (exam["id"],))  # rebuilt below; an Exam with graded copies is kept
                rebuilt_exams.append(name)

    for name in d["new"]:
        f = files[name]
        (dest / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest / name)
        pages = len(pdfium.PdfDocument(str(f))) if f.suffix.lower() == ".pdf" else 0
        role = "data" if f.suffix.lower() in ingest.DATA_SUFFIXES else None
        db.execute("INSERT INTO sources (course_id, name, path, pages, role, sha256) VALUES (?,?,?,?,?,?)",
                   (cid, name, str(dest / name), pages, role, sha256(f)))

    ingest.read_pages(ctx, cid)  # resumable: reads only the pages dropped above and those of new Sources
    if d["new"]:
        ingest.propose_roles(ctx, cid)  # only Sources without a Role; the owner can change them in the found view
    for name in d["changed"]:
        sid = known[name]["id"]
        new_texts = {r["n"]: r["text"] or "" for r in db.execute("SELECT n, text FROM pages WHERE source_id=?", (sid,))}
        changed_pages |= {(name, n) for n in set(old_texts[name]) | set(new_texts) if old_texts[name].get(n) != new_texts.get(n)}
    search.index_course(db, ctx.search, cid)

    if rebuilt_exams or any(db.execute("SELECT role FROM sources WHERE course_id=? AND name=?", (cid, n)).fetchone()["role"]
                            in ("past exam", "correction") for n in d["new"]):
        exams.rebuild_past_papers(ctx, cid)
        cram.classify_questions(ctx, cid, force=True)

    removed = set(d["removed"])
    stale_sections = [s for s in _citing(ctx, cid, {n for n, _ in changed_pages} | removed)
                      if {(p["source"], p["page"]) for p in json.loads(s["pages"])} & changed_pages
                      or {p["source"] for p in json.loads(s["pages"])} & removed]
    edits = _edited_sections(ctx, cid, {s["id"] for s in stale_sections})
    regenerate = [s for s in stale_sections if s["id"] not in edits or edited != "keep"]
    regen_ids = {s["id"] for s in regenerate}
    notes = {sid: json.dumps(e, ensure_ascii=False) for sid, e in edits.items()} if edited == "notes" else {}

    for s in stale_sections:  # a removed Source's Blocks are flagged until regenerated or fixed
        if {p["source"] for p in json.loads(s["pages"])} & removed and s["id"] not in regen_ids:
            for b in db.execute("SELECT id, flags FROM blocks WHERE section_id=?", (s["id"],)).fetchall():
                flags = json.loads(b["flags"]) + [f"source removed: {', '.join(sorted(removed))}"]
                db.execute("UPDATE blocks SET status='flagged', flags=? WHERE id=?", (json.dumps(flags, ensure_ascii=False), b["id"]))
            db.execute("UPDATE chapters SET status='in_review' WHERE id=?", (s["chapter_id"],))
    for s in regenerate:
        db.execute("UPDATE sections SET generation_status='pending' WHERE id=?", (s["id"],))
    for chid in dict.fromkeys(s["chapter_id"] for s in regenerate):
        chm.generate_chapter(ctx, cid, chid, notes)  # only the pending Sections; Blocks keep their ids by position
    refresh_cards(ctx, [s["id"] for s in regenerate])

    result = {**d, "changed_pages": sorted([list(p) for p in changed_pages]), "regenerated": [s["id"] for s in regenerate],
              "kept": [s["id"] for s in stale_sections if s["id"] not in regen_ids], "rebuilt_exams": rebuilt_exams}
    record_owner_action(db, cid, "refresh", {"edited": edited, **{k: result[k] for k in ("new", "changed", "removed", "regenerated")}}, "refreshed")
    return result


def refresh_cards(ctx: Ctx, section_ids: list[int]) -> None:
    """Cards of rewritten Blocks get the new faces and keep their review history; Cards for parts that are gone are dropped."""
    from .learner import card_faces
    db = ctx.db
    for sid in section_ids:
        for b in db.execute("SELECT * FROM blocks WHERE section_id=?", (sid,)).fetchall():
            try:
                faces = {part: (front, back) for part, front, back in card_faces(chm.block_json(b))}
            except (KeyError, TypeError, IndexError):
                continue  # a flagged Block with broken data: its Cards wait for the fix
            for card in db.execute("SELECT id, part FROM cards WHERE block_id=?", (b["id"],)).fetchall():
                if card["part"] in faces:
                    db.execute("UPDATE cards SET front=?, back=? WHERE id=?", (*faces[card["part"]], card["id"]))
                else:
                    db.execute("DELETE FROM cards WHERE id=?", (card["id"],))
