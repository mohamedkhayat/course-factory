"""Generating Chapters Block by Block, checking and repairing Blocks, and the owner's Chapter review."""

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from pydantic import BaseModel, Field, ValidationError, model_validator

from . import components
from .catalogue import CATALOGUE, describe
from .checks import block_warnings, check_blocks
from .context import Ctx
from .outline import profile_of
from .failures import failure_class
from .progression import flag_progression
from .lesson_plan import plan_chapter, plan_gaps
from .pi_step import MODEL_LANES, StepFailed, attach_checks, last_trace_id, record_owner_action, run_pi_step

REPAIRS = 2  # each repair already retries bad output; deterministic healing catches the rest
PRIORITY_ORDER = {"focus": 0, "normal": 1, "light": 2}
LANGUAGE_RULE = ("Keep source statements, definitions and exercise wording in the source language (usually French), "
                 "with the professor's notation. Write your own explanations, intuitions and hints in English.")


def words(data) -> int:
    if isinstance(data, dict):
        return sum(words(v) for v in data.values())
    if isinstance(data, list):
        return sum(words(v) for v in data)
    return len(data.split()) if isinstance(data, str) else 0


MIN_SECTION_WORDS = 25


class SectionDraft(BaseModel):
    blocks: list[dict] = Field(min_length=1)  # checked one by one so a bad Block doesn't sink the Section
    proposals: list[dict] = []  # new Components, checked one by one too

    @model_validator(mode="after")
    def not_a_placeholder(self):
        """The model sometimes answers a Section with a stub ("test"); a rejection retries it with this feedback."""
        if words([b.get("data") for b in self.blocks if isinstance(b, dict)]) < MIN_SECTION_WORDS:
            raise ValueError(f"the Section is a placeholder (under {MIN_SECTION_WORDS} words): write its real content")
        return self


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
    source_error: bool = False  # the Block is right and the page has a slip (a typo in the correction): keep it, with a note
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


def cram_brief(ctx: Ctx, cid: int, chapter) -> dict:
    """What a Cram Section is written for: the Chapter's Cram Profile and the Question Types that test it, with their
    past Questions, points and Marking schemes."""
    db = ctx.db
    types = []
    for t in db.execute("SELECT DISTINCT t.* FROM question_types t LEFT JOIN questions q ON q.question_type_id=t.id "
                        "WHERE t.course_id=? AND (t.chapter_id=? OR q.chapter_id=?) ORDER BY t.id", (cid, chapter["id"], chapter["id"])):
        qs = db.execute("SELECT q.statement, q.points, q.model_answer, q.scheme FROM questions q JOIN exams e ON e.id=q.exam_id "
                        "WHERE q.question_type_id=? AND (e.kind!='past_paper' OR e.in_scope=1) ORDER BY q.id", (t["id"],)).fetchall()
        if not qs:
            continue  # only another cohort's papers ask it
        types.append({"name": t["name"], "trigger": t["trigger"], "points": sum(q["points"] for q in qs),
                      "past_questions": [{"statement": q["statement"], "points": q["points"], "model_answer": q["model_answer"],
                                          "scheme": json.loads(q["scheme"] or "null")} for q in qs[:3]]})
    return {"profile": profile_of(ctx, chapter), "question_types": types}


def taught_before(ctx: Ctx, cid: int) -> dict[int, list[str]]:
    """Section id -> the Concepts the Sections before it teach, in reading order."""
    out, taught = {}, []
    for s in ctx.db.execute("SELECT s.id, s.teaches FROM sections s JOIN chapters c ON c.id=s.chapter_id WHERE c.course_id=? "
                            "ORDER BY c.position, s.position", (cid,)):
        out[s["id"]] = list(taught)
        taught += json.loads(s["teaches"])
    return out


def generate_chapter(ctx: Ctx, cid: int, chid: int, notes: dict[int, str] | None = None) -> None:
    """Writes the Chapter's unfinished Sections; `notes` (Section id -> text) are owner notes for the model (a Refresh
    passes the owner's earlier edits)."""
    db = ctx.db
    db.execute("UPDATE chapters SET status='generating' WHERE id=?", (chid,))
    chapter = db.execute("SELECT * FROM chapters WHERE id=?", (chid,)).fetchone()
    goal, subject = db.execute("SELECT goal, subject FROM courses WHERE id=?", (cid,)).fetchone()
    cram = cram_brief(ctx, cid, chapter) if goal == "cram" else "none (Deep: no exam focus)"
    known_types = {r["name"] for r in db.execute("SELECT name FROM question_types WHERE course_id=?", (cid,))}
    sections = db.execute("SELECT * FROM sections WHERE chapter_id=? ORDER BY position", (chid,)).fetchall()
    pending_sections = []
    for sec in sections:
        if sec["generation_status"] == "complete":
            continue
        db.execute("UPDATE sections SET generation_status='generating' WHERE id=?", (sec["id"],))
        pending_sections.append(sec)
    if not pending_sections:
        db.execute("UPDATE chapters SET status='in_review' WHERE id=?", (chid,))
        return
    catalogue = catalogue_text(ctx)
    before = taught_before(ctx, cid)
    planned = [{"title": s["title"], "teaches": json.loads(s["teaches"]),
                "excerpt": " … ".join(p["text"][:400] for p in page_texts(ctx, cid, json.loads(s["pages"])))[:1200]} for s in sections]
    exam_types = [t["name"] for t in cram["question_types"]] if isinstance(cram, dict) else []
    try:
        lessons = plan_chapter(db, ctx.backend, ctx.course_dir(cid), cid, chapter, planned, {
            "goal": goal, "priority": chapter["priority"], "chapter": chapter["title"], "subject": subject, "cram": cram,
            "language": LANGUAGE_RULE, "taught": json.dumps(before[sections[0]["id"]], ensure_ascii=False),
            "components": ", ".join(CATALOGUE), "exam_types": json.dumps(exam_types, ensure_ascii=False)}, exam_types)
    except StepFailed:
        lessons = {}  # no plan: the Sections are written as before rather than stalling the Run

    def write(sec):
        pages = page_texts(ctx, cid, json.loads(sec["pages"]))
        lesson = lessons.get(sec["title"])
        inputs = {"goal": goal, "priority": chapter["priority"], "chapter": chapter["title"], "section": sec["title"],
                  "pages": pages, "catalogue": catalogue, "language": LANGUAGE_RULE, "subject": subject, "cram": cram,
                  "owner_notes": (notes or {}).get(sec["id"], "none"), "taught_before": before[sec["id"]],
                  "teaches": json.loads(sec["teaches"]), "plan": lesson or "none", "gaps": "none"}
        draft = run_pi_step(db, ctx.backend, "write_section", inputs, SectionDraft, ctx.course_dir(cid), course_id=cid)
        if lesson and (gaps := plan_gaps(lesson, draft.blocks)):  # one more try to follow the plan; then take what's written
            attach_checks(db, last_trace_id(), [{"warnings": [f"plan: {g}" for g in gaps]}])
            draft = run_pi_step(db, ctx.backend, "write_section", inputs | {"gaps": "\n".join(f"- {g}" for g in gaps)},
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
        # a rewritten Section keeps its Block ids by position (and so the Cards' history) while the Component stays the same
        old = {r["position"]: r for r in db.execute("SELECT id, position, component FROM blocks WHERE section_id=?", (sec["id"],))}
        for pos, (block, flags) in enumerate(zip(blocks, checks)):
            values = (block["component"], json.dumps(block["data"], ensure_ascii=False), json.dumps(block["citations"], ensure_ascii=False),
                      block["origin"], "flagged" if flags["errors"] else "ok", json.dumps(flags["errors"] + flags["warnings"], ensure_ascii=False),
                      json.dumps([n for n in block.get("exam_types", []) if n in known_types], ensure_ascii=False),
                      json.dumps(block.get("tests", []), ensure_ascii=False))
            prev = old.pop(pos, None)
            if prev and prev["component"] == block["component"]:
                db.execute("UPDATE blocks SET component=?, data=?, citations=?, origin=?, status=?, flags=?, exam_types=?, tests=?, "
                           "previous=NULL, review_queue=0 WHERE id=?", (*values, prev["id"]))
                continue
            if prev:
                db.execute("DELETE FROM blocks WHERE id=?", (prev["id"],))
            db.execute("INSERT INTO blocks (section_id, position, component, data, citations, origin, status, flags, exam_types, tests) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?)", (sec["id"], pos, *values))
        for prev in old.values():
            db.execute("DELETE FROM blocks WHERE id=?", (prev["id"],))
        attach_checks(db, section_trace, [{"block": i, **flags} for i, flags in enumerate(checks)])
        db.execute("UPDATE sections SET generation_status='complete' WHERE id=?", (sec["id"],))

    with ThreadPoolExecutor(max_workers=min(MODEL_LANES, len(drafts) or 1)) as pool:
        futures = {pool.submit(check_section, item): item for item in drafts}
        for future in as_completed(futures):
            save_section(futures[future], future.result())
    db.execute("UPDATE chapters SET status='in_review' WHERE id=?", (chid,))
    flag_progression(db, cid)
    if db.execute("SELECT auto_resolve FROM courses WHERE id=?", (cid,)).fetchone()[0]:
        auto_resolve(ctx, cid, chid)


def auto_resolve(ctx: Ctx, cid: int, chid: int) -> dict:
    """Resolves a Chapter's flagged Blocks with the local model: each Block's flags are its repair note, then it is re-checked
    and re-judged. The previous version is kept for undo; a Block still flagged goes to the Review Queue (worked by Claude Code)."""
    db = ctx.db
    resolved, queued, classes = [], [], []
    for sec in db.execute("SELECT id, pages FROM sections WHERE chapter_id=? ORDER BY position", (chid,)).fetchall():
        rows = db.execute("SELECT * FROM blocks WHERE section_id=? AND status='flagged' ORDER BY position", (sec["id"],)).fetchall()
        if not rows:
            continue
        notes = {i: "; ".join(json.loads(r["flags"])) or "the Block is flagged" for i, r in enumerate(rows)}
        classes += [failure_class(f) for r in rows for f in json.loads(r["flags"])]
        blocks, flags = checked_blocks(ctx, cid, [block_json(r) for r in rows], page_texts(ctx, cid, json.loads(sec["pages"])), notes)
        for row, block, f in zip(rows, blocks, flags):
            previous = {k: row[k] for k in ("component", "origin", "status")} | {k: json.loads(row[k]) for k in ("data", "citations", "flags")}
            db.execute("UPDATE blocks SET component=?, data=?, citations=?, origin=?, status=?, flags=?, previous=?, review_queue=? WHERE id=?",
                       (block["component"], json.dumps(block["data"], ensure_ascii=False), json.dumps(block["citations"], ensure_ascii=False),
                        block["origin"], "flagged" if f["errors"] else "ok", json.dumps(f["errors"] + f["warnings"], ensure_ascii=False),
                        json.dumps(previous, ensure_ascii=False), int(bool(f["errors"])), row["id"]))
            (queued if f["errors"] else resolved).append(row["id"])
    flag_progression(db, cid)  # a repaired Block is checked against the rest of the Course again
    record_owner_action(db, cid, "chapter_review", {"chapter": chid, "resolved": resolved, "queued": queued, "classes": classes}, "auto_resolved")
    return {"resolved": resolved, "queued": queued}


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
            elif r.source_error:
                warnings[i].append(f"source error: {r.reason}")  # shown to the learner next to the Block
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
    for block, block_errors, warned in zip(blocks, errors, warnings):
        state_errors, state_warnings = components.status_flags(ctx.db, block["component"]) if not block_errors else ([], [])
        flags.append({"errors": block_errors + state_errors, "warnings": warned + state_warnings + block_warnings(block)})
    return blocks, flags


def checked_block(ctx: Ctx, cid: int, raw: dict, pages: list[dict], note: str | None = None) -> tuple[dict, dict]:
    """Single-Block adapter for edits and regeneration endpoints."""
    blocks, flags = checked_blocks(ctx, cid, [raw], pages, {0: note} if note else None)
    return blocks[0], flags[0]


def block_json(row) -> dict:
    return {"id": row["id"], "position": row["position"], "component": row["component"], "data": json.loads(row["data"]),
            "citations": json.loads(row["citations"]), "origin": row["origin"], "status": row["status"], "flags": json.loads(row["flags"]),
            "exam_types": json.loads(row["exam_types"]), "tests": json.loads(row["tests"]), "review_queue": bool(row["review_queue"]),
            "previous": json.loads(row["previous"]) if row["previous"] else None,
            **({} if row["component"] in CATALOGUE else {"fallback_markdown": fallback_markdown(json.loads(row["data"]))})}


def load_chapter(ctx: Ctx, chid: int) -> dict:
    ch = ctx.db.execute("SELECT * FROM chapters WHERE id=?", (chid,)).fetchone()
    plan = {p["title"]: p for p in json.loads(ch["plan"] or '{"sections": []}')["sections"]}
    sections = []
    for s in ctx.db.execute("SELECT * FROM sections WHERE chapter_id=? ORDER BY position", (chid,)):
        blocks = [block_json(b) for b in ctx.db.execute("SELECT * FROM blocks WHERE section_id=? ORDER BY position", (s["id"],))]
        sections.append({"id": s["id"], "title": s["title"], "pages": json.loads(s["pages"]), "teaches": json.loads(s["teaches"]),
                         "objectives": [o["text"] for o in plan.get(s["title"], {}).get("objectives", [])], "blocks": blocks})
    return {"id": ch["id"], "title": ch["title"], "priority": ch["priority"], "exam_weight": ch["exam_weight"],
            "status": ch["status"], "sections": sections}
