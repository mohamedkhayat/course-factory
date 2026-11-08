"""Past papers rebuilt from the real exams and their corrigés, Mock exams in their style, and exam mode (Copies)."""

import datetime as dt
import json

from pydantic import BaseModel, Field, model_validator

from .chapters import LANGUAGE_RULE, page_texts
from .checks import render_errors
from .context import Ctx
from .pi_step import run_pi_step

MOCK_EXAMS = 2
GRACE_SECONDS = 60  # autosave arriving just after the countdown still counts


class SchemeStep(BaseModel):
    step: str
    points: float = Field(gt=0)


class QuestionPlan(BaseModel):
    statement: str
    points: float = Field(gt=0)
    model_answer: str
    scheme: list[SchemeStep] | None = None

    @model_validator(mode="after")
    def scheme_adds_up(self):
        if self.scheme and abs(sum(s.points for s in self.scheme) - self.points) > 1e-6:
            raise ValueError("the Marking scheme's points must add up to the Question's points")
        return self


class ExamPlan(BaseModel):
    title: str
    duration_min: int = Field(gt=0)
    chapters: list[str] = []  # titles of the Chapters covered
    questions: list[QuestionPlan] = Field(min_length=1)


def build_exams(ctx: Ctx, cid: int) -> None:
    """Rebuilds each past exam once, then tops Mock exams up to MOCK_EXAMS. Safe to re-run."""
    db = ctx.db
    titles = [r["title"] for r in db.execute("SELECT title FROM chapters WHERE course_id=? AND priority!='skip' ORDER BY position", (cid,))]
    for src in db.execute("SELECT * FROM sources WHERE course_id=? AND role='past exam' AND excluded=0 ORDER BY name", (cid,)).fetchall():
        if db.execute("SELECT 1 FROM exams WHERE source_id=?", (src["id"],)).fetchone():
            continue
        correction = db.execute("SELECT * FROM sources WHERE course_id=? AND excluded=0 AND (id=? OR paired_with=?) AND id!=?",
                                (cid, src["paired_with"], src["id"], src["id"])).fetchone()
        plan = run_pi_step(db, ctx.backend, "rebuild_past_paper", {
            "exam": pages_of(ctx, cid, src), "correction": pages_of(ctx, cid, correction) if correction else [],
            "chapters": titles, "language": LANGUAGE_RULE}, ExamPlan, ctx.course_dir(cid), course_id=cid)
        save_exam(ctx, cid, plan, "past_paper", src["id"])
    have = db.execute("SELECT COUNT(*) FROM exams WHERE course_id=? AND kind='mock'", (cid,)).fetchone()[0]
    for n in range(have, MOCK_EXAMS):
        past = [load_exam(ctx, e["id"], with_answers=False) for e in db.execute(
            "SELECT id FROM exams WHERE course_id=? ORDER BY id", (cid,))]
        weights = [{"chapter": r["title"], "exam_weight": r["exam_weight"]} for r in db.execute(
            "SELECT title, exam_weight FROM chapters WHERE course_id=? AND priority!='skip' ORDER BY position", (cid,))]
        plan = run_pi_step(db, ctx.backend, "write_mock_exam", {
            "number": n + 1, "past_papers": past, "chapters": weights, "language": LANGUAGE_RULE},
            ExamPlan, ctx.course_dir(cid), course_id=cid)
        save_exam(ctx, cid, plan, "mock", None)


def pages_of(ctx: Ctx, cid: int, src) -> list[dict]:
    return page_texts(ctx, cid, [{"source": src["name"], "page": n} for n in range(1, src["pages"] + 1)])


def save_exam(ctx: Ctx, cid: int, plan: ExamPlan, kind: str, source_id: int | None) -> int:
    db = ctx.db
    ids = {r["title"]: r["id"] for r in db.execute("SELECT id, title FROM chapters WHERE course_id=?", (cid,))}
    covered = [ids[t] for t in plan.chapters if t in ids]
    eid = db.execute("INSERT INTO exams (course_id, kind, title, duration_min, chapters, source_id) VALUES (?,?,?,?,?,?)",
                     (cid, kind, plan.title, plan.duration_min, json.dumps(covered), source_id)).lastrowid
    assert eid is not None
    questions = [q.model_dump() for q in plan.questions]
    errors = render_errors([{"component": "", "data": q} for q in questions])
    for i, q in enumerate(questions):
        db.execute("INSERT INTO questions (exam_id, position, statement, points, model_answer, scheme, flags) VALUES (?,?,?,?,?,?,?)",
                   (eid, i, q["statement"], q["points"], q["model_answer"], json.dumps(q["scheme"]), json.dumps(errors.get(i, []))))
    return eid


def load_exam(ctx: Ctx, eid: int, with_answers: bool) -> dict:
    """An Exam; without answers it is what exam mode shows (no model answer, no Marking scheme)."""
    e = ctx.db.execute("SELECT * FROM exams WHERE id=?", (eid,)).fetchone()
    qs = []
    for q in ctx.db.execute("SELECT * FROM questions WHERE exam_id=? ORDER BY position", (eid,)):
        item = {"id": q["id"], "position": q["position"], "statement": q["statement"], "points": q["points"]}
        if with_answers:
            item |= {"model_answer": q["model_answer"], "scheme": json.loads(q["scheme"]), "flags": json.loads(q["flags"])}
        qs.append(item)
    return {"id": e["id"], "kind": e["kind"], "title": e["title"], "duration_min": e["duration_min"],
            "chapters": json.loads(e["chapters"]), "total_points": sum(q["points"] for q in qs), "questions": qs}


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def copy_json(ctx: Ctx, row) -> dict:
    deadline = dt.datetime.fromisoformat(row["deadline"])
    out = {"id": row["id"], "exam_id": row["exam_id"], "started_at": row["started_at"], "deadline": row["deadline"],
           "remaining_seconds": max(0, int((deadline - now()).total_seconds())) if not row["handed_in_at"] else 0,
           "answers": json.loads(row["answers"]), "handed_in_at": row["handed_in_at"],
           "grade": json.loads(row["grade"]) if row["grade"] else None}
    if row["handed_in_at"]:  # the correction is shown only after hand-in
        out["correction"] = load_exam(ctx, row["exam_id"], with_answers=True)
    return out
