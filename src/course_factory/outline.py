"""Proposing the outline (Chapters, Sections) and the owner's edits at the outline Approval Gate."""

import json

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .context import Ctx, Priority, Profile
from .pi_step import run_pi_step

PAGE_HEAD_CHARS = 500


class PageRef(BaseModel):
    source: str
    page: int


class SectionPlan(BaseModel):
    title: str
    pages: list[PageRef] = []
    teaches: list[str] = []  # the Concepts this Section teaches, each taught in one Section only (#22)


class ChapterPlan(BaseModel):
    title: str
    sections: list[SectionPlan]
    profile: Profile | None = None  # None: from the Course's subject


class OutlinePlan(BaseModel):
    kind: Literal["theoretical", "practical", "mixed"] = "mixed"
    chapters: list[ChapterPlan] = Field(min_length=1)


def propose_outline(ctx: Ctx, cid: int) -> None:
    db = ctx.db
    goal = db.execute("SELECT goal FROM courses WHERE id=?", (cid,)).fetchone()["goal"]
    sources = []
    for s in db.execute("SELECT id, name, role, pages FROM sources WHERE course_id=? AND excluded=0 AND pages>0 ORDER BY name", (cid,)):
        heads = [{"page": p["n"], "head": (p["text"] or "")[:PAGE_HEAD_CHARS]}
                 for p in db.execute("SELECT n, text FROM pages WHERE source_id=? AND readable=1 ORDER BY n", (s["id"],))]
        sources.append({"name": s["name"], "role": s["role"], "pages": heads})
    notes = [s["name"] for s in sources if s["role"] == "course notes"]

    class CoveringPlan(OutlinePlan):
        """A local model can stop after the first Chapter with valid JSON; a retry names the notes it left out."""
        @model_validator(mode="after")
        def covers_the_notes(self):
            cited = {p.source for ch in self.chapters for s in ch.sections for p in s.pages}
            if missing := [n for n in notes if n not in cited]:
                raise ValueError(f"outline incomplete: no Section cites the course notes {', '.join(missing)}. "
                                 "Plan the whole course: add the Chapters for these notes, after the ones you have.")
            return self

    plan = run_pi_step(db, ctx.backend, "propose_outline", {"goal": goal, "sources": sources}, CoveringPlan,
                       ctx.course_dir(cid), course_id=cid)
    db.execute("UPDATE courses SET subject=? WHERE id=?", (plan.kind, cid))
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
    taught: set[str] = set()
    for i, ch in enumerate(plan.chapters):
        prio = priorities[i] if priorities else "normal"
        chid = db.execute("INSERT INTO chapters (course_id, position, title, priority, profile) VALUES (?,?,?,?,?)",
                          (cid, i, ch.title, prio, ch.profile)).lastrowid
        for j, sec in enumerate(ch.sections):
            taught |= set(teaches := [c for c in dict.fromkeys(t.strip() for t in sec.teaches) if c and c not in taught])
            db.execute("INSERT INTO sections (chapter_id, position, title, pages, teaches) VALUES (?,?,?,?,?)",
                       (chid, j, sec.title, json.dumps(valid_refs(ctx, cid, sec.pages)), json.dumps(teaches, ensure_ascii=False)))


def load_outline(ctx: Ctx, cid: int) -> list[dict]:
    out = []
    for ch in ctx.db.execute("SELECT * FROM chapters WHERE course_id=? ORDER BY position", (cid,)):
        secs = [{"id": s["id"], "title": s["title"], "pages": json.loads(s["pages"]), "teaches": json.loads(s["teaches"])}
                for s in ctx.db.execute("SELECT * FROM sections WHERE chapter_id=? ORDER BY position", (ch["id"],))]
        out.append({"id": ch["id"], "title": ch["title"], "priority": ch["priority"], "exam_hits": ch["exam_hits"],
                    "exam_weight": ch["exam_weight"], "status": ch["status"], "profile": profile_of(ctx, ch), "sections": secs})
    return out


DEFAULT_PROFILE: dict[str, Profile] = {"theoretical": "problem", "practical": "hands_on", "mixed": "problem"}


def profile_of(ctx: Ctx, chapter) -> Profile:
    """The Chapter's Cram Profile; unset, it follows the Course's subject."""
    if chapter["profile"]:
        return chapter["profile"]
    subject = ctx.db.execute("SELECT subject FROM courses WHERE id=?", (chapter["course_id"],)).fetchone()["subject"]
    return DEFAULT_PROFILE.get(subject, "problem")
