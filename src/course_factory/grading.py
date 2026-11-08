"""Grading Copies (Live work): handwriting transcribed with vision, then graded step by step against the Marking scheme."""

import datetime as dt
import json
import uuid

import pypdfium2 as pdfium
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import search as searchm
from .context import Ctx
from .exams import SchemeStep, copy_json
from .pi_step import run_pi_step

IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_UPLOAD = 40 * 1024 * 1024


class Transcription(BaseModel):
    text: str


class DerivedScheme(BaseModel):
    scheme: list[SchemeStep] = Field(min_length=1)


class StepGrade(BaseModel):
    step: str
    awarded: float = Field(ge=0)
    comment: str


class QuestionGrade(BaseModel):
    steps: list[StepGrade] = Field(min_length=1)


def save_upload(ctx: Ctx, cid: int, copy_id: int, upload: UploadFile, kind: str) -> list[str]:
    """Stores an upload as page images (a PDF becomes one PNG per page). Returns the image paths."""
    data = upload.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file too large")
    folder = ctx.course_dir(cid) / "copies" / str(copy_id)
    folder.mkdir(parents=True, exist_ok=True)
    stem = uuid.uuid4().hex[:10]
    if upload.content_type == "application/pdf":
        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError:
            raise HTTPException(422, "not a readable PDF")
        paths = []
        for n in range(len(pdf)):
            p = folder / f"{stem}-{n + 1}.png"
            pdf[n].render(scale=2).to_pil().save(p)
            paths.append(str(p))
        return paths
    if upload.content_type not in IMAGE_TYPES:
        raise HTTPException(415, "send a PNG, JPEG or WebP image, or a PDF")
    p = folder / f"{stem}{IMAGE_TYPES[upload.content_type]}"
    p.write_bytes(data)
    return [str(p)]


def grade_copy(ctx: Ctx, cid: int, copy) -> dict:
    db = ctx.db
    files = json.loads(copy["files"])
    typed = json.loads(copy["answers"])
    workdir = ctx.course_dir(cid) / "copies" / str(copy["id"])
    workdir.mkdir(parents=True, exist_ok=True)
    questions = db.execute("SELECT * FROM questions WHERE exam_id=? ORDER BY position", (copy["exam_id"],)).fetchall()
    loose = [f["path"] for f in files if f["question_id"] is None]
    out, total, max_total = [], 0.0, 0.0
    for q in questions:
        derived = not q["scheme"] or q["scheme"] == "null"
        scheme: list[dict] = [] if derived else json.loads(q["scheme"])
        if derived:  # no Marking scheme: derive one from the model answer, and show that it was derived
            scheme = [s.model_dump() for s in run_pi_step(db, ctx.backend, "derive_scheme", {
                "statement": q["statement"], "points": q["points"], "model_answer": q["model_answer"]},
                DerivedScheme, workdir, course_id=cid, live=True).scheme]
            factor = q["points"] / sum(s["points"] for s in scheme)  # the scheme must add up to the Question's points
            scheme = [{"step": s["step"], "points": round(s["points"] * factor, 2)} for s in scheme]
            db.execute("UPDATE questions SET scheme=? WHERE id=?", (json.dumps(scheme, ensure_ascii=False), q["id"]))
        mine = [i for i, f in enumerate(files) if f["question_id"] in (q["id"], None)]  # indices, for showing the handwriting
        images = [f["path"] for f in files if f["question_id"] == q["id"]] + loose
        written = ""
        if images:
            written = run_pi_step(db, ctx.backend, "transcribe_copy", {"question": q["position"] + 1, "statement": q["statement"]},
                                  Transcription, workdir, tuple(images), course_id=cid, live=True).text
        answer = "\n\n".join(a for a in (typed.get(str(q["id"]), ""), written) if a.strip())
        graded = run_pi_step(db, ctx.backend, "grade_answer", {
            "statement": q["statement"], "model_answer": q["model_answer"], "scheme": scheme, "answer": answer or "(no answer)"},
            QuestionGrade, workdir, course_id=cid, live=True)
        by_step = {g.step: g for g in graded.steps}
        steps = []
        for i, s in enumerate(scheme):
            g = by_step.get(s["step"]) or (graded.steps[i] if i < len(graded.steps) else None)
            awarded = min(g.awarded, s["points"]) if g else 0.0  # never more than the step is worth
            hits = searchm.search(db, ctx.search, cid, f"{s['step']} {q['statement']}", 1) if awarded < s["points"] else []
            steps.append({"step": s["step"], "points": s["points"], "awarded": awarded, "comment": g.comment if g else "not addressed",
                          "page": {"source": hits[0]["source"], "page": hits[0]["page"]} if hits else None})
        score = sum(s["awarded"] for s in steps)
        total, max_total = total + score, max_total + q["points"]
        out.append({"question_id": q["id"], "position": q["position"], "points": q["points"], "awarded": score,
                    "scheme_derived": derived, "answer": answer, "files": mine, "steps": steps})
    grade = {"graded_at": dt.datetime.now(dt.UTC).isoformat(), "total": total, "max": max_total, "questions": out}
    db.execute("UPDATE copies SET grade=? WHERE id=?", (json.dumps(grade, ensure_ascii=False), copy["id"]))
    return grade


def router(ctx: Ctx) -> APIRouter:
    db = ctx.db
    r = APIRouter()

    def copy_or_404(cid: int, copy_id: int):
        row = db.execute("SELECT c.* FROM copies c JOIN exams e ON e.id=c.exam_id WHERE c.id=? AND e.course_id=?", (copy_id, cid)).fetchone()
        if row is None:
            raise HTTPException(404, "no such Copy")
        return row

    @r.post("/api/courses/{cid}/copies/{copy_id}/files", status_code=201)
    def upload(cid: int, copy_id: int, file: UploadFile = File(...), kind: str = Form("photo"), question_id: int | None = Form(None)):
        """Tablet ink (exported as PNG), photos of paper, or a PDF. Optionally tied to one Question."""
        row = copy_or_404(cid, copy_id)
        if row["grade"]:
            raise HTTPException(409, "this Copy is already graded")
        if kind not in ("ink", "photo", "pdf"):
            raise HTTPException(422, "kind is ink, photo or pdf")
        if question_id is not None and not db.execute("SELECT 1 FROM questions WHERE id=? AND exam_id=?", (question_id, row["exam_id"])).fetchone():
            raise HTTPException(422, "not a Question of this Exam")
        files = json.loads(row["files"]) + [{"path": p, "kind": kind, "question_id": question_id}
                                            for p in save_upload(ctx, cid, copy_id, file, kind)]
        db.execute("UPDATE copies SET files=? WHERE id=?", (json.dumps(files), copy_id))
        return {"files": [{"index": i, "kind": f["kind"], "question_id": f["question_id"]} for i, f in enumerate(files)]}

    @r.get("/api/courses/{cid}/copies/{copy_id}/files/{index}")
    def copy_file(cid: int, copy_id: int, index: int):
        files = json.loads(copy_or_404(cid, copy_id)["files"])
        if not 0 <= index < len(files):
            raise HTTPException(404, "no such file")
        return FileResponse(files[index]["path"])

    @r.post("/api/courses/{cid}/copies/{copy_id}/grade")
    def grade(cid: int, copy_id: int):
        row = copy_or_404(cid, copy_id)
        if not row["handed_in_at"]:
            raise HTTPException(409, "hand the Copy in first")
        grade_copy(ctx, cid, row)
        return copy_json(ctx, copy_or_404(cid, copy_id))

    @r.get("/api/courses/{cid}/copies")
    def list_copies(cid: int):
        """Graded Copies with their scores, oldest first, to show progress over time."""
        rows = db.execute("SELECT c.id, c.exam_id, e.title, c.handed_in_at, c.grade FROM copies c JOIN exams e ON e.id=c.exam_id "
                          "WHERE e.course_id=? AND c.grade IS NOT NULL ORDER BY c.handed_in_at", (cid,)).fetchall()
        return [{"id": x["id"], "exam_id": x["exam_id"], "exam": x["title"], "handed_in_at": x["handed_in_at"],
                 "total": json.loads(x["grade"])["total"], "max": json.loads(x["grade"])["max"]} for x in rows]

    return r
