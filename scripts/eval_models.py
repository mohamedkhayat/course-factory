"""Compare models on the same Sections of a saved Course: write each Section, then check, repair and judge it as a Run does.

    uv run python scripts/eval_models.py --course 1 --sections 6 llama-swap/nemotron3.5-bolt llama-swap/ninfer-qwen3.8-27b:medium

Works on a copy of the database, so the Course is never touched. Prints one row per model."""
import argparse
import json
import os
import shutil
import tempfile
import time
from collections import Counter
from pathlib import Path

from course_factory import db as dbm
from course_factory.chapters import GroundingBatch, language_rule, SectionDraft, catalogue_text, checked_blocks, page_texts, source_pages, words
from course_factory.checks import check_blocks
from course_factory.components import schemas
from course_factory.context import Ctx
from course_factory.pi_step import PiBackend, StepFailed, run_pi_step

VISUAL = {"plot", "surface_plot", "optimizer_animation", "diagram", "step_diagram", "iteration_table", "terminal", "figure", "explorer"}
PRACTICE = {"quiz", "fill_blanks", "code_exercise", "exercise"}
DATA = Path(os.environ.get("CF_DATA", Path.home() / ".local/share/course-factory"))


def evaluate(model: str, cid: int, sections: list[int], work: Path) -> dict:
    shutil.copy(DATA / "course-factory.db", work / "course-factory.db")
    db = dbm.connect(work / "course-factory.db")
    ctx = Ctx(db=db, backend=PiBackend(), data_dir=work, search=None)  # type: ignore[arg-type]  # no search in these steps
    for k in [k for k in os.environ if k.startswith("CF_MODEL_") and k != "CF_MODEL_CONCURRENCY"] + ["CF_FALLBACK_MODEL"]:
        os.environ.pop(k, None)  # every step runs on the model under test, or the comparison is confounded
    os.environ["CF_MODEL"] = model
    sources, extra, catalogue = source_pages(ctx, cid), schemas(db), catalogue_text(ctx)
    goal = db.execute("SELECT goal FROM courses WHERE id=?", (cid,)).fetchone()["goal"]
    row = Counter()
    used = Counter()
    start, before = time.monotonic(), db.execute("SELECT COALESCE(MAX(id), 0) FROM traces").fetchone()[0]
    for sid in sections:
        sec = db.execute("SELECT s.*, c.title chapter, c.priority FROM sections s JOIN chapters c ON c.id=s.chapter_id WHERE s.id=?",
                         (sid,)).fetchone()
        pages = page_texts(ctx, cid, json.loads(sec["pages"]))
        try:
            draft = run_pi_step(db, ctx.backend, "write_section", {
                "goal": goal, "priority": sec["priority"], "chapter": sec["chapter"], "section": sec["title"],
                "pages": pages, "catalogue": catalogue, "language": language_rule(db, cid),
                "subject": db.execute("SELECT subject FROM courses WHERE id=?", (cid,)).fetchone()["subject"],
                "owner_notes": "none", "taught_before": [], "teaches": json.loads(sec["teaches"]), "plan": "none", "gaps": "none",
                "chapter_map": "none", "cram": "none"}, SectionDraft, work, course_id=cid)
        except StepFailed:
            row["sections failed"] += 1
            continue
        _, first = check_blocks(draft.blocks, sources, extra)
        blocks, flags = checked_blocks(ctx, cid, draft.blocks, pages)
        row["blocks"] += len(blocks)
        row["errors at first check"] += sum(bool(e) for e in first)
        row["still flagged"] += sum(bool(f["errors"]) for f in flags)
        row["from source"] += sum(b["origin"] == "from_source" for b in blocks)
        used.update(b["component"] for b in blocks)
        for b in blocks:  # how much of the Section explains, against how much asks
            row["practice words" if b["component"] in PRACTICE else "teaching words"] += words(b["data"])
        kinds = {b["component"] for b in blocks}
        row["sections with a visual and practice"] += bool(kinds & VISUAL and kinds & PRACTICE)
    for (out,) in db.execute("SELECT output FROM traces WHERE id > ? AND step='judge_grounding' AND error IS NULL", (before,)):
        for r in GroundingBatch.model_validate_json(out).results:
            row["contradicts" if r.contradicts else "grounded" if r.grounded else "extends"] += 1
    for step, n, failed in db.execute("SELECT step, COUNT(*), SUM(error IS NOT NULL) FROM traces WHERE id > ? GROUP BY step",
                                      (before,)):
        row[f"{step} calls"], row[f"{step} failed"] = n, failed
    return {"model": model, "minutes": round((time.monotonic() - start) / 60, 1), **row, "components": dict(used.most_common())}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("models", nargs="+")
    p.add_argument("--course", type=int, default=1)
    p.add_argument("--sections", type=int, default=6, help="how many Sections, spread evenly over the Course")
    a = p.parse_args()
    db = dbm.connect(DATA / "course-factory.db")
    ids = [r[0] for r in db.execute("SELECT s.id FROM sections s JOIN chapters c ON c.id=s.chapter_id WHERE c.course_id=? "
                                    "ORDER BY c.position, s.position", (a.course,))]
    picked = ids[::max(1, len(ids) // a.sections)][:a.sections]
    for model in a.models:
        with tempfile.TemporaryDirectory(prefix="cf-eval-") as work:
            print(json.dumps(evaluate(model, a.course, picked, Path(work)), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
