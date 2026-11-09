"""The Generation Run as a LangGraph graph (ADR 0001). One thread per Course; Approval Gates are interrupts."""

import sqlite3
import subprocess
import time
from typing import TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from . import chapters, exams, ingest, labs, outline, search
from .context import Ctx


class RunState(TypedDict):
    course_id: int


def build_graph(ctx: Ctx, langgraph_db: sqlite3.Connection):
    db = ctx.db

    def node(fn):
        def run(state: RunState):
            fn(ctx, state["course_id"])
            return {}
        return run

    def found_gate(state: RunState):
        decision = interrupt({"gate": "found"})
        db.execute("UPDATE courses SET goal=?, exam_date=? WHERE id=?",
                   (decision["goal"], decision.get("exam_date"), state["course_id"]))
        return {}

    def outline_gate(state: RunState):
        interrupt({"gate": "outline"})
        return {}

    def chapter_review_gate(state: RunState):
        """Holds the Run until the owner has published every generated Chapter (publishing the last one resumes it)."""
        if chapters.awaiting_review(ctx, state["course_id"]):
            interrupt({"gate": "chapter_review"})
        return {}

    fns = {"import_sources": node(ingest.import_sources), "read_pages": node(ingest.read_pages),
           "propose_roles": node(ingest.propose_roles), "found_gate": found_gate,
           "index_passages": node(lambda c, cid: search.index_course(c.db, c.search, cid)),
           "propose_outline": node(outline.propose_outline), "outline_gate": outline_gate,
           "rebuild_past_papers": node(exams.rebuild_past_papers), "generate_chapters": node(chapters.generate_chapters),
           "build_mock_exams": node(exams.build_mock_exams), "build_labs": node(labs.build_labs),
           "chapter_review_gate": chapter_review_gate}
    steps = [(name, fns[name]) for name, _ in PIPELINE]
    g = StateGraph(RunState)
    for name, fn in steps:
        g.add_node(name, fn)
    g.add_edge(START, steps[0][0])
    for (a, _), (b, _) in zip(steps, steps[1:]):
        g.add_edge(a, b)
    g.add_edge(steps[-1][0], END)
    return g.compile(checkpointer=SqliteSaver(langgraph_db))


PIPELINE = [  # the Run's steps in order, with what the Run screen calls them
    ("import_sources", "Copy the files"),
    ("read_pages", "Read every page"),
    ("propose_roles", "Propose Roles and Pairings"),
    ("found_gate", "Check what was found"),
    ("index_passages", "Index for search"),
    ("propose_outline", "Propose the outline"),
    ("outline_gate", "Fix the outline"),
    ("rebuild_past_papers", "Rebuild past papers"),  # before Chapters: Exam Weight orders Cram generation
    ("generate_chapters", "Write the Chapters"),
    ("build_mock_exams", "Write Mock exams"),
    ("build_labs", "Build Labs"),
    ("chapter_review_gate", "Review the Chapters"),  # last, so the GPU keeps working while the owner reviews
]


def pipeline(graph, course_id: int) -> list[dict]:
    """Each step of the Run with its state: done, current or waiting."""
    snap = graph.get_state(thread(course_id))
    names = [n for n, _ in PIPELINE]
    if snap.next:
        at = names.index(snap.next[0])
    else:
        at = len(names) if snap.values else -1  # finished, or not started
    return [{"name": n, "label": label, "gate": n.endswith("_gate"),
             "state": "done" if i < at else "current" if i == at else "waiting"} for i, (n, label) in enumerate(PIPELINE)]


def thread(course_id: int) -> RunnableConfig:
    return {"configurable": {"thread_id": f"course-{course_id}"}}


def run_status(graph, course_id: int, error: str | None = None) -> dict:
    if error:
        return {"status": "failed", "gate": None, "error": error}
    snap = graph.get_state(thread(course_id))
    if snap.interrupts:
        return {"status": "waiting", "gate": snap.interrupts[0].value["gate"]}
    if snap.next:
        return {"status": "running", "gate": None, "next": list(snap.next)}
    return {"status": "done" if snap.values else "not started", "gate": None}


def mean_ms(db: sqlite3.Connection, *steps: str) -> float | None:
    """Mean time per run of steps[0], counting the follow-up steps (repairs, judging) with it. Over every Course: same machine and model."""
    q = ",".join("?" * len(steps))
    row = db.execute(f"SELECT SUM(duration_ms) total, SUM(step=?) n FROM traces WHERE step IN ({q}) AND duration_ms IS NOT NULL",
                     (steps[0], *steps)).fetchone()
    return row["total"] / row["n"] if row["n"] else None


def seconds_left(db: sqlite3.Connection, cid: int) -> int | None:
    """Time left until the Run's next stop, from past step timings; None until there is a timing to go on."""
    unread = db.execute("SELECT COUNT(*) FROM pages p JOIN sources s ON s.id=p.source_id WHERE s.course_id=? AND p.text IS NULL",
                        (cid,)).fetchone()[0]
    if unread:
        work = [(unread, mean_ms(db, "read_page"))]
    else:
        sections = db.execute("SELECT COUNT(*) FROM sections s JOIN chapters c ON c.id=s.chapter_id WHERE c.course_id=? "
                              "AND c.status IN ('planned', 'generating') AND c.priority!='skip'", (cid,)).fetchone()[0]
        past = db.execute("SELECT COUNT(*) FROM sources s WHERE s.course_id=? AND s.role='past exam' AND s.excluded=0 "
                          "AND NOT EXISTS (SELECT 1 FROM exams e WHERE e.source_id=s.id)", (cid,)).fetchone()[0]
        mocks = max(0, exams.MOCK_EXAMS - db.execute("SELECT COUNT(*) FROM exams WHERE course_id=? AND kind='mock'", (cid,)).fetchone()[0])
        lab_sources = db.execute("SELECT COUNT(*) FROM sources s WHERE s.course_id=? AND s.role='lab' AND s.excluded=0 "
                                 "AND NOT EXISTS (SELECT 1 FROM labs l WHERE l.source_id=s.id)", (cid,)).fetchone()[0]
        work = [(sections, mean_ms(db, "write_section", "repair_block", "judge_grounding")),  # a Section with its repairs and judging
                (past, mean_ms(db, "rebuild_past_paper")), (mocks, mean_ms(db, "write_mock_exam")),
                (lab_sources, mean_ms(db, "build_lab", "repair_lab_step"))]
    known = [(n, ms) for n, ms in work if n and ms is not None]
    if not known and any(n for n, _ in work):
        return None
    return round(sum(n * ms for n, ms in known) / 1000)


_gpu: tuple[float, dict | None] = (0.0, None)


def gpu() -> dict | None:
    """GPU use from nvidia-smi, cached for 2 s (the Run screen polls). None without an NVIDIA GPU."""
    global _gpu
    if time.monotonic() - _gpu[0] > 2:
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                                  "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5, check=True)
            name, util, used, total = [x.strip() for x in out.stdout.splitlines()[0].split(",")]
            _gpu = (time.monotonic(), {"name": name, "util": int(util), "mem_used_mb": int(used), "mem_total_mb": int(total)})
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            _gpu = (time.monotonic(), None)
    return _gpu[1]
