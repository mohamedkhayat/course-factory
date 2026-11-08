import datetime as dt
import json
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from langgraph.types import Command
from pydantic import BaseModel, model_validator

from . import chapters as chm
from . import db as dbm
from . import exams as exm
from . import grading, labs, learner, tutor
from .kernels import DockerLauncher, Launcher, lab_image
from . import search as searchm
from .context import Ctx, Gate, Priority, Role
from .checks import check_blocks
from .generation import build_graph, run_status, thread
from .outline import ChapterPlan, OutlinePlan, load_outline, save_outline
from .pi_step import Backend, record_owner_action

SOURCE_COLUMNS = "id, name, pages, role, paired_with, excluded"


class NewCourse(BaseModel):
    name: str
    folder: str


class SourceEdit(BaseModel):
    role: Role | None = None
    paired_with: int | None = None  # null unpairs
    excluded: bool | None = None

    @model_validator(mode="after")
    def no_null_role_or_exclusion(self):
        for field in ("role", "excluded"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class FoundDecision(BaseModel):
    goal: Literal["cram", "deep"]
    exam_date: dt.date | None = None

    @model_validator(mode="after")
    def cram_needs_date(self):
        if self.goal == "cram" and self.exam_date is None:
            raise ValueError("Cram needs an exam date")
        return self


class ChapterEdit(ChapterPlan):
    priority: Priority = "normal"


class OutlineEdit(BaseModel):
    chapters: list[ChapterEdit]


class GoalChange(FoundDecision):
    pass


class BlockEdit(BaseModel):
    data: dict


class RegenerateNote(BaseModel):
    note: str


class CopyAnswers(BaseModel):
    answers: dict[str, str]  # Question id -> typed answer (Markdown)


def source_json(row: sqlite3.Row) -> dict:
    return dict(row) | {"excluded": bool(row["excluded"])}


def create_app(data_dir: Path, backend: Backend, search_models: searchm.SearchModels | None = None,
               labs_launcher: Callable[[int], Launcher] | None = None) -> FastAPI:
    data_dir.mkdir(parents=True, exist_ok=True)
    db = dbm.connect(data_dir / "course-factory.db")
    models = search_models or searchm.LocalSearchModels()
    searchm.setup(db, models.dim)
    ctx = Ctx(db, backend, data_dir, models)
    app_labs = labs.router(ctx)  # creates the Lab tables the launcher below reads

    def docker_launcher(cid: int) -> Launcher:
        """The Course's pinned Lab Environment: the image id is fixed the first time a Lab runs."""
        row = db.execute("SELECT image FROM lab_envs WHERE course_id=?", (cid,)).fetchone()
        if row is None:
            db.execute("INSERT OR IGNORE INTO lab_envs VALUES (?,?)", (cid, lab_image()))
            row = db.execute("SELECT image FROM lab_envs WHERE course_id=?", (cid,)).fetchone()
        return DockerLauncher(row["image"])

    ctx.labs_launcher = labs_launcher or docker_launcher
    graph = build_graph(ctx, sqlite3.connect(data_dir / "langgraph.db", check_same_thread=False))
    app = FastAPI(title="course-factory")
    advancing: set[int] = set()  # Courses whose Run is executing right now
    lock = threading.Lock()

    def course_or_404(cid: int) -> sqlite3.Row:
        row = db.execute("SELECT * FROM courses WHERE id=?", (cid,)).fetchone()
        if row is None:
            raise HTTPException(404, "no such Course")
        return row

    def status(cid: int) -> dict:
        s = run_status(graph, cid, course_or_404(cid)["run_error"])
        p = db.execute("SELECT COALESCE(SUM(s.pages),0) total, (SELECT COUNT(*) FROM pages p JOIN sources s2 ON s2.id=p.source_id "
                       "WHERE s2.course_id=? AND p.text IS NOT NULL) done FROM sources s WHERE s.course_id=?", (cid, cid)).fetchone()
        return {"error": None, **s, "pages_read": p["done"], "pages_total": p["total"]}

    def claim(cid: int, gate: Gate | None):
        """Reserve the Run so two requests can't advance it at once.

        gate=None is a retry: allowed when the Run failed, or shows "running" with nothing executing it
        (the app stopped mid-step)."""
        with lock:
            s = status(cid)
            ok = s["status"] in ("failed", "running") if gate is None else s["gate"] == gate
            if cid in advancing or not ok:
                raise HTTPException(409, "Run is not stuck" if gate is None else f"Run is not waiting at the {gate} gate")
            advancing.add(cid)

    def advance(cid: int, payload):
        try:
            graph.invoke(payload, thread(cid))
            db.execute("UPDATE courses SET run_error=NULL WHERE id=?", (cid,))
        except Exception as e:  # the Run stays resumable from its last checkpoint; the owner retries
            db.execute("UPDATE courses SET run_error=? WHERE id=?", (f"{type(e).__name__}: {e}"[:2000], cid))
        finally:
            advancing.discard(cid)

    @app.post("/api/courses", status_code=201)
    def create_course(body: NewCourse, tasks: BackgroundTasks):
        folder = Path(body.folder).expanduser()
        if not folder.is_dir():
            raise HTTPException(422, "folder does not exist")
        cid = db.execute("INSERT INTO courses (name, folder) VALUES (?,?)", (body.name, str(folder.resolve()))).lastrowid
        assert cid is not None
        advancing.add(cid)
        tasks.add_task(advance, cid, {"course_id": cid})
        return {"id": cid}

    @app.get("/api/courses/{cid}")
    def get_course(cid: int):
        return dict(course_or_404(cid))

    @app.get("/api/courses/{cid}/run")
    def get_run(cid: int):
        return status(cid)

    @app.post("/api/courses/{cid}/run/retry")
    def retry_run(cid: int, tasks: BackgroundTasks):
        claim(cid, None)
        db.execute("UPDATE courses SET run_error=NULL WHERE id=?", (cid,))
        tasks.add_task(advance, cid, None)
        return {"ok": True}

    @app.get("/api/courses/{cid}/found")
    def get_found(cid: int):
        course_or_404(cid)
        sources = [source_json(r) for r in db.execute(f"SELECT {SOURCE_COLUMNS} FROM sources WHERE course_id=? ORDER BY name", (cid,))]
        unreadable = [{"source": r["name"], "page": r["n"]} for r in db.execute(
            "SELECT s.name, p.n FROM pages p JOIN sources s ON s.id=p.source_id WHERE s.course_id=? AND p.readable=0 ORDER BY s.name, p.n", (cid,))]
        return {"sources": sources, "unreadable_pages": unreadable}

    @app.patch("/api/courses/{cid}/sources/{sid}")
    def edit_source(cid: int, sid: int, body: SourceEdit):
        require_gate(cid, "found")
        if db.execute("SELECT 1 FROM sources WHERE id=? AND course_id=?", (sid, cid)).fetchone() is None:
            raise HTTPException(404, "no such Source")
        changes = body.model_dump(exclude_unset=True)
        if changes.get("paired_with") is not None and db.execute(
                "SELECT 1 FROM sources WHERE id=? AND course_id=? AND id!=?", (changes["paired_with"], cid, sid)).fetchone() is None:
            raise HTTPException(422, "Pairing must point to another Source of this Course")
        for col, val in changes.items():  # col comes from SourceEdit's fixed field names
            db.execute(f"UPDATE sources SET {col}=? WHERE id=?", (int(val) if isinstance(val, bool) else val, sid))
        return source_json(db.execute(f"SELECT {SOURCE_COLUMNS} FROM sources WHERE id=?", (sid,)).fetchone())

    @app.post("/api/courses/{cid}/gates/found")
    def approve_found(cid: int, body: FoundDecision, tasks: BackgroundTasks):
        claim(cid, "found")
        decision = body.model_dump(mode="json")
        record_owner_action(db, cid, "found", decision, "approved")
        tasks.add_task(advance, cid, Command(resume=decision))
        return {"ok": True}

    def require_gate(cid: int, gate: Gate):
        if status(cid)["gate"] != gate:
            raise HTTPException(409, f"Run is not waiting at the {gate} gate")

    @app.patch("/api/courses/{cid}")
    def change_goal(cid: int, body: GoalChange):
        course_or_404(cid)
        if status(cid)["gate"] == "found":
            raise HTTPException(409, "choose the Goal by approving the found gate")
        db.execute("UPDATE courses SET goal=?, exam_date=? WHERE id=?", (body.goal, body.exam_date and body.exam_date.isoformat(), cid))
        return dict(course_or_404(cid))

    @app.get("/api/courses/{cid}/outline")
    def get_outline(cid: int):
        course_or_404(cid)
        return {"chapters": load_outline(ctx, cid)}

    @app.put("/api/courses/{cid}/outline")
    def edit_outline(cid: int, body: OutlineEdit):
        require_gate(cid, "outline")
        if not body.chapters:
            raise HTTPException(422, "an outline needs at least one Chapter")
        record_owner_action(db, cid, "outline", body.model_dump(), "edited")
        save_outline(ctx, cid, OutlinePlan(chapters=list(body.chapters)), [c.priority for c in body.chapters])
        return {"chapters": load_outline(ctx, cid)}

    @app.post("/api/courses/{cid}/gates/outline")
    def approve_outline(cid: int, tasks: BackgroundTasks):
        claim(cid, "outline")
        record_owner_action(db, cid, "outline", {}, "approved")
        tasks.add_task(advance, cid, Command(resume={"approved": True}))  # an empty resume value is ignored by LangGraph
        return {"ok": True}

    @app.get("/api/courses/{cid}/search")
    def search(cid: int, q: str, k: int = 8):
        course_or_404(cid)
        return searchm.search(db, models, cid, q, k)

    @app.get("/api/courses/{cid}/traces")
    def get_traces(cid: int):
        course_or_404(cid)
        return [dict(r) for r in db.execute("SELECT * FROM traces WHERE course_id=? ORDER BY id", (cid,))]

    def chapter_or_404(cid: int, chid: int) -> sqlite3.Row:
        row = db.execute("SELECT * FROM chapters WHERE id=? AND course_id=?", (chid, cid)).fetchone()
        if row is None:
            raise HTTPException(404, "no such Chapter")
        return row

    def block_or_404(cid: int, bid: int) -> sqlite3.Row:
        row = db.execute("SELECT b.*, c.status chapter_status, s.pages section_pages FROM blocks b JOIN sections s ON s.id=b.section_id "
                         "JOIN chapters c ON c.id=s.chapter_id WHERE b.id=? AND c.course_id=?", (bid, cid)).fetchone()
        if row is None:
            raise HTTPException(404, "no such Block")
        if row["chapter_status"] not in ("in_review", "published"):
            raise HTTPException(409, "the Block's Chapter is still generating")
        return row

    def save_block(bid: int, block: dict, flags: dict):
        db.execute("UPDATE blocks SET component=?, data=?, citations=?, origin=?, status=?, flags=? WHERE id=?",
                   (block["component"], json.dumps(block["data"], ensure_ascii=False), json.dumps(block["citations"], ensure_ascii=False),
                    block["origin"], "flagged" if flags["errors"] else "ok", json.dumps(flags["errors"] + flags["warnings"], ensure_ascii=False), bid))
        return chm.block_json(db.execute("SELECT * FROM blocks WHERE id=?", (bid,)).fetchone())

    @app.get("/api/courses/{cid}/chapters/{chid}")
    def get_chapter(cid: int, chid: int):
        chapter_or_404(cid, chid)
        return chm.load_chapter(ctx, chid)

    @app.get("/api/courses/{cid}/review")
    def review_list(cid: int):
        """Chapters waiting for review, flagged Blocks first."""
        course_or_404(cid)
        out = []
        for ch in db.execute("SELECT id FROM chapters WHERE course_id=? AND status='in_review' ORDER BY position", (cid,)):
            chapter = chm.load_chapter(ctx, ch["id"])
            blocks = [b | {"section": s["title"]} for s in chapter["sections"] for b in s["blocks"]]
            out.append({"id": chapter["id"], "title": chapter["title"],
                        "blocks": sorted(blocks, key=lambda b: (b["status"] != "flagged", not b["flags"]))})
        return out

    @app.put("/api/courses/{cid}/blocks/{bid}")
    def edit_block(cid: int, bid: int, body: BlockEdit):
        row = block_or_404(cid, bid)
        draft = {"component": row["component"], "data": body.data, "citations": json.loads(row["citations"]), "origin": row["origin"]}
        (block,), (errors,) = check_blocks([draft], chm.source_pages(ctx, cid))
        if errors:
            raise HTTPException(422, {"errors": errors})
        record_owner_action(db, cid, "chapter_review", {"block": bid, "data": body.data}, "edited")
        return save_block(bid, block, {"errors": [], "warnings": []})

    @app.post("/api/courses/{cid}/blocks/{bid}/approve")
    def approve_block(cid: int, bid: int):
        block_or_404(cid, bid)
        record_owner_action(db, cid, "chapter_review", {"block": bid}, "approved")
        db.execute("UPDATE blocks SET status='ok' WHERE id=?", (bid,))
        return chm.block_json(db.execute("SELECT * FROM blocks WHERE id=?", (bid,)).fetchone())

    @app.post("/api/courses/{cid}/blocks/{bid}/regenerate")
    def regenerate_block(cid: int, bid: int, body: RegenerateNote):
        row = block_or_404(cid, bid)
        record_owner_action(db, cid, "chapter_review", {"block": bid, "note": body.note}, "regenerated")
        current = chm.block_json(row)
        pages = chm.page_texts(ctx, cid, json.loads(row["section_pages"]))
        block, flags = chm.checked_block(ctx, cid, current, pages, note=body.note)
        return save_block(bid, block, flags)

    @app.post("/api/courses/{cid}/chapters/{chid}/publish")
    def publish_chapter(cid: int, chid: int):
        if chapter_or_404(cid, chid)["status"] != "in_review":
            raise HTTPException(409, "only a Chapter under review can be published")
        record_owner_action(db, cid, "chapter_review", {"chapter": chid}, "published")
        db.execute("UPDATE chapters SET status='published' WHERE id=?", (chid,))
        return {"ok": True}

    @app.get("/api/courses/{cid}/reader")
    def reader(cid: int):
        """What the learner can read: published Chapters only, in course order."""
        course_or_404(cid)
        return [chm.load_chapter(ctx, r["id"]) for r in db.execute(
            "SELECT id FROM chapters WHERE course_id=? AND status='published' ORDER BY position", (cid,))]

    def exam_or_404(cid: int, eid: int) -> sqlite3.Row:
        row = db.execute("SELECT * FROM exams WHERE id=? AND course_id=?", (eid, cid)).fetchone()
        if row is None:
            raise HTTPException(404, "no such Exam")
        return row

    def copy_or_404(cid: int, copy_id: int) -> sqlite3.Row:
        row = db.execute("SELECT c.* FROM copies c JOIN exams e ON e.id=c.exam_id WHERE c.id=? AND e.course_id=?", (copy_id, cid)).fetchone()
        if row is None:
            raise HTTPException(404, "no such Copy")
        return row

    @app.get("/api/courses/{cid}/exams")
    def list_exams(cid: int):
        course_or_404(cid)
        return [{k: e[k] for k in ("id", "kind", "title", "duration_min")} | {"chapters": json.loads(e["chapters"])}
                for e in db.execute("SELECT * FROM exams WHERE course_id=? ORDER BY kind DESC, id", (cid,))]

    @app.get("/api/courses/{cid}/exams/{eid}")
    def get_exam(cid: int, eid: int):
        """Exam mode's sheet: no model answers or Marking schemes."""
        exam_or_404(cid, eid)
        return exm.load_exam(ctx, eid, with_answers=False)

    @app.post("/api/courses/{cid}/exams/{eid}/copies", status_code=201)
    def start_copy(cid: int, eid: int):
        exam = exam_or_404(cid, eid)
        start = exm.now()
        deadline = start + dt.timedelta(minutes=exam["duration_min"])
        copy_id = db.execute("INSERT INTO copies (exam_id, started_at, deadline) VALUES (?,?,?)",
                             (eid, start.isoformat(), deadline.isoformat())).lastrowid
        return exm.copy_json(ctx, db.execute("SELECT * FROM copies WHERE id=?", (copy_id,)).fetchone())

    @app.get("/api/courses/{cid}/copies/{copy_id}")
    def get_copy(cid: int, copy_id: int):
        return exm.copy_json(ctx, copy_or_404(cid, copy_id))

    def open_copy(cid: int, copy_id: int) -> sqlite3.Row:
        row = copy_or_404(cid, copy_id)
        if row["handed_in_at"]:
            raise HTTPException(409, "this Copy was handed in")
        if exm.now() > dt.datetime.fromisoformat(row["deadline"]) + dt.timedelta(seconds=exm.GRACE_SECONDS):
            raise HTTPException(409, "time is up: hand the Copy in")
        return row

    @app.put("/api/courses/{cid}/copies/{copy_id}/answers")
    def save_answers(cid: int, copy_id: int, body: CopyAnswers):
        row = open_copy(cid, copy_id)
        valid = {str(r["id"]) for r in db.execute("SELECT id FROM questions WHERE exam_id=?", (row["exam_id"],))}
        if unknown := set(body.answers) - valid:
            raise HTTPException(422, f"not Questions of this Exam: {sorted(unknown)}")
        answers = json.loads(row["answers"]) | body.answers
        db.execute("UPDATE copies SET answers=? WHERE id=?", (json.dumps(answers, ensure_ascii=False), copy_id))
        return exm.copy_json(ctx, copy_or_404(cid, copy_id))

    @app.post("/api/courses/{cid}/copies/{copy_id}/hand-in")
    def hand_in(cid: int, copy_id: int):
        row = copy_or_404(cid, copy_id)
        if row["handed_in_at"]:
            raise HTTPException(409, "this Copy was already handed in")
        db.execute("UPDATE copies SET handed_in_at=? WHERE id=?", (exm.now().isoformat(), copy_id))
        learner.unlock_exam_cards(ctx, cid, row["exam_id"])
        return exm.copy_json(ctx, copy_or_404(cid, copy_id))

    app.include_router(learner.router(ctx))
    app.include_router(tutor.router(ctx))
    app.include_router(grading.router(ctx))
    app.include_router(app_labs)
    return app
