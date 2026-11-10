import base64
import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Literal

import pypdfium2 as pdfium
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel, model_validator

from . import chapters as chm
from . import db as dbm
from . import exams as exm
from . import components, cram, failures, grading, ingest, labs, learner, pairing, refresh, tutor
from .kernels import DockerLauncher, Launcher, lab_image
from . import search as searchm
from .context import Ctx, Gate, Priority, Role
from .checks import check_blocks
from .generation import build_graph, gpu, pipeline, progress, run_status, seconds_left, thread, time_left
from .progression import flag_progression
from .outline import ChapterPlan, OutlinePlan, load_outline, save_outline
from .pi_step import DEFAULT_MODEL, HARNESS_DIR, STEP_MODELS, Backend, activity, model_for, record_owner_action

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
EXPORT_VIEWER = WEB_DIST.parent / "dist-export" / "export.html"
SOURCE_COLUMNS = "id, name, pages, role, paired_with, excluded"
RUN_POLL = 0.5


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


class RefreshChoice(BaseModel):
    edited: Literal["keep", "regenerate", "notes"] = "keep"


class StepModel(BaseModel):
    step: str
    model: str = ""  # empty: back to the env variable or the default


class AutoResolve(BaseModel):
    on: bool


class ExamScope(BaseModel):
    in_scope: bool


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

    @asynccontextmanager
    async def lifespan(_):
        yield
        ctx.kernels.stop_all()  # a Lab kernel (a Docker container) outlives the app otherwise

    app = FastAPI(title="course-factory", lifespan=lifespan)
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
        a = activity(cid)
        out = {"error": None, **s, "pages_read": p["done"], "pages_total": p["total"], "pipeline": pipeline(graph, cid), "progress": progress(db, cid),
               "active": cid in advancing,  # "running" but not active: the app stopped mid-step, and Retry resumes it
               "activity": {k: v for k, v in a.items() if k not in ("started", "id")}
                           | {"elapsed": round(time.time() - a["started"])} if a else None}
        if s["status"] == "running":
            out |= {"seconds_left": seconds_left(db, cid), "time_left": time_left(db, cid), "gpu": gpu()}
        return out

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

    @app.get("/api/system")
    def system():
        """What the home hub shows about the machine: the generation model and the GPU."""
        return {"model": getattr(backend, "model", None) or model_for("write_section"), "gpu": gpu()}

    db.executescript(learner.LEARNER_SCHEMA)  # the settings table, before learner.router creates it
    row = db.execute("SELECT value FROM settings WHERE key='step_models'").fetchone()
    STEP_MODELS.clear()
    STEP_MODELS.update(json.loads(row["value"]) if row else {})

    @app.get("/api/models")
    def step_models():
        """The model each Model step runs on, and where that comes from (Settings, an env variable, or the default)."""
        steps = sorted(p.stem for p in HARNESS_DIR.glob("*.md"))
        default = os.environ.get("CF_MODEL") or DEFAULT_MODEL
        return {"default": default, "steps": [{"step": s, "model": model_for(s), "from": "settings" if s in STEP_MODELS else
                                                "env" if os.environ.get(f"CF_MODEL_{s.upper()}") else "default"} for s in steps]}

    @app.put("/api/models")
    def put_model(body: StepModel):
        """Sets (or, with no model, clears) one step's model; the next model call of that step uses it."""
        if body.step not in {p.stem for p in HARNESS_DIR.glob("*.md")}:
            raise HTTPException(422, f"unknown step {body.step}")
        if body.model:
            STEP_MODELS[body.step] = body.model
        else:
            STEP_MODELS.pop(body.step, None)
        db.execute("INSERT INTO settings VALUES ('step_models', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(STEP_MODELS),))
        return step_models()

    @app.post("/api/courses/upload", status_code=201)
    def create_course_from_upload(tasks: BackgroundTasks, name: str = Form(..., min_length=1), files: list[UploadFile] = File(...)):
        """A Course from a folder picked in the browser: each file's name is its path inside the picked folder."""
        rels = [PurePosixPath(f.filename or "") for f in files]
        if any(r.is_absolute() or ".." in r.parts or not r.name for r in rels):
            raise HTTPException(422, "file paths must stay inside the picked folder")
        tops = {r.parts[0] for r in rels}
        if len(tops) == 1 and all(len(r.parts) > 1 for r in rels):  # the picked folder's own name
            rels = [PurePosixPath(*r.parts[1:]) for r in rels]
        folder = data_dir / "uploads" / uuid.uuid4().hex[:12]
        for f, rel in zip(files, rels):
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            with open(folder / rel, "wb") as out:
                shutil.copyfileobj(f.file, out)
        return create_course(NewCourse(name=name, folder=str(folder)), tasks)

    @app.get("/api/courses")
    def list_courses():
        """Every Course with what the home hub shows: its Run, Chapters, Cards due and exam countdown."""
        out, today, stamp = [], dt.date.today(), dt.datetime.now(dt.UTC).isoformat()
        for r in db.execute("SELECT * FROM courses ORDER BY id DESC").fetchall():
            s = status(r["id"])
            ch = db.execute("SELECT COUNT(*) total, COALESCE(SUM(status='published'),0) published FROM chapters "
                            "WHERE course_id=? AND priority!='skip'", (r["id"],)).fetchone()
            out.append(dict(r) | {
                "run": {k: s.get(k) for k in ("status", "gate", "error", "active", "pages_read", "pages_total", "seconds_left")},
                "chapters_total": ch["total"], "chapters_published": ch["published"],
                "cards_due": db.execute("SELECT COUNT(*) FROM cards WHERE course_id=? AND due<=?", (r["id"], stamp)).fetchone()[0],
                "exam_countdown_days": (dt.date.fromisoformat(r["exam_date"]) - today).days if r["exam_date"] else None})
        return out

    @app.get("/api/courses/{cid}")
    def get_course(cid: int):
        return dict(course_or_404(cid))

    @app.delete("/api/courses/{cid}", status_code=204)
    def delete_course(cid: int):
        """Deletes a Course and everything made or recorded for it. The folder it was imported from is never touched;
        Focus Sessions stay (they keep the Streak) and Traces stay as harness evidence, both unlinked from the Course."""
        course = course_or_404(cid)
        with lock:
            if cid in advancing:
                raise HTTPException(409, "The Run is working on this Course. Delete it once the Run stops or waits for you.")
            advancing.add(cid)  # nothing may resume the Run while it is being deleted
        try:
            for lab in db.execute("SELECT id FROM labs WHERE course_id=?", (cid,)).fetchall():
                ctx.kernels.stop(f"lab-{lab['id']}")
            db.execute("BEGIN IMMEDIATE")
            try:
                searchm.drop_passages(db, cid)
                for sql in [
                    "DELETE FROM places WHERE course_id=?", "DELETE FROM tutor_messages WHERE course_id=?",
                    "DELETE FROM cards WHERE course_id=?",
                    "DELETE FROM copies WHERE exam_id IN (SELECT id FROM exams WHERE course_id=?)",
                    "DELETE FROM exams WHERE course_id=?", "DELETE FROM question_types WHERE course_id=?", "DELETE FROM labs WHERE course_id=?", "DELETE FROM lab_envs WHERE course_id=?",
                    "DELETE FROM chapters WHERE course_id=?",  # cascades to Sections, Blocks and what hangs off them
                    "DELETE FROM pages WHERE source_id IN (SELECT id FROM sources WHERE course_id=?)",
                    "UPDATE sources SET paired_with=NULL WHERE course_id=?", "DELETE FROM sources WHERE course_id=?",
                    # ids get reused: unlink what stays so a later Course with this id doesn't inherit it
                    "UPDATE components SET course_id=NULL WHERE course_id=?", "UPDATE focus_sessions SET course_id=NULL WHERE course_id=?",
                    "UPDATE traces SET course_id=NULL WHERE course_id=?",
                    "DELETE FROM courses WHERE id=?",
                ]:
                    db.execute(sql, (cid,))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
            graph.checkpointer.delete_thread(thread(cid)["configurable"]["thread_id"])
        finally:
            advancing.discard(cid)
        shutil.rmtree(ctx.course_dir(cid), ignore_errors=True)
        folder = Path(course["folder"]).resolve()
        if folder.is_relative_to((data_dir / "uploads").resolve()):  # a browser upload's own copy, not the owner's folder
            shutil.rmtree(folder, ignore_errors=True)

    @app.get("/api/courses/{cid}/run")
    def get_run(cid: int):
        return status(cid)

    @app.get("/api/courses/{cid}/run/events")
    def run_events(cid: int):
        """Server-sent Run progress: a "status" event on each change, until the Run stops (gate, done or failed)."""
        course_or_404(cid)

        def events():
            last = None
            while True:
                s = status(cid)
                if s != last:
                    yield tutor.sse("status", s)
                    last = s
                if s["status"] != "running" and cid not in advancing:
                    return
                time.sleep(RUN_POLL)

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/api/courses/{cid}/run/retry")
    def retry_run(cid: int, tasks: BackgroundTasks):
        claim(cid, None)
        db.execute("UPDATE courses SET run_error=NULL WHERE id=?", (cid,))
        tasks.add_task(advance, cid, None)
        return {"ok": True}

    def read_and_index(cid: int):
        try:
            ingest.read_pages(ctx, cid)  # only the new pages: reading is resumable
            searchm.index_course(db, ctx.search, cid)
        except Exception:
            pass  # the Trace has it; the next upload retries the unread pages

    @app.post("/api/courses/{cid}/sources", status_code=201)
    def upload_notes(cid: int, tasks: BackgroundTasks, file: UploadFile = File(...)):
        """A PDF of the owner's notes (from the tablet) becomes a new "personal notes" Source, then is read and indexed."""
        course_or_404(cid)
        data = file.file.read(grading.MAX_UPLOAD + 1)
        if len(data) > grading.MAX_UPLOAD:
            raise HTTPException(413, "file too large")
        try:
            pages = len(pdfium.PdfDocument(data))
        except pdfium.PdfiumError:
            raise HTTPException(422, "send a readable PDF")
        stem = re.sub(r"[^\w.-]+", "_", Path(file.filename or "notes").stem)[:60] or "notes"
        name = f"notes/{stem}-{uuid.uuid4().hex[:6]}.pdf"
        path = ctx.course_dir(cid) / "sources" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        sid = db.execute("INSERT INTO sources (course_id, name, path, pages, role) VALUES (?,?,?,?,'personal notes')",
                         (cid, name, str(path), pages)).lastrowid
        tasks.add_task(read_and_index, cid)
        return source_json(db.execute(f"SELECT {SOURCE_COLUMNS} FROM sources WHERE id=?", (sid,)).fetchone())

    refreshes: dict[int, dict] = {}  # the last Refresh per Course: running, done (with what it did) or failed

    @app.get("/api/courses/{cid}/refresh")
    def refresh_preview(cid: int):
        """What changed in the Course folder since it was imported, and the last Refresh."""
        course_or_404(cid)
        return refresh.diff(ctx, cid) | {"last": refreshes.get(cid)}

    def run_refresh(cid: int, edited: str):
        try:
            refreshes[cid] = {"state": "done", "result": refresh.apply(ctx, cid, edited)}
        except Exception as e:
            refreshes[cid] = {"state": "failed", "error": str(e)[:2000]}
        finally:
            advancing.discard(cid)

    @app.post("/api/courses/{cid}/refresh", status_code=202)
    def start_refresh(cid: int, body: RefreshChoice, tasks: BackgroundTasks):
        """Re-reads only changed pages and regenerates only the Sections citing them; owner-edited ones as chosen."""
        course_or_404(cid)
        if cid in advancing:
            raise HTTPException(409, "the Course is busy: wait for the Run or Refresh to finish")
        advancing.add(cid)
        refreshes[cid] = {"state": "running"}
        tasks.add_task(run_refresh, cid, body.edited)
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
    def get_traces(cid: int, limit: int | None = Query(None, ge=1, le=200)):
        """Every Trace, oldest first; with a limit, the newest ones first (the Run screen's feed)."""
        course_or_404(cid)
        if limit is None:
            return [dict(r) for r in db.execute("SELECT * FROM traces WHERE course_id=? ORDER BY id", (cid,))]
        return [dict(r) for r in db.execute("SELECT * FROM traces WHERE course_id=? ORDER BY id DESC LIMIT ?", (cid, limit))]

    @app.get("/api/courses/{cid}/map")
    def course_map(cid: int):
        """Every imported file with how many of its pages are read so far: the Run screen draws the course from it."""
        course_or_404(cid)
        return [dict(r) for r in db.execute(
            "SELECT s.name, s.pages, s.role, COUNT(p.text) AS read, COALESCE(SUM(p.text IS NOT NULL AND p.readable=0), 0) AS unreadable "
            "FROM sources s LEFT JOIN pages p ON p.source_id=s.id WHERE s.course_id=? AND s.excluded=0 GROUP BY s.id ORDER BY s.name", (cid,))]

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

    def cid_of_block(bid: int) -> int:
        return db.execute("SELECT c.course_id FROM blocks b JOIN sections s ON s.id=b.section_id JOIN chapters c ON c.id=s.chapter_id "
                          "WHERE b.id=?", (bid,)).fetchone()[0]

    def save_block(bid: int, block: dict, flags: dict):
        db.execute("UPDATE blocks SET component=?, data=?, citations=?, origin=?, status=?, flags=? WHERE id=?",
                   (block["component"], json.dumps(block["data"], ensure_ascii=False), json.dumps(block["citations"], ensure_ascii=False),
                    block["origin"], "flagged" if flags["errors"] else "ok", json.dumps(flags["errors"] + flags["warnings"], ensure_ascii=False), bid))
        flag_progression(db, cid_of_block(bid))
        if db.execute("SELECT status FROM blocks WHERE id=?", (bid,)).fetchone()["status"] == "ok":
            db.execute("UPDATE blocks SET review_queue=0 WHERE id=?", (bid,))
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
        draft = {"component": row["component"], "data": body.data, "citations": json.loads(row["citations"]), "origin": row["origin"],
                 "tests": json.loads(row["tests"])}
        (block,), (errors,) = check_blocks([draft], chm.source_pages(ctx, cid), components.schemas(db))
        if errors:
            raise HTTPException(422, {"errors": errors})
        record_owner_action(db, cid, "chapter_review", {"block": bid, "data": body.data, "classes": classes_of(row)}, "edited")
        state_errors, warnings = components.status_flags(db, row["component"])
        return save_block(bid, block, {"errors": state_errors, "warnings": warnings})

    @app.post("/api/courses/{cid}/blocks/{bid}/approve")
    def approve_block(cid: int, bid: int):
        block_or_404(cid, bid)
        record_owner_action(db, cid, "chapter_review", {"block": bid}, "approved")
        db.execute("UPDATE blocks SET status='ok', review_queue=0 WHERE id=?", (bid,))
        return chm.block_json(db.execute("SELECT * FROM blocks WHERE id=?", (bid,)).fetchone())

    @app.post("/api/courses/{cid}/blocks/{bid}/regenerate")
    def regenerate_block(cid: int, bid: int, body: RegenerateNote):
        row = block_or_404(cid, bid)
        record_owner_action(db, cid, "chapter_review", {"block": bid, "note": body.note, "classes": classes_of(row)}, "regenerated")
        current = chm.block_json(row)
        pages = chm.page_texts(ctx, cid, json.loads(row["section_pages"]))
        block, flags = chm.checked_block(ctx, cid, current, pages, note=body.note)
        return save_block(bid, block, flags)

    def classes_of(row) -> list[str]:
        """The Failure classes of what the owner fixed: its flags, or "unclassified" for a fix of a clean Block."""
        return [failures.failure_class(f) for f in json.loads(row["flags"])] or ["unclassified"]

    @app.post("/api/courses/{cid}/chapters/{chid}/auto-resolve")
    def auto_resolve(cid: int, chid: int):
        """The local model resolves the Chapter's flagged Blocks; what it can't goes to the Review Queue."""
        if chapter_or_404(cid, chid)["status"] != "in_review":
            raise HTTPException(409, "only a Chapter under review can be auto-resolved")
        return chm.auto_resolve(ctx, cid, chid)

    @app.post("/api/courses/{cid}/blocks/{bid}/undo")
    def undo_block(cid: int, bid: int):
        """Puts back the Block as it was before auto-resolve."""
        row = block_or_404(cid, bid)
        if not row["previous"]:
            raise HTTPException(409, "nothing to undo")
        p = json.loads(row["previous"])
        db.execute("UPDATE blocks SET component=?, data=?, citations=?, origin=?, status=?, flags=?, previous=NULL, review_queue=0 WHERE id=?",
                   (p["component"], json.dumps(p["data"], ensure_ascii=False), json.dumps(p["citations"], ensure_ascii=False), p["origin"],
                    p["status"], json.dumps(p["flags"], ensure_ascii=False), bid))
        record_owner_action(db, cid, "chapter_review", {"block": bid}, "undone")
        return chm.block_json(db.execute("SELECT * FROM blocks WHERE id=?", (bid,)).fetchone())

    @app.put("/api/courses/{cid}/auto-resolve")
    def set_auto_resolve(cid: int, body: AutoResolve):
        """Per-Run option: auto-resolve each Chapter's flags as soon as it is written, before review."""
        course_or_404(cid)
        db.execute("UPDATE courses SET auto_resolve=? WHERE id=?", (int(body.on), cid))
        return dict(course_or_404(cid))

    @app.get("/api/review-blocks")
    def review_blocks():
        """The Review Queue of flagged Blocks auto-resolve couldn't fix, with their pages. Worked by Claude Code from outside."""
        out = []
        for row in db.execute("SELECT b.*, s.pages AS section_pages, s.title AS section, c.title AS chapter, c.course_id FROM blocks b "
                              "JOIN sections s ON s.id=b.section_id JOIN chapters c ON c.id=s.chapter_id WHERE b.review_queue=1 ORDER BY b.id"):
            out.append(chm.block_json(row) | {"course_id": row["course_id"], "chapter": row["chapter"], "section": row["section"],
                                              "classes": classes_of(row), "pages": chm.page_texts(ctx, row["course_id"], json.loads(row["section_pages"]))})
        return out

    @app.get("/api/failures")
    def failure_report(course: int | None = None):
        """Failure classes ranked by count, with examples, Harness versions, handler and rate before/after hardening."""
        return failures.report(db, course)

    @app.post("/api/courses/{cid}/chapters/{chid}/publish")
    def publish_chapter(cid: int, chid: int, tasks: BackgroundTasks):
        if chapter_or_404(cid, chid)["status"] != "in_review":
            raise HTTPException(409, "only a Chapter under review can be published")
        record_owner_action(db, cid, "chapter_review", {"chapter": chid}, "published")
        db.execute("UPDATE chapters SET status='published' WHERE id=?", (chid,))
        flag_progression(db, cid)
        cram.unlock_likely_cards(ctx, cid, chid)
        if status(cid)["gate"] == "chapter_review" and not chm.awaiting_review(ctx, cid):
            finish_review(cid, tasks)
        return {"ok": True}

    @app.post("/api/courses/{cid}/gates/chapter_review")
    def finish_review(cid: int, tasks: BackgroundTasks):
        """Resumes the Run once nothing waits for review (publishing the last Chapter calls this itself)."""
        if chm.awaiting_review(ctx, cid):
            raise HTTPException(409, "publish every Chapter under review first")
        claim(cid, "chapter_review")
        tasks.add_task(advance, cid, Command(resume={"approved": True}))
        return {"ok": True}

    @app.get("/api/courses/{cid}/reader")
    def reader(cid: int):
        """What the learner can read: published Chapters only, in course order."""
        course_or_404(cid)
        return cram.annotate(ctx, cid, [chm.load_chapter(ctx, r["id"]) for r in db.execute(
            "SELECT id FROM chapters WHERE course_id=? AND status='published' ORDER BY position", (cid,))])

    @app.get("/api/courses/{cid}/export")
    def export_course(cid: int):
        """The Course as one HTML file that opens offline: published Chapters, practice and Exams with answers; no model."""
        course = course_or_404(cid)
        if not EXPORT_VIEWER.exists():
            raise HTTPException(503, "the export viewer is not built: run npm run build in web/")
        chapters = reader(cid)
        blocks = [b for c in chapters for s in c["sections"] for b in s["blocks"]]
        pages = {}
        for b in blocks:  # only Figures carry their page image; Citations stay as text to keep the file small
            if b["component"] == "figure":
                row = db.execute("SELECT p.image FROM pages p JOIN sources s ON s.id=p.source_id WHERE s.course_id=? AND s.name=? AND p.n=?",
                                 (cid, b["data"]["source"], b["data"]["page"])).fetchone()
                if row and row["image"] and Path(row["image"]).exists():
                    pages[f'{b["data"]["source"]}#{b["data"]["page"]}'] = "data:image/png;base64," + base64.b64encode(Path(row["image"]).read_bytes()).decode()
        comps = []
        for name in sorted({b["component"] for b in blocks}):
            js = components.comp_dir(ctx, name) / "component.js"
            if js.exists() and db.execute("SELECT 1 FROM components WHERE name=? AND status='approved'", (name,)).fetchone():
                comps.append({"name": name, "bundle": js.read_text()})
        exams = [exm.load_exam(ctx, e["id"], with_answers=True) for e in db.execute(
            "SELECT id FROM exams WHERE course_id=? ORDER BY kind DESC, id", (cid,))]
        payload = {"course": {"name": course["name"]}, "chapters": chapters, "exams": exams, "pages": pages, "components": comps,
                   "cheatsheet": cram.cheat_sheet(ctx, cid)}
        data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")  # no "</script>" can close the data tag
        html = EXPORT_VIEWER.read_text().replace("<!--CF_COURSE-->", data, 1)
        filename = re.sub(r"[^A-Za-z0-9._-]+", "-", course["name"]).strip("-") or "course"
        return Response(html, media_type="text/html", headers={"content-disposition": f'attachment; filename="{filename}.html"'})

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
        return [{k: e[k] for k in ("id", "kind", "title", "duration_min", "cohort")} | {"chapters": json.loads(e["chapters"]),
                                                                                    "in_scope": bool(e["in_scope"])}
                for e in db.execute("SELECT * FROM exams WHERE course_id=? ORDER BY kind DESC, id", (cid,))]

    @app.put("/api/courses/{cid}/exams/{eid}/scope")
    def set_exam_scope(cid: int, eid: int, body: ExamScope):
        """Whether a Past paper weighs the Course (it was set for the learner's cohort) or is only extra practice. No model:
        every paper's Questions already have Question Types."""
        exam_or_404(cid, eid)
        db.execute("UPDATE exams SET in_scope=? WHERE id=?", (int(body.in_scope), eid))
        exm.set_exam_weights(ctx, cid)
        return {"ok": True}

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

    app.include_router(pairing.router(db))
    app.add_middleware(pairing.PairingGuard, db=db)
    app.include_router(components.router(ctx))
    app.include_router(learner.router(ctx))
    app.include_router(cram.router(ctx))
    app.include_router(tutor.router(ctx))
    app.include_router(grading.router(ctx))
    app.include_router(app_labs)
    if (WEB_DIST / "index.html").exists():  # the built frontend; any other path is a client-side route
        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            f = (WEB_DIST / path).resolve()
            return FileResponse(f if path and f.is_file() and WEB_DIST in f.parents else WEB_DIST / "index.html")

    return app
