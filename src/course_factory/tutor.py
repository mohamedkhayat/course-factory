"""The tutor: Live work that answers from the Course's material, cites pages, and streams over SSE."""

import datetime as dt
import json
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import exams
from . import search as searchm
from .chapters import page_texts
from .context import Ctx
from .pi_step import stream_pi_step

CITE_RE = re.compile(r"\[([^\[\]]+?) p\.\s*(\d+)\]")
HISTORY = 6
PASSAGES = 6

TUTOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS tutor_messages (
  id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL, course_id INTEGER NOT NULL REFERENCES courses(id),
  section_id INTEGER, role TEXT NOT NULL, text TEXT NOT NULL, citations TEXT NOT NULL DEFAULT '[]', at TEXT NOT NULL
);
"""


class Ask(BaseModel):
    question: str = Field(min_length=1)
    section_id: int | None = None
    conversation_id: int | None = None


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def citations_in(text: str, allowed: set[tuple[str, int]]) -> list[dict]:
    """The [source p.N] citations in an answer that point at material the tutor was actually given."""
    found = dict.fromkeys((s.strip(), int(n)) for s, n in CITE_RE.findall(text))
    return [{"source": s, "page": n} for s, n in found if (s, n) in allowed]


def router(ctx: Ctx) -> APIRouter:
    db = ctx.db
    db.executescript(TUTOR_SCHEMA)
    r = APIRouter()

    @r.post("/api/courses/{cid}/tutor")
    def ask(cid: int, body: Ask):
        if db.execute("SELECT 1 FROM courses WHERE id=?", (cid,)).fetchone() is None:
            raise HTTPException(404, "no such Course")
        if db.execute("SELECT 1 FROM copies c JOIN exams e ON e.id=c.exam_id WHERE e.course_id=? AND c.handed_in_at IS NULL "
                      "AND c.deadline > ?", (cid, exams.now().isoformat())).fetchone():
            raise HTTPException(409, "the tutor is hidden during an exam")
        section = None
        if body.section_id is not None:
            section = db.execute("SELECT s.* FROM sections s JOIN chapters c ON c.id=s.chapter_id WHERE s.id=? AND c.course_id=?",
                                 (body.section_id, cid)).fetchone()
            if section is None:
                raise HTTPException(404, "no such Section")
        conv = body.conversation_id
        if conv is not None and db.execute("SELECT 1 FROM tutor_messages WHERE conversation_id=? AND course_id=?", (conv, cid)).fetchone() is None:
            raise HTTPException(404, "no such conversation")
        history = [{"role": m["role"], "text": m["text"]} for m in db.execute(
            "SELECT role, text FROM tutor_messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?", (conv, HISTORY))][::-1] if conv else []
        pages = page_texts(ctx, cid, json.loads(section["pages"])) if section else []
        passages = [{"source": p["source"], "page": p["page"], "text": p["text"]}
                    for p in searchm.search(db, ctx.search, cid, body.question, PASSAGES)]
        allowed = {(p["source"], p["page"]) for p in pages + passages}
        inputs = {"section": section["title"] if section else "", "pages": pages, "passages": passages,
                  "history": history, "question": body.question}

        def events():
            chunks = []
            try:
                for chunk in stream_pi_step(db, ctx.backend, "tutor", inputs, ctx.course_dir(cid), course_id=cid):
                    chunks.append(chunk)
                    yield sse("token", {"text": chunk})
            except Exception as e:  # the Trace already has it; tell the panel
                yield sse("error", {"message": str(e)[:500]})
                return
            answer = "".join(chunks)
            cites = citations_in(answer, allowed)
            at = dt.datetime.now(dt.UTC).isoformat()
            first = db.execute("INSERT INTO tutor_messages (conversation_id, course_id, section_id, role, text, at) VALUES (?,?,?,?,?,?)",
                               (conv or 0, cid, body.section_id, "learner", body.question, at)).lastrowid
            cid_conv = conv or first
            if not conv:
                db.execute("UPDATE tutor_messages SET conversation_id=? WHERE id=?", (cid_conv, first))
            mid = db.execute("INSERT INTO tutor_messages (conversation_id, course_id, section_id, role, text, citations, at) "
                             "VALUES (?,?,?,?,?,?,?)", (cid_conv, cid, body.section_id, "tutor", answer, json.dumps(cites), at)).lastrowid
            yield sse("done", {"conversation_id": cid_conv, "message_id": mid, "citations": cites})

        return StreamingResponse(events(), media_type="text/event-stream")

    @r.get("/api/courses/{cid}/tutor/{conversation_id}")
    def conversation(cid: int, conversation_id: int):
        rows = db.execute("SELECT * FROM tutor_messages WHERE conversation_id=? AND course_id=? ORDER BY id", (conversation_id, cid)).fetchall()
        if not rows:
            raise HTTPException(404, "no such conversation")
        return [{"id": m["id"], "role": m["role"], "text": m["text"], "citations": json.loads(m["citations"]), "at": m["at"]} for m in rows]

    return r
