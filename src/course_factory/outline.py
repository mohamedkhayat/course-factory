"""Proposing the outline (Chapters, Sections) and the owner's edits at the outline Approval Gate."""

import json
import re

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .context import Ctx, Priority, Profile
from .pi_step import run_pi_step

PAGE_HEAD_CHARS = 500
PRACTICE_ONLY = re.compile(r"exerci|r[ée]vision|annales|entra[iî]nement|\bTD\b|\bTP\b|bilan|synth[eè]se|practice|review", re.I)
MIN_PAGE_CHARS = 300  # shorter uncited pages are title pages and section dividers (courses 2-6)


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
            if empty := [s.title for ch in self.chapters for s in ch.sections if not s.teaches and not PRACTICE_ONLY.search(s.title)]:
                raise ValueError(f"these Sections list no Concepts in \"teaches\": {json.dumps(empty, ensure_ascii=False)}. "
                                 "List what each one teaches; only an exercises or revision Section may teach none.")
            return self

    plan = run_pi_step(db, ctx.backend, "propose_outline", {"goal": goal, "sources": sources}, CoveringPlan,
                       ctx.course_dir(cid), course_id=cid)
    db.execute("UPDATE courses SET subject=? WHERE id=?", (plan.kind, cid))
    attach_uncited(db, cid, plan)
    save_outline(ctx, cid, plan)


def attach_uncited(db, cid: int, plan: OutlinePlan) -> None:
    """A course-notes page with content that no Section cites (the model skipped it) goes to the Section citing the
    nearest earlier page of the same Source, else the nearest later one: no part of the notes is silently dropped."""
    cited = [(s, p) for ch in plan.chapters for s in ch.sections for p in s.pages]
    have = {(p.source, p.page) for _, p in cited}
    for r in db.execute("SELECT s.name, p.n, p.text FROM pages p JOIN sources s ON s.id=p.source_id WHERE s.course_id=? AND "
                        "s.excluded=0 AND s.role='course notes' AND p.readable=1 ORDER BY s.name, p.n", (cid,)):
        text = r["text"] or ""
        if (r["name"], r["n"]) in have or len(text.strip()) < MIN_PAGE_CHARS or "hors programme" in text.lower():
            continue  # a title page, a blank, or what the professor marked out of scope
        same = [(p.page, s) for s, p in cited if p.source == r["name"]]
        before, after = [x for x in same if x[0] < r["n"]], [x for x in same if x[0] > r["n"]]
        if near := (max(before, key=lambda x: x[0]) if before else min(after, key=lambda x: x[0]) if after else None):
            near[1].pages.append(PageRef(source=r["name"], page=r["n"]))


def backfill_concepts(ctx: Ctx, cid: int) -> None:
    """For a Course outlined before Concepts existed (#22): names each Section's Concepts without touching the outline, its
    pages or its Blocks, and drops the Chapter plans so the next regeneration of each Chapter plans it with them."""
    db, current = ctx.db, load_outline(ctx, cid)
    titles = [[s["title"] for s in ch["sections"]] for ch in current]

    class SameOutline(OutlinePlan):
        @model_validator(mode="after")
        def same_titles(self):
            if [[s.title for s in ch.sections] for ch in self.chapters] != titles:
                raise ValueError(f"keep the outline: these Section titles per Chapter, in this order: {json.dumps(titles, ensure_ascii=False)}")
            return self

    pages = {(r["name"], r["n"]): (r["text"] or "")[:300] for r in db.execute(
        "SELECT s.name, p.n, p.text FROM pages p JOIN sources s ON s.id=p.source_id WHERE s.course_id=? AND p.readable=1", (cid,))}
    outline = [{"title": ch["title"], "sections": [{"title": s["title"], "pages": [pages.get((p["source"], p["page"]), "")
                                                                                    for p in s["pages"]]} for s in ch["sections"]]}
               for ch in current]
    goal = db.execute("SELECT goal FROM courses WHERE id=?", (cid,)).fetchone()["goal"]
    plan = run_pi_step(db, ctx.backend, "name_concepts", {"goal": goal, "outline": outline}, SameOutline, ctx.course_dir(cid), course_id=cid)
    taught: set[str] = set()
    for ch, named in zip(current, plan.chapters):
        for s, sec in zip(ch["sections"], named.sections):
            taught |= set(teaches := [c for c in dict.fromkeys(t.strip() for t in sec.teaches) if c and c not in taught])
            db.execute("UPDATE sections SET teaches=? WHERE id=?", (json.dumps(teaches, ensure_ascii=False), s["id"]))
    db.execute("UPDATE chapters SET plan=NULL WHERE course_id=?", (cid,))


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
