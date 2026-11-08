"""The Generation Run as a LangGraph graph (ADR 0001). One thread per Course; Approval Gates are interrupts."""

import shutil
import sqlite3
from pathlib import Path
from typing import Literal, TypedDict

import pypdfium2 as pdfium
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel

from .pi_step import Backend, run_pi_step

Role = Literal["course notes", "exercise sheet", "lab", "past exam", "correction", "personal notes", "data"]
DATA_SUFFIXES = {".csv", ".txt", ".json", ".xlsx", ".npy", ".mat", ".dat"}


class PageReading(BaseModel):
    text: str
    readable: bool


class RoleProposal(BaseModel):
    name: str
    role: Role
    paired_with: str | None = None


class RoleProposals(BaseModel):
    sources: list[RoleProposal]


class RunState(TypedDict):
    course_id: int


def build_graph(db: sqlite3.Connection, backend: Backend, data_dir: Path, checkpoints: sqlite3.Connection):
    def course_dir(cid: int) -> Path:
        return data_dir / "courses" / str(cid)

    def import_sources(state: RunState):
        cid = state["course_id"]
        folder = Path(db.execute("SELECT folder FROM courses WHERE id=?", (cid,)).fetchone()["folder"])
        dest = course_dir(cid) / "sources"
        for f in sorted(p for p in folder.rglob("*") if p.is_file() and not p.name.startswith(".")):
            rel = f.relative_to(folder)
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest / rel)
            pages = len(pdfium.PdfDocument(str(f))) if f.suffix.lower() == ".pdf" else 0
            role = "data" if f.suffix.lower() in DATA_SUFFIXES else None
            db.execute("INSERT INTO sources (course_id, name, path, pages, role) VALUES (?,?,?,?,?)",
                       (cid, rel.as_posix(), str(dest / rel), pages, role))
        return {}

    def read_pages(state: RunState):
        cid = state["course_id"]
        img_dir = course_dir(cid) / "pages"
        img_dir.mkdir(parents=True, exist_ok=True)
        # shortcut: notebooks are not transcribed yet; they get read when Labs are built.
        for src in db.execute("SELECT * FROM sources WHERE course_id=? AND pages>0", (cid,)).fetchall():
            pdf = pdfium.PdfDocument(src["path"])
            for n in range(1, src["pages"] + 1):
                done = db.execute("SELECT 1 FROM pages WHERE source_id=? AND n=? AND text IS NOT NULL", (src["id"], n)).fetchone()
                if done:  # resumable: a restart mid-read skips pages already read
                    continue
                img = img_dir / f"{src['id']}-{n}.png"
                pdf[n - 1].render(scale=2).to_pil().save(img)
                r = run_pi_step(db, backend, "read_page", {"source": src["name"], "page": str(n)}, PageReading,
                                img_dir, [img], course_id=cid)
                db.execute("INSERT OR REPLACE INTO pages (source_id, n, image, text, readable) VALUES (?,?,?,?,?)",
                           (src["id"], n, str(img), r.text, int(r.readable)))
        return {}

    def propose_roles(state: RunState):
        cid = state["course_id"]
        rows = db.execute(
            "SELECT s.id, s.name, s.role, p.text FROM sources s LEFT JOIN pages p ON p.source_id=s.id AND p.n=1 WHERE s.course_id=?",
            (cid,)).fetchall()
        undecided = [{"name": r["name"], "start": (r["text"] or "")[:1500]} for r in rows if r["role"] is None]
        if not undecided:
            return {}
        ids = {r["name"]: r["id"] for r in rows}
        props = run_pi_step(db, backend, "propose_roles", {"sources": undecided}, RoleProposals,
                            course_dir(cid), course_id=cid)
        for p in props.sources:
            if p.name in ids:
                db.execute("UPDATE sources SET role=?, paired_with=? WHERE id=?", (p.role, ids.get(p.paired_with or ""), ids[p.name]))
        return {}

    def found_gate(state: RunState):
        decision = interrupt({"gate": "found"})
        db.execute("UPDATE courses SET goal=?, exam_date=? WHERE id=?",
                   (decision["goal"], decision.get("exam_date"), state["course_id"]))
        return {}

    def outline_gate(state: RunState):
        # shortcut: outline generation is the next slice; the Run parks here until it exists.
        interrupt({"gate": "outline"})
        return {}

    g = StateGraph(RunState)
    for name, fn in [("import_sources", import_sources), ("read_pages", read_pages), ("propose_roles", propose_roles),
                     ("found_gate", found_gate), ("outline_gate", outline_gate)]:
        g.add_node(name, fn)
    g.add_edge(START, "import_sources")
    g.add_edge("import_sources", "read_pages")
    g.add_edge("read_pages", "propose_roles")
    g.add_edge("propose_roles", "found_gate")
    g.add_edge("found_gate", "outline_gate")
    g.add_edge("outline_gate", END)
    return g.compile(checkpointer=SqliteSaver(checkpoints))


def thread(course_id: int) -> RunnableConfig:
    return {"configurable": {"thread_id": f"course-{course_id}"}}


def run_status(graph, course_id: int) -> dict:
    snap = graph.get_state(thread(course_id))
    if snap.interrupts:
        return {"status": "waiting", "gate": snap.interrupts[0].value["gate"]}
    if snap.next:
        return {"status": "running", "gate": None, "next": list(snap.next)}
    return {"status": "done" if snap.values else "not started", "gate": None}

