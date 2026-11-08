import datetime as dt
import sqlite3
import threading
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from langgraph.types import Command
from pydantic import BaseModel, model_validator

from . import db as dbm
from . import search as searchm
from .context import Ctx, Gate, Priority, Role
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


def source_json(row: sqlite3.Row) -> dict:
    return dict(row) | {"excluded": bool(row["excluded"])}


def create_app(data_dir: Path, backend: Backend, search_models: searchm.SearchModels | None = None) -> FastAPI:
    data_dir.mkdir(parents=True, exist_ok=True)
    db = dbm.connect(data_dir / "course-factory.db")
    models = search_models or searchm.LocalSearchModels()
    searchm.setup(db, models.dim)
    ctx = Ctx(db, backend, data_dir, models)
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

    return app
