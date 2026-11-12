"""Import, page reading and Role proposals: everything before the found Approval Gate."""

import unicodedata
import hashlib
import json
import shutil
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path

import pypdfium2 as pdfium
from pydantic import BaseModel

from .context import Ctx, Role
from .pi_step import MODEL_LANES, StepFailed, run_pi_step

DATA_SUFFIXES = {".csv", ".txt", ".json", ".xlsx", ".npy", ".mat", ".dat"}
JUNK_DIRS = {"__pycache__", "node_modules", "site-packages", "venv"}  # tooling, not course material


def is_material(rel: Path) -> bool:
    """False for hidden files and anything inside a hidden folder (.venv, .git), a virtualenv or a cache."""
    return not any(part.startswith(".") or part in JUNK_DIRS for part in rel.parts)


class PageFigure(BaseModel):
    """A figure's structure, so a redraw can keep it: what it shows, what contains what, and the labelled links."""
    kind: str = ""
    entities: list[str] = []
    contains: list[list[str]] = []  # [holder, part] pairs; lenient so one odd entry doesn't fail the page
    relations: list[list[str]] = []


class PageReading(BaseModel):
    text: str
    readable: bool
    figures: list[PageFigure] = []


class RoleProposal(BaseModel):
    name: str
    role: Role
    paired_with: str | None = None


class RoleProposals(BaseModel):
    sources: list[RoleProposal]


def import_sources(ctx: Ctx, cid: int) -> None:
    db = ctx.db
    folder = Path(db.execute("SELECT folder FROM courses WHERE id=?", (cid,)).fetchone()["folder"])
    dest = ctx.course_dir(cid) / "sources"
    for f in sorted(p for p in folder.rglob("*") if p.is_file() and is_material(p.relative_to(folder))):
        # composed Unicode: a model cites "é" as one character, and names are matched as plain strings everywhere
        rel = Path(unicodedata.normalize("NFC", f.relative_to(folder).as_posix()))
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest / rel)
        pages = len(pdfium.PdfDocument(str(f))) if f.suffix.lower() == ".pdf" else 0
        role = "data" if f.suffix.lower() in DATA_SUFFIXES else None
        # data files have no pages to read, so their Role is known without the model
        db.execute("INSERT OR IGNORE INTO sources (course_id, name, path, pages, role, sha256) VALUES (?,?,?,?,?,?)",
                   (cid, rel.as_posix(), str(dest / rel), pages, role, hashlib.sha256(f.read_bytes()).hexdigest()))

def read_pages(ctx: Ctx, cid: int) -> None:
    db, backend = ctx.db, ctx.backend
    img_dir = ctx.course_dir(cid) / "pages"
    img_dir.mkdir(parents=True, exist_ok=True)
    failed: list[tuple[int, int]] = []  # pages the model did not answer for in this call
    answered = 0
    # shortcut: notebooks are not transcribed yet; they get read when Labs are built.
    for src in db.execute("SELECT * FROM sources WHERE course_id=? AND pages>0", (cid,)).fetchall():
        pdf = pdfium.PdfDocument(src["path"])
        pending: dict[Future[PageReading], tuple[int, Path]] = {}

        def save_finished():
            nonlocal answered
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                n, img = pending.pop(future)
                reading = future.result()
                if reading is None:
                    failed.append((src["id"], n))
                    reading = PageReading(text="", readable=False)
                else:
                    answered += 1
                db.execute("INSERT OR REPLACE INTO pages (source_id, n, image, text, readable, figures) VALUES (?,?,?,?,?,?)",
                           (src["id"], n, str(img), reading.text, int(reading.readable),
                            json.dumps([f.model_dump() for f in reading.figures], ensure_ascii=False)))

        with ThreadPoolExecutor(max_workers=MODEL_LANES) as pool:
            try:
                for n in range(1, src["pages"] + 1):
                    done = db.execute("SELECT 1 FROM pages WHERE source_id=? AND n=? AND text IS NOT NULL", (src["id"], n)).fetchone()
                    if done:  # resumable: a restart mid-read skips pages already read
                        continue
                    page = pdf[n - 1]
                    img = img_dir / f"{src['id']}-{n}.png"
                    pdf_text = ""
                    try:
                        text_page = page.get_textpage()
                        pdf_text = text_page.get_text_range().strip()[:10000]
                        text_page.close()
                    except Exception:
                        pass  # scanned pages still go through the image transcription path
                    page.render(scale=2).to_pil().save(img)
                    future = pool.submit(_read_page, db, backend, src["name"], n, pdf_text, img_dir, img, cid)
                    pending[future] = (n, img)
                    if len(pending) >= MODEL_LANES:
                        save_finished()
                while pending:
                    save_finished()
            finally:
                pdf.close()
    # One bad page is listed at the found gate; no page answered at all is the model being unreachable (no key, server
    # down), and a Course built on that would be empty: fail the step and leave the pages to be read again on Retry.
    if not answered and len(failed) >= 3:
        db.executemany("DELETE FROM pages WHERE source_id=? AND n=?", failed)
        last = db.execute("SELECT error FROM traces WHERE course_id=? AND step='read_page' AND error IS NOT NULL ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
        raise StepFailed(f"read_pages: the model read none of {len(failed)} pages. {last['error'][:500] if last else ''}")


def _read_page(db, backend, source: str, page: int, pdf_text: str, workdir: Path, image: Path, cid: int) -> PageReading | None:
    try:
        return run_pi_step(db, backend, "read_page", {"source": source, "page": str(page), "pdf_text": pdf_text},
                           PageReading, workdir, (image,), course_id=cid)
    except StepFailed:  # one bad page must not stop the Run: the found gate lists it as unreadable
        return None

def propose_roles(ctx: Ctx, cid: int) -> None:
    db, backend = ctx.db, ctx.backend
    rows = db.execute(
        "SELECT s.id, s.name, s.role, p.text FROM sources s LEFT JOIN pages p ON p.source_id=s.id AND p.n=1 WHERE s.course_id=?",
        (cid,)).fetchall()
    undecided = [{"name": r["name"], "start": (r["text"] or "")[:1500]} for r in rows if r["role"] is None]
    if not undecided:
        return
    ids = {r["name"]: r["id"] for r in rows}
    props = run_pi_step(db, backend, "propose_roles", {"sources": undecided}, RoleProposals,
                        ctx.course_dir(cid), course_id=cid)
    for p in props.sources:
        if p.name in ids:
            db.execute("UPDATE sources SET role=?, paired_with=? WHERE id=?", (p.role, ids.get(p.paired_with or ""), ids[p.name]))
