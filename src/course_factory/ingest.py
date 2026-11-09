"""Import, page reading and Role proposals: everything before the found Approval Gate."""

import shutil
from pathlib import Path

import pypdfium2 as pdfium
from pydantic import BaseModel

from .context import Ctx, Role
from .pi_step import StepFailed, run_pi_step

DATA_SUFFIXES = {".csv", ".txt", ".json", ".xlsx", ".npy", ".mat", ".dat"}


class PageReading(BaseModel):
    text: str
    readable: bool


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
    for f in sorted(p for p in folder.rglob("*") if p.is_file() and not p.name.startswith(".")):
        rel = f.relative_to(folder)
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest / rel)
        pages = len(pdfium.PdfDocument(str(f))) if f.suffix.lower() == ".pdf" else 0
        role = "data" if f.suffix.lower() in DATA_SUFFIXES else None
        # data files have no pages to read, so their Role is known without the model
        db.execute("INSERT OR IGNORE INTO sources (course_id, name, path, pages, role) VALUES (?,?,?,?,?)",
                   (cid, rel.as_posix(), str(dest / rel), pages, role))

def read_pages(ctx: Ctx, cid: int) -> None:
    db, backend = ctx.db, ctx.backend
    img_dir = ctx.course_dir(cid) / "pages"
    img_dir.mkdir(parents=True, exist_ok=True)
    # shortcut: notebooks are not transcribed yet; they get read when Labs are built.
    for src in db.execute("SELECT * FROM sources WHERE course_id=? AND pages>0", (cid,)).fetchall():
        pdf = pdfium.PdfDocument(src["path"])
        for n in range(1, src["pages"] + 1):
            done = db.execute("SELECT 1 FROM pages WHERE source_id=? AND n=? AND text IS NOT NULL", (src["id"], n)).fetchone()
            if done:  # resumable: a restart mid-read skips pages already read
                continue
            img = img_dir / f"{src['id']}-{n}.png"
            pdf[n - 1].render(scale=2).to_pil().save(img)
            try:
                reading = run_pi_step(db, backend, "read_page", {"source": src["name"], "page": str(n)}, PageReading,
                                      img_dir, (img,), course_id=cid)
            except StepFailed:  # one bad page must not stop the Run: the found gate lists it as unreadable
                reading = PageReading(text="", readable=False)
            db.execute("INSERT OR REPLACE INTO pages (source_id, n, image, text, readable) VALUES (?,?,?,?,?)",
                       (src["id"], n, str(img), reading.text, int(reading.readable)))

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
