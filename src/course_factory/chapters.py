"""Generating Chapters Block by Block, checking and repairing Blocks, and the owner's Chapter review."""

import json

from pydantic import BaseModel, Field

from .catalogue import describe
from .checks import check_blocks
from .context import Ctx
from .pi_step import StepFailed, run_pi_step

REPAIRS = 3
PRIORITY_ORDER = {"focus": 0, "normal": 1, "light": 2}
LANGUAGE_RULE = ("Keep source statements, definitions and exercise wording in the source language (usually French), "
                 "with the professor's notation. Write your own explanations, intuitions and hints in English.")


class SectionDraft(BaseModel):
    blocks: list[dict] = Field(min_length=1)  # checked one by one so a bad Block doesn't sink the Section


class RepairedBlock(BaseModel):
    block: dict


class Grounding(BaseModel):
    grounded: bool
    reason: str = ""


def chapter_order(ctx: Ctx, cid: int) -> list[int]:
    """Chapters to generate, most useful first. Cram: Priority then Exam Weight; Deep: course order. Skip is never generated."""
    goal = ctx.db.execute("SELECT goal FROM courses WHERE id=?", (cid,)).fetchone()["goal"]
    rows = [r for r in ctx.db.execute("SELECT * FROM chapters WHERE course_id=? ORDER BY position", (cid,)) if r["priority"] != "skip"]
    if goal == "cram":
        rows.sort(key=lambda r: (PRIORITY_ORDER[r["priority"]], -r["exam_weight"], r["position"]))
    return [r["id"] for r in rows]


def generate_chapters(ctx: Ctx, cid: int) -> None:
    for chid in chapter_order(ctx, cid):
        if ctx.db.execute("SELECT status FROM chapters WHERE id=?", (chid,)).fetchone()["status"] in ("in_review", "published"):
            continue  # resuming: already done
        generate_chapter(ctx, cid, chid)


def source_pages(ctx: Ctx, cid: int) -> dict[str, int]:
    return {r["name"]: r["pages"] for r in ctx.db.execute("SELECT name, pages FROM sources WHERE course_id=? AND excluded=0", (cid,))}


def page_texts(ctx: Ctx, cid: int, refs: list[dict]) -> list[dict]:
    out = []
    for r in refs:
        row = ctx.db.execute("SELECT p.text FROM pages p JOIN sources s ON s.id=p.source_id WHERE s.course_id=? AND s.name=? AND p.n=?",
                             (cid, r["source"], r["page"])).fetchone()
        out.append({"source": r["source"], "page": r["page"], "text": row["text"] if row else ""})
    return out


def generate_chapter(ctx: Ctx, cid: int, chid: int) -> None:
    db = ctx.db
    db.execute("UPDATE chapters SET status='generating' WHERE id=?", (chid,))
    chapter = db.execute("SELECT * FROM chapters WHERE id=?", (chid,)).fetchone()
    goal = db.execute("SELECT goal FROM courses WHERE id=?", (cid,)).fetchone()["goal"]
    for sec in db.execute("SELECT * FROM sections WHERE chapter_id=? ORDER BY position", (chid,)).fetchall():
        db.execute("DELETE FROM blocks WHERE section_id=?", (sec["id"],))  # a resumed Chapter starts its Sections over
        pages = page_texts(ctx, cid, json.loads(sec["pages"]))
        draft = run_pi_step(db, ctx.backend, "write_section", {
            "goal": goal, "priority": chapter["priority"], "chapter": chapter["title"], "section": sec["title"],
            "pages": pages, "catalogue": describe(), "language": LANGUAGE_RULE}, SectionDraft, ctx.course_dir(cid), course_id=cid)
        for pos, raw in enumerate(draft.blocks):
            block, flags = checked_block(ctx, cid, raw, pages)
            db.execute("INSERT INTO blocks (section_id, position, component, data, citations, origin, status, flags) VALUES (?,?,?,?,?,?,?,?)",
                       (sec["id"], pos, block["component"], json.dumps(block["data"], ensure_ascii=False),
                        json.dumps(block["citations"], ensure_ascii=False), block["origin"],
                        "flagged" if flags["errors"] else "ok", json.dumps(flags["errors"] + flags["warnings"], ensure_ascii=False)))
    db.execute("UPDATE chapters SET status='in_review' WHERE id=?", (chid,))


def checked_block(ctx: Ctx, cid: int, raw: dict, pages: list[dict], note: str | None = None) -> tuple[dict, dict]:
    """Checks a Block, asks the model to repair it up to REPAIRS times, then judges grounding.
    Returns the last Block and {"errors": [...], "warnings": [...]}; errors mean the Block is flagged."""
    sources = source_pages(ctx, cid)
    (block,), (errors,) = check_blocks([raw], sources)
    if note:
        errors = [f"owner note: {note}"]
    for _ in range(REPAIRS):
        if not errors:
            break
        try:
            fixed = run_pi_step(ctx.db, ctx.backend, "repair_block", {"block": block, "errors": errors, "pages": pages,
                                "catalogue": describe(), "language": LANGUAGE_RULE}, RepairedBlock, ctx.course_dir(cid), course_id=cid)
        except StepFailed as e:
            errors = errors + [str(e)]
            break
        (block,), (errors,) = check_blocks([fixed.block], sources)
    warnings = []
    if not errors and block["origin"] == "from_source":
        cited = page_texts(ctx, cid, block["citations"])
        try:
            g = run_pi_step(ctx.db, ctx.backend, "judge_grounding", {"block": block, "pages": cited}, Grounding,
                            ctx.course_dir(cid), course_id=cid)
            if not g.grounded:
                warnings.append(f"grounding: {g.reason or 'not supported by its Citations'}")
        except StepFailed as e:
            warnings.append(f"grounding judge failed: {e}")
    return block, {"errors": errors, "warnings": warnings}


def block_json(row) -> dict:
    return {"id": row["id"], "position": row["position"], "component": row["component"], "data": json.loads(row["data"]),
            "citations": json.loads(row["citations"]), "origin": row["origin"], "status": row["status"], "flags": json.loads(row["flags"])}


def load_chapter(ctx: Ctx, chid: int) -> dict:
    ch = ctx.db.execute("SELECT * FROM chapters WHERE id=?", (chid,)).fetchone()
    sections = []
    for s in ctx.db.execute("SELECT * FROM sections WHERE chapter_id=? ORDER BY position", (chid,)):
        blocks = [block_json(b) for b in ctx.db.execute("SELECT * FROM blocks WHERE section_id=? ORDER BY position", (s["id"],))]
        sections.append({"id": s["id"], "title": s["title"], "pages": json.loads(s["pages"]), "blocks": blocks})
    return {"id": ch["id"], "title": ch["title"], "priority": ch["priority"], "exam_weight": ch["exam_weight"],
            "status": ch["status"], "sections": sections}
