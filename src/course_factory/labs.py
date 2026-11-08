"""Labs built from the TPs: Steps with hidden Checks proven to reject wrong code, Hints, locked Solutions, a real .ipynb."""

import asyncio
import json
from pathlib import Path

import nbformat
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .chapters import LANGUAGE_RULE, page_texts
from .context import Ctx
from .kernels import Kernel
from .learner import record
from .pi_step import StepFailed, run_pi_step

REPAIRS = 3

LAB_SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_envs (course_id INTEGER PRIMARY KEY REFERENCES courses(id), image TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS labs (
  id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES courses(id), source_id INTEGER REFERENCES sources(id),
  title TEXT NOT NULL, intro TEXT NOT NULL, chapters TEXT NOT NULL DEFAULT '[]', flags TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS lab_steps (
  id INTEGER PRIMARY KEY, lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE, position INTEGER NOT NULL,
  statement TEXT NOT NULL, starter TEXT NOT NULL, check_code TEXT NOT NULL, hints TEXT NOT NULL, solution TEXT NOT NULL,
  hints_shown INTEGER NOT NULL DEFAULT 0, passed INTEGER NOT NULL DEFAULT 0, gave_up INTEGER NOT NULL DEFAULT 0
);
"""


class StepPlan(BaseModel):
    statement: str
    starter: str = ""
    solution: str
    check: str  # Python asserts run after the learner's code; never Check plots
    hints: list[str] = []
    wrong: list[str] = Field(min_length=1)  # plausible wrong versions the Check must reject


class LabPlan(BaseModel):
    title: str
    intro: str
    chapters: list[str] = []
    steps: list[StepPlan] = Field(min_length=1)


class RepairedStep(BaseModel):
    step: StepPlan


class NotebookIn(BaseModel):
    notebook: dict


def isolated(setup: list[str], code: str, check: str) -> str:
    """Runs setup, candidate and Check in a fresh namespace, so one proof can't leak into the next."""
    return f"__cf = {{}}\nfor __src in {json.dumps(setup + [code, check])}:\n    exec(compile(__src, '<lab>', 'exec'), __cf)\ndel __cf"


def prove(kernel: Kernel, setup: list[str], step: StepPlan) -> list[str]:
    """Errors if the Check doesn't pass the Solution or doesn't fail the starter and every wrong version."""
    errors = []
    _, err = kernel.execute(isolated(setup, step.solution, step.check), silent=True, timeout=120)
    if err:
        errors.append(f"the Check fails the Solution: {err['ename']}: {err['evalue']}")
    for label, code in [("the starter code", step.starter)] + [(f"wrong version {i + 1}", w) for i, w in enumerate(step.wrong)]:
        _, err = kernel.execute(isolated(setup, code, step.check), silent=True, timeout=120)
        if not err:
            errors.append(f"the Check passes {label}; it must reject it")
    return errors


def lab_dirs(ctx: Ctx, cid: int, lab_id: int | str) -> tuple[Path, Path]:
    return ctx.course_dir(cid) / "labs" / str(lab_id), ctx.course_dir(cid) / "sources"


def build_labs(ctx: Ctx, cid: int) -> None:
    """One Lab per TP Source, built once. Steps whose Check can't be proven after REPAIRS are left out and noted."""
    db = ctx.db
    tps = db.execute("SELECT * FROM sources WHERE course_id=? AND role='lab' AND excluded=0 ORDER BY name", (cid,)).fetchall()
    if not tps:
        return
    launcher = ctx.labs_launcher(cid)
    data_files = [r["name"] for r in db.execute("SELECT name FROM sources WHERE course_id=? AND role='data' AND excluded=0", (cid,))]
    titles = [r["title"] for r in db.execute("SELECT title FROM chapters WHERE course_id=? ORDER BY position", (cid,))]
    for tp in tps:
        if db.execute("SELECT 1 FROM labs WHERE source_id=?", (tp["id"],)).fetchone():
            continue
        pages = page_texts(ctx, cid, [{"source": tp["name"], "page": n} for n in range(1, tp["pages"] + 1)])
        if tp["path"].endswith(".ipynb"):  # a notebook TP: its cells are the text
            nb = nbformat.read(tp["path"], as_version=4)
            pages = [{"source": tp["name"], "page": 0, "text": "\n\n".join(f"[{c.cell_type}]\n{c.source}" for c in nb.cells)}]
        plan = run_pi_step(db, ctx.backend, "build_lab", {"tp": pages, "data_files": data_files, "chapters": titles,
                                                          "language": LANGUAGE_RULE}, LabPlan, ctx.course_dir(cid), course_id=cid)
        workdir, data_dir = lab_dirs(ctx, cid, f"proof-{tp['id']}")
        key = f"proof-{cid}-{tp['id']}"
        kernel = ctx.kernels.get(key, launcher, workdir, data_dir)
        try:
            steps, flags, setup = [], [], []
            for n, step in enumerate(plan.steps, 1):
                errors = prove(kernel, setup, step)
                for _ in range(REPAIRS):
                    if not errors:
                        break
                    try:
                        step = run_pi_step(db, ctx.backend, "repair_lab_step", {"step": step.model_dump(), "errors": errors,
                                           "setup": setup}, RepairedStep, ctx.course_dir(cid), course_id=cid).step
                    except StepFailed as e:
                        errors.append(str(e))
                        break
                    errors = prove(kernel, setup, step)
                if errors:
                    flags.append({"step": n, "statement": step.statement, "errors": errors})
                else:
                    steps.append(step)
                setup.append(step.solution)  # later Steps build on this one's reference state
        finally:
            ctx.kernels.stop(key)
        ids = {r["title"]: r["id"] for r in db.execute("SELECT id, title FROM chapters WHERE course_id=?", (cid,))}
        lab_id = db.execute("INSERT INTO labs (course_id, source_id, title, intro, chapters, flags) VALUES (?,?,?,?,?,?)",
                            (cid, tp["id"], plan.title, plan.intro, json.dumps([ids[t] for t in plan.chapters if t in ids]),
                             json.dumps(flags, ensure_ascii=False))).lastrowid
        for i, s in enumerate(steps):
            db.execute("INSERT INTO lab_steps (lab_id, position, statement, starter, check_code, hints, solution) VALUES (?,?,?,?,?,?,?)",
                       (lab_id, i, s.statement, s.starter, s.check, json.dumps(s.hints, ensure_ascii=False), s.solution))


def step_json(row) -> dict:
    hints = json.loads(row["hints"])
    unlocked = bool(row["passed"] or row["gave_up"])
    return {"id": row["id"], "position": row["position"], "statement": row["statement"], "starter": row["starter"],
            "hints": hints[: row["hints_shown"]], "hints_left": len(hints) - row["hints_shown"], "passed": bool(row["passed"]),
            "gave_up": bool(row["gave_up"]), "solution": row["solution"] if unlocked else None}


def starter_notebook(lab, steps) -> nbformat.NotebookNode:
    nb = nbformat.v4.new_notebook()
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    nb.cells.append(nbformat.v4.new_markdown_cell(f"# {lab['title']}\n\n{lab['intro']}"))
    for s in steps:
        nb.cells.append(nbformat.v4.new_markdown_cell(f"## Step {s['position'] + 1}\n\n{s['statement']}", metadata={"cf_step": s["id"]}))
        nb.cells.append(nbformat.v4.new_code_cell(s["starter"], metadata={"cf_step": s["id"]}))
    return nb


def router(ctx: Ctx) -> APIRouter:
    db = ctx.db
    db.executescript(LAB_SCHEMA)
    r = APIRouter()

    def lab_or_404(cid: int, lab_id: int):
        row = db.execute("SELECT * FROM labs WHERE id=? AND course_id=?", (lab_id, cid)).fetchone()
        if row is None:
            raise HTTPException(404, "no such Lab")
        return row

    def step_or_404(cid: int, lab_id: int, step_id: int):
        lab_or_404(cid, lab_id)
        row = db.execute("SELECT * FROM lab_steps WHERE id=? AND lab_id=?", (step_id, lab_id)).fetchone()
        if row is None:
            raise HTTPException(404, "no such Step")
        return row

    def notebook_path(cid: int, lab_id: int) -> Path:
        return lab_dirs(ctx, cid, lab_id)[0] / "lab.ipynb"

    def kernel(cid: int, lab_id: int) -> Kernel:
        workdir, data_dir = lab_dirs(ctx, cid, lab_id)
        return ctx.kernels.get(f"lab-{lab_id}", ctx.labs_launcher(cid), workdir, data_dir)

    @r.get("/api/courses/{cid}/labs")
    def list_labs(cid: int):
        return [{"id": x["id"], "title": x["title"], "chapters": json.loads(x["chapters"]), "steps": x["n"], "passed": x["p"]}
                for x in db.execute("SELECT l.*, (SELECT COUNT(*) FROM lab_steps WHERE lab_id=l.id) n, "
                                    "(SELECT COUNT(*) FROM lab_steps WHERE lab_id=l.id AND passed=1) p FROM labs l "
                                    "WHERE course_id=? ORDER BY id", (cid,))]

    @r.get("/api/courses/{cid}/labs/{lab_id}")
    def get_lab(cid: int, lab_id: int):
        lab = lab_or_404(cid, lab_id)
        steps = [step_json(s) for s in db.execute("SELECT * FROM lab_steps WHERE lab_id=? ORDER BY position", (lab_id,))]
        return {"id": lab["id"], "title": lab["title"], "intro": lab["intro"], "chapters": json.loads(lab["chapters"]),
                "flags": json.loads(lab["flags"]), "steps": steps, "kernel_running": ctx.kernels.running(f"lab-{lab_id}")}

    @r.get("/api/courses/{cid}/labs/{lab_id}/notebook")
    def get_notebook(cid: int, lab_id: int):
        """The learner's work as a real .ipynb."""
        lab = lab_or_404(cid, lab_id)
        path = notebook_path(cid, lab_id)
        if not path.exists():
            steps = [dict(s) for s in db.execute("SELECT * FROM lab_steps WHERE lab_id=? ORDER BY position", (lab_id,))]
            path.parent.mkdir(parents=True, exist_ok=True)
            nbformat.write(starter_notebook(lab, steps), path)
        return Response(path.read_text(), media_type="application/x-ipynb+json",
                        headers={"Content-Disposition": f'attachment; filename="lab-{lab_id}.ipynb"'})

    @r.put("/api/courses/{cid}/labs/{lab_id}/notebook")
    def save_notebook(cid: int, lab_id: int, body: NotebookIn):
        lab_or_404(cid, lab_id)
        try:
            nb = nbformat.from_dict(body.notebook)
            nbformat.validate(nb)
        except Exception as e:
            raise HTTPException(422, f"not a valid notebook: {str(e)[:300]}")
        path = notebook_path(cid, lab_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        nbformat.write(nb, path)
        return {"ok": True}

    @r.post("/api/courses/{cid}/labs/{lab_id}/kernel/stop")
    def stop_kernel(cid: int, lab_id: int):
        lab_or_404(cid, lab_id)
        ctx.kernels.stop(f"lab-{lab_id}")
        return {"ok": True}

    @r.post("/api/courses/{cid}/labs/{lab_id}/steps/{step_id}/check")
    def check_step(cid: int, lab_id: int, step_id: int):
        """Runs the hidden Check in the learner's kernel, against what they have run so far."""
        step = step_or_404(cid, lab_id, step_id)
        _, err = kernel(cid, lab_id).execute(step["check_code"], silent=True, timeout=120)
        if err is None and not step["passed"]:
            db.execute("UPDATE lab_steps SET passed=1 WHERE id=?", (step_id,))
            chapters = json.loads(lab_or_404(cid, lab_id)["chapters"])
            record(ctx, "lab_step", chapters[0] if chapters else None)
        message = None if err is None else (err["evalue"] if err["ename"] == "AssertionError" and err["evalue"] else "not yet")
        return {"passed": err is None, "message": message, "step": step_json(step_or_404(cid, lab_id, step_id))}

    @r.post("/api/courses/{cid}/labs/{lab_id}/steps/{step_id}/hint")
    def next_hint(cid: int, lab_id: int, step_id: int):
        step = step_or_404(cid, lab_id, step_id)
        if step["hints_shown"] >= len(json.loads(step["hints"])):
            raise HTTPException(409, "no more Hints")
        db.execute("UPDATE lab_steps SET hints_shown=hints_shown+1 WHERE id=?", (step_id,))
        return step_json(step_or_404(cid, lab_id, step_id))

    @r.post("/api/courses/{cid}/labs/{lab_id}/steps/{step_id}/give-up")
    def give_up(cid: int, lab_id: int, step_id: int):
        step_or_404(cid, lab_id, step_id)
        db.execute("UPDATE lab_steps SET gave_up=1 WHERE id=?", (step_id,))
        return step_json(step_or_404(cid, lab_id, step_id))

    @r.websocket("/api/courses/{cid}/labs/{lab_id}/run")
    async def run_code(ws: WebSocket, cid: int, lab_id: int):
        """Send {"code": "..."}; receive {"output": <nbformat output>} as it comes, then {"done": true, "error": ...}."""
        await ws.accept()
        if db.execute("SELECT 1 FROM labs WHERE id=? AND course_id=?", (lab_id, cid)).fetchone() is None:
            await ws.close(code=4404)
            return
        loop = asyncio.get_running_loop()
        try:
            k = await run_in_threadpool(kernel, cid, lab_id)
            while True:
                msg = await ws.receive_json()
                queue: asyncio.Queue = asyncio.Queue()
                job = loop.run_in_executor(None, lambda: k.execute(
                    str(msg.get("code", "")), on_output=lambda o: loop.call_soon_threadsafe(queue.put_nowait, o)))
                while not (job.done() and queue.empty()):
                    try:
                        await ws.send_json({"output": await asyncio.wait_for(queue.get(), 0.1)})
                    except asyncio.TimeoutError:
                        pass
                _, err = await job
                await ws.send_json({"done": True, "error": err})
        except WebSocketDisconnect:
            pass

    return r
