"""Proposing the outline (Chapters, Sections) and the owner's edits at the outline Approval Gate."""

import json

from pydantic import BaseModel, Field

from .context import Ctx, Priority
from .pi_step import run_pi_step

PAGE_HEAD_CHARS = 500


class PageRef(BaseModel):
    source: str
    page: int


class SectionPlan(BaseModel):
    title: str
    pages: list[PageRef] = []


class ChapterPlan(BaseModel):
    title: str
    sections: list[SectionPlan]


class OutlinePlan(BaseModel):
    chapters: list[ChapterPlan] = Field(min_length=1)


def propose_outline(ctx: Ctx, cid: int) -> None:
    db = ctx.db
    goal = db.execute("SELECT goal FROM courses WHERE id=?", (cid,)).fetchone()["goal"]
    sources = []
    for s in db.execute("SELECT id, name, role, pages FROM sources WHERE course_id=? AND excluded=0 AND pages>0 ORDER BY name", (cid,)):
        heads = [{"page": p["n"], "head": (p["text"] or "")[:PAGE_HEAD_CHARS]}
                 for p in db.execute("SELECT n, text FROM pages WHERE source_id=? AND readable=1 ORDER BY n", (s["id"],))]
        sources.append({"name": s["name"], "role": s["role"], "pages": heads})
    plan = run_pi_step(db, ctx.backend, "propose_outline", {"goal": goal, "sources": sources}, OutlinePlan,
                       ctx.course_dir(cid), course_id=cid)
    save_outline(ctx, cid, plan)


def valid_refs(ctx: Ctx, cid: int, refs: list[PageRef]) -> list[dict]:
    """Keeps only references to real pages of non-excluded Sources of this Course."""
    pages = {r["name"]: r["pages"] for r in ctx.db.execute(
        "SELECT name, pages FROM sources WHERE course_id=? AND excluded=0", (cid,))}
    return [r.model_dump() for r in refs if 1 <= r.page <= pages.get(r.source, 0)]


def save_outline(ctx: Ctx, cid: int, plan: OutlinePlan, priorities: list[Priority] | None = None) -> None:
    db = ctx.db
    db.execute("DELETE FROM sections WHERE chapter_id IN (SELECT id FROM chapters WHERE course_id=?)", (cid,))
    db.execute("DELETE FROM chapters WHERE course_id=?", (cid,))
    for i, ch in enumerate(plan.chapters):
        prio = priorities[i] if priorities else "normal"
        chid = db.execute("INSERT INTO chapters (course_id, position, title, priority) VALUES (?,?,?,?)",
                          (cid, i, ch.title, prio)).lastrowid
        for j, sec in enumerate(ch.sections):
            db.execute("INSERT INTO sections (chapter_id, position, title, pages) VALUES (?,?,?,?)",
                       (chid, j, sec.title, json.dumps(valid_refs(ctx, cid, sec.pages))))


def load_outline(ctx: Ctx, cid: int) -> list[dict]:
    out = []
    for ch in ctx.db.execute("SELECT * FROM chapters WHERE course_id=? ORDER BY position", (cid,)):
        secs = [{"id": s["id"], "title": s["title"], "pages": json.loads(s["pages"])}
                for s in ctx.db.execute("SELECT * FROM sections WHERE chapter_id=? ORDER BY position", (ch["id"],))]
        out.append({"id": ch["id"], "title": ch["title"], "priority": ch["priority"], "exam_hits": ch["exam_hits"],
                    "exam_weight": ch["exam_weight"], "status": ch["status"], "sections": secs})
    return out
