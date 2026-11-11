"""The tutor: Live work that answers from the Course's material, cites pages, and streams over SSE."""

import base64
import datetime as dt
import json
import re
import uuid

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from typing import Literal

from pydantic import BaseModel, Field

from . import exams
from . import search as searchm
from .chapters import block_json, catalogue_text, checked_block, page_texts
from .context import Ctx
from .pi_step import record_owner_action, stream_pi_step
from .progression import flag_progression

CITE_RE = re.compile(r"\[([^\[\]]+?) p\.\s*(\d+)\]")
PROPOSAL_RE = re.compile(r"```proposal\s*\n(.*?)\n```", re.S)
HISTORY = 6
PASSAGES = 6

TUTOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS tutor_messages (
  id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL, course_id INTEGER NOT NULL REFERENCES courses(id),
  section_id INTEGER, role TEXT NOT NULL, text TEXT NOT NULL, citations TEXT NOT NULL DEFAULT '[]', at TEXT NOT NULL,
  proposal TEXT
);
"""


class Ask(BaseModel):
    question: str = Field(min_length=1)
    section_id: int | None = None
    conversation_id: int | None = None
    lab_step_id: int | None = None  # the Lab tutor: coaches on the learner's code, outputs and plots
    block_id: int | None = None  # the same coaching on a code_exercise Block; with style, the Block to explain again
    style: Literal["simpler", "example", "analogy", "deeper"] | None = None  # "Explain this differently" on a teaching Block
    code: str = Field("", max_length=50_000)
    outputs: list[dict] = Field([], max_length=50)  # nbformat outputs of the learner's last run


STYLES = {  # what the learner picked in "Explain this differently", as the instruction the tutor gets
    "simpler": "Explain it again more simply: plain words, shorter sentences, no notation it does not need.",
    "example": "Explain it again through one concrete worked example, with numbers or a real case.",
    "analogy": "Explain it again through an analogy, and say where the analogy stops being true.",
    "deeper": "Go deeper: why it holds, where it comes from, and how it connects to the rest of the Section.",
}
MAX_PLOTS = 4
OUTPUT_CHARS = 4000


def output_text(outputs: list[dict]) -> str:
    """The text a run printed, ANSI codes stripped and capped, for the Lab tutor."""
    parts = []
    for o in outputs:
        text = o.get("text") or (o.get("data") or {}).get("text/plain") or "\n".join(o.get("traceback") or [])
        parts.append("".join(text) if isinstance(text, list) else str(text))
    return re.sub(r"\x1b\[[0-9;]*m", "", "\n".join(parts))[-OUTPUT_CHARS:]


def save_plots(outputs: list[dict], folder) -> tuple:
    """The run's PNG plots as files, so the model sees them."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for o in outputs:
        png = (o.get("data") or {}).get("image/png")
        if png and len(paths) < MAX_PLOTS:
            p = folder / f"{uuid.uuid4().hex[:10]}.png"
            try:
                p.write_bytes(base64.b64decode("".join(png) if isinstance(png, list) else png, validate=True))
            except ValueError:
                continue  # not base64: skip the plot
            paths.append(p)
    return tuple(paths)


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def citations_in(text: str, allowed: set[tuple[str, int]]) -> list[dict]:
    """The [source p.N] citations in an answer that point at material the tutor was actually given."""
    found = dict.fromkeys((s.strip(), int(n)) for s, n in CITE_RE.findall(text))
    return [{"source": s, "page": n} for s, n in found if (s, n) in allowed]


def message_json(m) -> dict:
    return {"id": m["id"], "role": m["role"], "text": m["text"], "citations": json.loads(m["citations"]), "at": m["at"],
            "proposal": json.loads(m["proposal"]) if m["proposal"] else None}


def router(ctx: Ctx) -> APIRouter:
    db = ctx.db
    db.executescript(TUTOR_SCHEMA)
    if "proposal" not in {c["name"] for c in db.execute("PRAGMA table_info(tutor_messages)")}:
        db.execute("ALTER TABLE tutor_messages ADD COLUMN proposal TEXT")

    def section_blocks(sid: int) -> list:
        return db.execute("SELECT * FROM blocks WHERE section_id=? ORDER BY position", (sid,)).fetchall()

    def proposal_of(answer: str, cid: int, section, pages: list[dict]) -> dict | None:
        """The Block the tutor proposes, run through the same checks as a generated one; errors make it unacceptable."""
        found = PROPOSAL_RE.search(answer)
        if not found or section is None:
            return None
        ids = {b["id"] for b in section_blocks(section["id"])}
        try:
            p = json.loads(found.group(1))
            action, target = p["action"], p.get("block_id" if p["action"] == "replace" else "after_block_id")
            if action not in ("add", "replace") or not isinstance(p["block"], dict) or (target is not None and target not in ids) \
                    or (action == "replace" and target is None):
                raise ValueError("needs action add or replace, a block, and a Block id of this Section")
        except (ValueError, KeyError, TypeError) as e:
            return {"action": "add", "block": None, "flags": {"errors": [f"proposal: {e}"], "warnings": []}, "status": "open"}
        block, flags = checked_block(ctx, cid, p["block"], pages)
        return {"action": action, "target": target, "block": block, "flags": flags, "status": "open"}
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
        files: tuple = ()
        if body.lab_step_id is not None:
            step = db.execute("SELECT st.statement FROM lab_steps st JOIN labs l ON l.id=st.lab_id WHERE st.id=? AND l.course_id=?",
                              (body.lab_step_id, cid)).fetchone()
            if step is None:
                raise HTTPException(404, "no such Lab Step")
            # no Check, no Solution: the tutor can't give away what it never sees
            name, allowed = "lab_tutor", set()
            inputs = {"statement": step["statement"], "code": body.code, "outputs": output_text(body.outputs),
                      "history": history, "question": body.question}
            files = save_plots(body.outputs, ctx.course_dir(cid) / "tutor" / "plots")
        elif body.block_id is not None and body.style is None:
            block = db.execute("SELECT b.component, b.data FROM blocks b JOIN sections s ON s.id=b.section_id JOIN chapters c "
                               "ON c.id=s.chapter_id WHERE b.id=? AND c.course_id=? AND c.status='published'", (body.block_id, cid)).fetchone()
            if block is None:
                raise HTTPException(404, "no such Block")
            if block["component"] != "code_exercise":
                raise HTTPException(422, "not a code exercise Block")
            name, allowed = "lab_tutor", set()  # the task only, never the solution
            inputs = {"statement": json.loads(block["data"])["task"], "code": body.code, "outputs": "",
                      "history": history, "question": body.question}
        else:
            question = body.question
            if body.style is not None:  # explain one Block again from this Section's pages only, so its citations stay there
                block = next((b for b in section_blocks(section["id"]) if b["id"] == body.block_id), None) if section else None
                if block is None:
                    raise HTTPException(404, "no such Block in this Section")
                question = f"{STYLES[body.style]}\n\nThe Block ({block['component']}): {block['data']}"
            pages = page_texts(ctx, cid, json.loads(section["pages"])) if section else []
            passages = [] if body.style else [{"source": p["source"], "page": p["page"], "text": p["text"]}
                                              for p in searchm.search(db, ctx.search, cid, body.question, PASSAGES)]
            name, allowed = "tutor", {(p["source"], p["page"]) for p in pages + passages}
            inputs = {"section": section["title"] if section else "", "pages": pages, "passages": passages,
                      "history": history, "question": question, "catalogue": catalogue_text(ctx),
                      "blocks": "\n".join(f"[{b['id']}] {b['component']}: {b['data'][:160]}" for b in section_blocks(section["id"]))
                      if section else "(no Section open: propose nothing)"}

        def events():
            chunks = []
            try:
                for chunk in stream_pi_step(db, ctx.backend, name, inputs, ctx.course_dir(cid), files, course_id=cid):
                    chunks.append(chunk)
                    yield sse("token", {"text": chunk})
            except Exception as e:  # the Trace already has it; tell the panel
                yield sse("error", {"message": str(e)[:500]})
                return
            answer = "".join(chunks)
            cites = citations_in(answer, allowed)
            proposal = proposal_of(answer, cid, section, inputs.get("pages", [])) if name == "tutor" else None
            at = dt.datetime.now(dt.UTC).isoformat()
            first = db.execute("INSERT INTO tutor_messages (conversation_id, course_id, section_id, role, text, at) VALUES (?,?,?,?,?,?)",
                               (conv or 0, cid, body.section_id, "learner", body.question, at)).lastrowid
            cid_conv = conv or first
            if not conv:
                db.execute("UPDATE tutor_messages SET conversation_id=? WHERE id=?", (cid_conv, first))
            mid = db.execute("INSERT INTO tutor_messages (conversation_id, course_id, section_id, role, text, citations, at, proposal) "
                             "VALUES (?,?,?,?,?,?,?,?)", (cid_conv, cid, body.section_id, "tutor", answer, json.dumps(cites), at,
                                                          json.dumps(proposal, ensure_ascii=False) if proposal else None)).lastrowid
            yield sse("done", {"conversation_id": cid_conv, "message_id": mid, "citations": cites, "proposal": proposal})

        return StreamingResponse(events(), media_type="text/event-stream")

    @r.get("/api/courses/{cid}/tutor/{conversation_id}")
    def conversation(cid: int, conversation_id: int):
        rows = db.execute("SELECT * FROM tutor_messages WHERE conversation_id=? AND course_id=? ORDER BY id", (conversation_id, cid)).fetchall()
        if not rows:
            raise HTTPException(404, "no such conversation")
        return [message_json(m) for m in rows]

    @r.get("/api/courses/{cid}/tutor")
    def conversations(cid: int, section_id: int | None = None):
        """A Course's conversations, latest first: the first question, the Section it started in, the last activity."""
        rows = db.execute(
            "SELECT m.conversation_id AS id, m.text AS question, m.section_id, s.title AS section, "
            "(SELECT MAX(at) FROM tutor_messages x WHERE x.conversation_id=m.conversation_id AND x.course_id=m.course_id) AS last_at "
            "FROM tutor_messages m LEFT JOIN sections s ON s.id=m.section_id WHERE m.course_id=? AND m.id=m.conversation_id "
            "AND (? IS NULL OR m.section_id=?) ORDER BY last_at DESC, m.id DESC", (cid, section_id, section_id)).fetchall()
        return [dict(c) for c in rows]

    @r.delete("/api/courses/{cid}/tutor/{conversation_id}", status_code=204)
    def delete_conversation(cid: int, conversation_id: int):
        if not db.execute("DELETE FROM tutor_messages WHERE conversation_id=? AND course_id=?", (conversation_id, cid)).rowcount:
            raise HTTPException(404, "no such conversation")
        return Response(status_code=204)

    def open_proposal(cid: int, mid: int):
        m = db.execute("SELECT * FROM tutor_messages WHERE id=? AND course_id=?", (mid, cid)).fetchone()
        if m is None or not m["proposal"]:
            raise HTTPException(404, "no such proposal")
        p = json.loads(m["proposal"])
        if p["status"] != "open":
            raise HTTPException(409, f"this proposal was already {p['status']}")
        return m, p

    def close(mid: int, p: dict, status: str):
        db.execute("UPDATE tutor_messages SET proposal=? WHERE id=?", (json.dumps(p | {"status": status}, ensure_ascii=False), mid))

    @r.post("/api/courses/{cid}/tutor/messages/{mid}/accept")
    def accept(cid: int, mid: int):
        """Adds the proposed Block to the message's Section, or replaces the one it names; returns the Block."""
        m, p = open_proposal(cid, mid)
        if p["flags"]["errors"]:
            raise HTTPException(409, {"errors": p["flags"]["errors"]})
        blocks = section_blocks(m["section_id"])
        target = next((b for b in blocks if b["id"] == p["target"]), None)
        if p["target"] is not None and target is None:
            raise HTTPException(409, "the Block it targets is gone")
        b, flags = p["block"], p["flags"]
        values = (b["component"], json.dumps(b["data"], ensure_ascii=False), json.dumps(b.get("citations", []), ensure_ascii=False),
                  b["origin"], "ok", json.dumps(flags["warnings"], ensure_ascii=False), json.dumps(b.get("tests", []), ensure_ascii=False))
        if p["action"] == "replace":
            bid = p["target"]
            db.execute("UPDATE blocks SET component=?, data=?, citations=?, origin=?, status=?, flags=?, tests=?, previous=NULL, "
                       "review_queue=0 WHERE id=?", (*values, bid))
        else:
            pos = target["position"] + 1 if target else (blocks[-1]["position"] + 1 if blocks else 0)
            db.execute("UPDATE blocks SET position=position+1 WHERE section_id=? AND position>=?", (m["section_id"], pos))
            bid = db.execute("INSERT INTO blocks (section_id, position, component, data, citations, origin, status, flags, tests) "
                             "VALUES (?,?,?,?,?,?,?,?,?)", (m["section_id"], pos, *values)).lastrowid
        close(mid, p, "accepted")
        record_owner_action(db, cid, "tutor", {"message": mid, "action": p["action"], "block": bid}, "accepted_proposal")
        flag_progression(db, cid)
        return block_json(db.execute("SELECT * FROM blocks WHERE id=?", (bid,)).fetchone())

    @r.post("/api/courses/{cid}/tutor/messages/{mid}/dismiss", status_code=204)
    def dismiss(cid: int, mid: int):
        _, p = open_proposal(cid, mid)
        close(mid, p, "dismissed")
        return Response(status_code=204)

    return r
