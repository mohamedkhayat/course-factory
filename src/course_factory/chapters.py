"""Generating Chapters Block by Block, checking and repairing Blocks, and the owner's Chapter review."""

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from pydantic import BaseModel, Field, ValidationError

from . import components
from .catalogue import CATALOGUE, describe
from .checks import check_blocks
from .context import Ctx
from .pi_step import MODEL_LANES, StepFailed, attach_checks, last_trace_id, run_pi_step

REPAIRS = 2  # each repair already retries bad output; deterministic healing catches the rest
PRIORITY_ORDER = {"focus": 0, "normal": 1, "light": 2}
LANGUAGE_RULE = ("Keep source statements, definitions and exercise wording in the source language (usually French), "
                 "with the professor's notation. Write your own explanations, intuitions and hints in English.")


class SectionDraft(BaseModel):
    blocks: list[dict] = Field(min_length=1)  # checked one by one so a bad Block doesn't sink the Section
    proposals: list[dict] = []  # new Components, checked one by one too


def catalogue_text(ctx: Ctx) -> str:
    return "\n".join(x for x in (describe(), components.describe_custom(ctx.db)) if x)


def fallback_markdown(data) -> str:
    """How a Block shows when its Component isn't live: its fields as Markdown."""
    if isinstance(data, dict):
        return "\n\n".join(f"**{k.replace('_', ' ')}**\n\n{fallback_markdown(v)}" for k, v in data.items())
    if isinstance(data, list):
        return "\n".join(f"- {fallback_markdown(v)}" for v in data)
    return str(data)


class RepairedBlock(BaseModel):
    block: dict


class GroundingResult(BaseModel):
    block: int
    grounded: bool
    contradicts: bool = False  # ungrounded because it disagrees with its pages, not just goes beyond them
    reason: str = ""


class GroundingBatch(BaseModel):
    results: list[GroundingResult] = []
    # Accept the original single-result shape for older Harnesses and lightweight backends.
    grounded: bool | None = None
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


def awaiting_review(ctx: Ctx, cid: int) -> int:
    return ctx.db.execute("SELECT COUNT(*) FROM chapters WHERE course_id=? AND status='in_review'", (cid,)).fetchone()[0]


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
    goal, subject = db.execute("SELECT goal, subject FROM courses WHERE id=?", (cid,)).fetchone()
    sections = db.execute("SELECT * FROM sections WHERE chapter_id=? ORDER BY position", (chid,)).fetchall()
    pending_sections = []
    for sec in sections:
        if sec["generation_status"] == "complete":
            continue
        db.execute("UPDATE sections SET generation_status='generating' WHERE id=?", (sec["id"],))
        db.execute("DELETE FROM blocks WHERE section_id=?", (sec["id"],))
        pending_sections.append(sec)
    if not pending_sections:
        db.execute("UPDATE chapters SET status='in_review' WHERE id=?", (chid,))
        return
    catalogue = catalogue_text(ctx)

    def write(sec):
        pages = page_texts(ctx, cid, json.loads(sec["pages"]))
        draft = run_pi_step(db, ctx.backend, "write_section", {
            "goal": goal, "priority": chapter["priority"], "chapter": chapter["title"], "section": sec["title"],
            "pages": pages, "catalogue": catalogue, "language": LANGUAGE_RULE, "subject": subject},
            SectionDraft, ctx.course_dir(cid), course_id=cid)
        return sec, pages, draft, last_trace_id()

    with ThreadPoolExecutor(max_workers=min(MODEL_LANES, len(pending_sections))) as pool:
        drafts = list(pool.map(write, pending_sections))

    # Register all proposed Components before checking any sibling Section's Blocks.
    for _, _, draft, _ in drafts:
        for raw in draft.proposals:
            try:
                components.propose(ctx, cid, components.ComponentProposal.model_validate(raw))
            except ValidationError:
                pass  # a malformed proposal is dropped; Blocks that use it get flagged

    def check_section(item):
        sec, pages, draft, _ = item
        stage = lambda s: db.execute("UPDATE sections SET generation_status=? WHERE id=?", (s, sec["id"]))  # noqa: E731
        stage("checking")
        return checked_blocks(ctx, cid, draft.blocks, pages, on_stage=stage)

    def save_section(item, result):
        sec, _, _, section_trace = item
        blocks, checks = result
        for pos, (block, flags) in enumerate(zip(blocks, checks)):
            db.execute("INSERT INTO blocks (section_id, position, component, data, citations, origin, status, flags) VALUES (?,?,?,?,?,?,?,?)",
                       (sec["id"], pos, block["component"], json.dumps(block["data"], ensure_ascii=False),
                        json.dumps(block["citations"], ensure_ascii=False), block["origin"],
                        "flagged" if flags["errors"] else "ok", json.dumps(flags["errors"] + flags["warnings"], ensure_ascii=False)))
        attach_checks(db, section_trace, [{"block": i, **flags} for i, flags in enumerate(checks)])
        db.execute("UPDATE sections SET generation_status='complete' WHERE id=?", (sec["id"],))

    with ThreadPoolExecutor(max_workers=min(MODEL_LANES, len(drafts) or 1)) as pool:
        futures = {pool.submit(check_section, item): item for item in drafts}
        for future in as_completed(futures):
            save_section(futures[future], future.result())
    db.execute("UPDATE chapters SET status='in_review' WHERE id=?", (chid,))


def checked_blocks(ctx: Ctx, cid: int, raw: list[dict], pages: list[dict], notes: dict[int, str] | None = None,
                   on_stage: Callable[[str], object] = lambda stage: None) -> tuple[list[dict], list[dict]]:
    """Check a Section's Blocks together, repair failures in parallel, then judge grounding in one call.
    A Block that goes beyond its pages becomes model-added; one that contradicts them is repaired once and judged again."""
    sources = source_pages(ctx, cid)
    extra = components.schemas(ctx.db)
    blocks, errors = check_blocks(raw, sources, extra)
    for index, note in (notes or {}).items():
        errors[index] = [f"owner note: {note}"]
    warnings: list[list[str]] = [[] for _ in blocks]

    def repair(index):
        try:
            fixed = run_pi_step(ctx.db, ctx.backend, "repair_block", {
                "block": blocks[index], "errors": errors[index], "pages": pages,
                "catalogue": catalogue_text(ctx), "language": LANGUAGE_RULE}, RepairedBlock,
                ctx.course_dir(cid), course_id=cid)
            return index, fixed.block, None, last_trace_id()
        except StepFailed as e:
            return index, None, str(e), last_trace_id()

    def repair_all(rounds: int, only: set[int]):
        failed = set()
        for _ in range(rounds):
            pending = [i for i in only if errors[i] and i not in failed]
            if not pending:
                return
            on_stage("repairing")
            with ThreadPoolExecutor(max_workers=min(MODEL_LANES, len(pending))) as pool:
                repaired = list(pool.map(repair, pending))
            fixed = [(i, b, t) for i, b, failure, t in repaired if not failure and b is not None]
            for i, _, failure, _ in repaired:
                if failure:
                    errors[i].append(failure)
                    failed.add(i)
            if fixed:
                normalized, new_errors = check_blocks([b for _, b, _ in fixed], sources, extra)
                for (i, _, trace_id), block, block_errors in zip(fixed, normalized, new_errors):
                    blocks[i], errors[i] = block, block_errors
                    attach_checks(ctx.db, trace_id, {"errors": block_errors})

    def judge(indices: list[int]) -> list[int]:
        """Judges grounding in one call; returns the Blocks that contradict their pages, with the reason as their error."""
        if indices:
            on_stage("judging")
        page_map = {(p["source"], p["page"]): p for i in indices for p in page_texts(ctx, cid, blocks[i]["citations"])}
        try:
            review = run_pi_step(ctx.db, ctx.backend, "judge_grounding", {
                "blocks": [{"block": i, "content": blocks[i], "citations": blocks[i]["citations"]} for i in indices],
                "pages": list(page_map.values())}, GroundingBatch, ctx.course_dir(cid), course_id=cid)
        except StepFailed as e:
            for i in indices:
                warnings[i].append(f"grounding judge failed: {e}")
            return []
        results = {r.block: r for r in review.results}
        if not results and review.grounded is not None:
            results = {i: GroundingResult(block=i, grounded=review.grounded, reason=review.reason) for i in indices}
        contradicted = []
        for i in indices:
            r = results.get(i)
            if r is None:
                warnings[i].append("grounding judge returned no result for this Block")
            elif r.contradicts:
                errors[i] = [f"contradicts its cited pages: {r.reason}"]
                contradicted.append(i)
            elif not r.grounded:
                blocks[i]["origin"] = "model_added"  # goes beyond its pages: its Citations stay as references
        return contradicted

    repair_all(REPAIRS, set(range(len(blocks))))
    contradicted = judge([i for i, b in enumerate(blocks) if not errors[i] and b["origin"] == "from_source"])
    if contradicted:
        repair_all(1, set(contradicted))
        judge([i for i in contradicted if not errors[i]])

    flags = []
    for block, block_errors, block_warnings in zip(blocks, errors, warnings):
        state_errors, state_warnings = components.status_flags(ctx.db, block["component"]) if not block_errors else ([], [])
        flags.append({"errors": block_errors + state_errors, "warnings": block_warnings + state_warnings})
    return blocks, flags


def checked_block(ctx: Ctx, cid: int, raw: dict, pages: list[dict], note: str | None = None) -> tuple[dict, dict]:
    """Single-Block adapter for edits and regeneration endpoints."""
    blocks, flags = checked_blocks(ctx, cid, [raw], pages, {0: note} if note else None)
    return blocks[0], flags[0]


def block_json(row) -> dict:
    return {"id": row["id"], "position": row["position"], "component": row["component"], "data": json.loads(row["data"]),
            "citations": json.loads(row["citations"]), "origin": row["origin"], "status": row["status"], "flags": json.loads(row["flags"]),
            **({} if row["component"] in CATALOGUE else {"fallback_markdown": fallback_markdown(json.loads(row["data"]))})}


def load_chapter(ctx: Ctx, chid: int) -> dict:
    ch = ctx.db.execute("SELECT * FROM chapters WHERE id=?", (chid,)).fetchone()
    sections = []
    for s in ctx.db.execute("SELECT * FROM sections WHERE chapter_id=? ORDER BY position", (chid,)):
        blocks = [block_json(b) for b in ctx.db.execute("SELECT * FROM blocks WHERE section_id=? ORDER BY position", (s["id"],))]
        sections.append({"id": s["id"], "title": s["title"], "pages": json.loads(s["pages"]), "blocks": blocks})
    return {"id": ch["id"], "title": ch["title"], "priority": ch["priority"], "exam_weight": ch["exam_weight"],
            "status": ch["status"], "sections": sections}
