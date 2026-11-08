import datetime as dt
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from langgraph.types import Command
from pydantic import BaseModel, model_validator

from . import db as dbm
from .generation import Role, build_graph, run_status, thread
from .pi_step import Backend


class NewCourse(BaseModel):
    name: str
    folder: str


class SourceEdit(BaseModel):
    role: Role | None = None
    paired_with: int | None = None
    excluded: bool | None = None


class FoundDecision(BaseModel):
    goal: Literal["cram", "deep"]
    exam_date: dt.date | None = None

    @model_validator(mode="after")
    def cram_needs_date(self):
        if self.goal == "cram" and self.exam_date is None:
            raise ValueError("Cram needs an exam date")
        return self


def create_app(data_dir: Path, backend: Backend) -> FastAPI:
    data_dir.mkdir(parents=True, exist_ok=True)
    db = dbm.connect(data_dir / "course-factory.db")
    graph = build_graph(db, backend, data_dir, sqlite3.connect(data_dir / "checkpoints.db", check_same_thread=False))
    app = FastAPI(title="course-factory")

    def course_or_404(cid: int) -> sqlite3.Row:
        row = db.execute("SELECT * FROM courses WHERE id=?", (cid,)).fetchone()
        if row is None:
            raise HTTPException(404, "no such Course")
        return row

    def require_gate(cid: int, gate: str):
        if run_status(graph, cid).get("gate") != gate:
            raise HTTPException(409, f"Run is not waiting at the {gate} gate")

    @app.post("/api/courses", status_code=201)
    def create_course(body: NewCourse, tasks: BackgroundTasks):
        folder = Path(body.folder).expanduser()
        if not folder.is_dir():
            raise HTTPException(422, "folder does not exist")
        cid = db.execute("INSERT INTO courses (name, folder) VALUES (?,?)", (body.name, str(folder.resolve()))).lastrowid
        assert cid is not None
        tasks.add_task(lambda: graph.invoke({"course_id": cid}, thread(cid)))
        return {"id": cid}

    @app.get("/api/courses/{cid}")
    def get_course(cid: int):
        return dict(course_or_404(cid))

    @app.get("/api/courses/{cid}/run")
    def get_run(cid: int):
        course_or_404(cid)
        return run_status(graph, cid)

    @app.get("/api/courses/{cid}/found")
    def get_found(cid: int):
        course_or_404(cid)
        sources = [dict(r) | {"excluded": bool(r["excluded"])} for r in
                   db.execute("SELECT id, name, pages, role, paired_with, excluded FROM sources WHERE course_id=? ORDER BY name", (cid,))]
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
        row = db.execute("SELECT id, name, pages, role, paired_with, excluded FROM sources WHERE id=?", (sid,)).fetchone()
        return dict(row) | {"excluded": bool(row["excluded"])}

    @app.post("/api/courses/{cid}/gates/found")
    def approve_found(cid: int, body: FoundDecision, tasks: BackgroundTasks):
        course_or_404(cid)
        require_gate(cid, "found")
        db.execute("INSERT INTO traces (course_id, step, harness_version, inputs, owner_action) VALUES (?,?,?,?,?)",
                   (cid, "found_gate", "-", body.model_dump_json(), "approved"))
        tasks.add_task(lambda: graph.invoke(Command(resume=body.model_dump(mode="json")), thread(cid)))
        return {"ok": True}

    @app.get("/api/courses/{cid}/traces")
    def get_traces(cid: int):
        course_or_404(cid)
        return [dict(r) for r in db.execute("SELECT * FROM traces WHERE course_id=? ORDER BY id", (cid,))]

    return app
