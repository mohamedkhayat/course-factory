"""The Generation Run as a LangGraph graph (ADR 0001). One thread per Course; Approval Gates are interrupts."""

import sqlite3
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

    steps = [
        ("import_sources", node(ingest.import_sources)),
        ("read_pages", node(ingest.read_pages)),
        ("propose_roles", node(ingest.propose_roles)),
        ("found_gate", found_gate),
        ("index_passages", node(lambda c, cid: search.index_course(c.db, c.search, cid))),
        ("propose_outline", node(outline.propose_outline)),
        ("outline_gate", outline_gate),
        ("generate_chapters", node(chapters.generate_chapters)),
        ("build_exams", node(exams.build_exams)),
        ("build_labs", node(labs.build_labs)),
    ]
    g = StateGraph(RunState)
    for name, fn in steps:
        g.add_node(name, fn)
    g.add_edge(START, steps[0][0])
    for (a, _), (b, _) in zip(steps, steps[1:]):
        g.add_edge(a, b)
    g.add_edge(steps[-1][0], END)
    return g.compile(checkpointer=SqliteSaver(langgraph_db))


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
