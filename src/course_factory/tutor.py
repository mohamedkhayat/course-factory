"""The tutor: Live work that answers from the Course's material, cites pages, and streams over SSE."""

import asyncio
import base64
import datetime as dt
import hashlib
import json
import re
import threading
import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import iterate_in_threadpool
from fastapi.responses import StreamingResponse
from typing import Literal

from pydantic import BaseModel, Field

from . import exams
from . import search as searchm
from .chapters import block_json, catalogue_text, checked_blocks, page_texts
from .context import Ctx
from .pi_step import record_owner_action, stream_pi_step
from .progression import flag_progression

CITE_RE = re.compile(r"\[([^\[\]]+?) p\.\s*(\d+)\]")
PROPOSAL_RE = re.compile(r"```proposal\s*\n(.*?)\n```", re.S)
HISTORY = 6
PASSAGES = 6
MAX_CHANGES = 12

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


def shown(p: dict | None) -> dict | None:
    """A stored proposal as the panel gets it: always a list of changes (older ones held a single change), never the undo snapshot."""
    if p is None:
        return None
    return {"changes": p.get("changes") or ([p] if p.get("block") else []), "flags": p["flags"], "status": p["status"],
            "can_undo": "undo" in p}


def message_json(m) -> dict:
    return {"id": m["id"], "role": m["role"], "text": m["text"], "citations": json.loads(m["citations"]), "at": m["at"],
            "proposal": shown(json.loads(m["proposal"]) if m["proposal"] else None)}


def planned(blocks: list[dict], changes: list[dict]) -> list[dict]:
    """The Section's Blocks as the changes would leave them, in order, each with a "mark": added, replaced, moved, removed
    (a removed Block stays in the list, marked) or None. Raises ValueError when a change names a Block that is gone."""
    out = [dict(b, mark=None) for b in blocks]

    def at(bid):
        i = next((i for i, b in enumerate(out) if b["id"] == bid and b["mark"] != "removed"), None)
        if i is None:
            raise ValueError("a Block it targets is gone")
        return i
    for n, c in enumerate(changes):
        if c["action"] == "add":
            new = {"id": -1 - n, "status": "ok", "flags": c["flags"]["warnings"], "citations": [], "tests": [], **c["block"], "mark": "added"}
            out.insert(at(c["target"]) + 1 if c["target"] is not None else len(out), new)
        elif c["action"] == "replace":
            i = at(c["target"])
            out[i] = {**out[i], "citations": [], "tests": [], **c["block"], "flags": c["flags"]["warnings"], "status": "ok", "mark": "replaced"}
        elif c["action"] == "remove":
            out[at(c["target"])]["mark"] = "removed"
        else:
            b = out.pop(at(c["target"]))
            out.insert(at(c["after"]) + 1 if c.get("after") is not None else 0, b | {"mark": b["mark"] or "moved"})
    return [b | {"position": i} for i, b in enumerate(out)]


def router(ctx: Ctx) -> APIRouter:
    db = ctx.db
    db.executescript(TUTOR_SCHEMA)
    if "proposal" not in {c["name"] for c in db.execute("PRAGMA table_info(tutor_messages)")}:
        db.execute("ALTER TABLE tutor_messages ADD COLUMN proposal TEXT")

    def section_blocks(sid: int) -> list:
        return db.execute("SELECT * FROM blocks WHERE section_id=? ORDER BY position", (sid,)).fetchall()

    def signature(sid: int) -> str:
        return hashlib.sha1(json.dumps([[b["id"], b["position"], b["component"], b["data"]] for b in section_blocks(sid)]).encode()).hexdigest()

    def proposal_of(answer: str, cid: int, section, pages: list[dict]) -> dict | None:
        """The changes the tutor proposes to the Section; its new Blocks go through the same checks as generated ones, and
        any error makes the whole proposal unacceptable."""
        found = PROPOSAL_RE.search(answer)
        if not found or section is None:
            return None
        rows = {b["id"]: b for b in section_blocks(section["id"])}
        try:
            p = json.loads(found.group(1))
            raw = p["changes"] if "changes" in p else [p]
            if not isinstance(raw, list) or not 0 < len(raw) <= MAX_CHANGES:
                raise ValueError(f"needs 1 to {MAX_CHANGES} changes")
            changes = []
            for c in raw:
                action, after = c["action"], c.get("after_block_id")
                target = after if action == "add" else c.get("block_id")
                if action not in ("add", "replace", "move", "remove") or any(t is not None and t not in rows for t in (target, after)) \
                        or (action != "add" and target is None) or (action == "move" and after == target) \
                        or (action in ("add", "replace") and not isinstance(c["block"], dict)):
                    raise ValueError("each change needs action add, replace, move or remove, a block when it adds or replaces, "
                                     "and Block ids of this Section")
                changes.append({"action": action, "target": target, "after": after if action == "move" else None,
                                "block": c["block"] if action in ("add", "replace") else block_json(rows[target]),  # the Block as it is, for the card
                                "flags": {"errors": [], "warnings": []}})
            new = [c for c in changes if c["action"] in ("add", "replace")]
            if new:  # one check for all of them: one grounding call, not one per Block
                blocks, flags = checked_blocks(ctx, cid, [c["block"] for c in new], pages)
                for c, block, f in zip(new, blocks, flags):
                    c["block"], c["flags"] = block, f
            planned([block_json(b) for b in rows.values()], changes)  # the changes must work one after the other
        except (ValueError, KeyError, TypeError) as e:  # said plainly: the tutor gets this text back when the learner asks it to fix it
            why = f'a change has no "{e.args[0]}" key' if isinstance(e, KeyError) else \
                f"the JSON doesn't parse: {e}" if isinstance(e, json.JSONDecodeError) else str(e)
            return {"changes": [], "flags": {"errors": [f"proposal: {why}"], "warnings": []}, "status": "open"}
        return {"changes": changes, "status": "open",
                "flags": {k: [m for c in changes for m in c["flags"][k]] for k in ("errors", "warnings")}}
    r = APIRouter()

    @r.post("/api/courses/{cid}/tutor")
    def ask(cid: int, body: Ask, request: Request):
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
                      "blocks": "\n".join(f"[{b['id']}] {b['component']}: {b['data'][:4000]}" for b in section_blocks(section["id"]))
                      if section else "(no Section open: propose nothing)"}

        stop = threading.Event()

        async def watched():
            """The answer's events, until the learner stops it: the page closing the request kills the model, even mid-thought."""
            it, nxt = iterate_in_threadpool(events()), None
            try:
                while True:
                    nxt = nxt or asyncio.ensure_future(it.__anext__())
                    if not (await asyncio.wait({nxt}, timeout=1))[0]:
                        if await request.is_disconnected():
                            return
                        continue
                    try:
                        chunk = nxt.result()
                    except StopAsyncIteration:
                        return
                    nxt = None
                    yield chunk
            finally:
                stop.set()

        def events():
            chunks = []
            try:
                for chunk in stream_pi_step(db, ctx.backend, name, inputs, ctx.course_dir(cid), files, course_id=cid, stop=stop):
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
            yield sse("done", {"conversation_id": cid_conv, "message_id": mid, "question_id": first, "citations": cites, "proposal": shown(proposal)})

        return StreamingResponse(watched(), media_type="text/event-stream")

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

    @r.delete("/api/courses/{cid}/tutor/messages/{mid}", status_code=204)
    def take_back(cid: int, mid: int):
        """Removes a message and everything after it in its conversation: to take a question back, or to edit it and ask again."""
        m = db.execute("SELECT * FROM tutor_messages WHERE id=? AND course_id=?", (mid, cid)).fetchone()
        if m is None:
            raise HTTPException(404, "no such message")
        later = db.execute("SELECT proposal FROM tutor_messages WHERE conversation_id=? AND course_id=? AND id>=?",
                           (m["conversation_id"], cid, mid)).fetchall()
        if any(r["proposal"] and "undo" in json.loads(r["proposal"]) for r in later):  # its Undo would go with it
            raise HTTPException(409, "a change from here on was applied to the Section: undo it first, or keep these messages")
        db.execute("DELETE FROM tutor_messages WHERE conversation_id=? AND course_id=? AND id>=?", (m["conversation_id"], cid, mid))
        return Response(status_code=204)

    def proposal(cid: int, mid: int, status: str = "open"):
        m = db.execute("SELECT * FROM tutor_messages WHERE id=? AND course_id=?", (mid, cid)).fetchone()
        if m is None or not m["proposal"]:
            raise HTTPException(404, "no such proposal")
        p = json.loads(m["proposal"])
        if p["status"] != status:
            raise HTTPException(409, f"this proposal was already {p['status'].replace('_', ' ')}")
        return m, p | {"changes": shown(p)["changes"]}

    def close(mid: int, p: dict, status: str):
        db.execute("UPDATE tutor_messages SET proposal=? WHERE id=?", (json.dumps(p | {"status": status}, ensure_ascii=False), mid))

    def plan(m, p) -> list[dict]:
        try:
            return planned([block_json(b) for b in section_blocks(m["section_id"])], p["changes"])
        except ValueError as e:
            raise HTTPException(409, str(e))

    @r.get("/api/courses/{cid}/tutor/messages/{mid}/preview")
    def preview(cid: int, mid: int):
        """The message's Section as its open proposal would leave it: every Block in order, the changed ones marked."""
        return plan(*proposal(cid, mid))

    @r.post("/api/courses/{cid}/tutor/messages/{mid}/accept")
    def accept(cid: int, mid: int):
        """Applies the proposal's changes to the message's Section and keeps what the Section was, for the rollback;
        returns the Section's Blocks."""
        m, p = proposal(cid, mid)
        if p["flags"]["errors"]:
            raise HTTPException(409, {"errors": p["flags"]["errors"]})
        sid = m["section_id"]
        after, before = plan(m, p), [dict(b) for b in section_blocks(sid)]
        for b in after:
            values = (b["component"], json.dumps(b["data"], ensure_ascii=False), json.dumps(b["citations"], ensure_ascii=False),
                      b["origin"], "ok", json.dumps(b["flags"], ensure_ascii=False), json.dumps(b["tests"], ensure_ascii=False))
            if b["mark"] == "removed":
                db.execute("DELETE FROM blocks WHERE id=?", (b["id"],))
            elif b["mark"] == "added":
                db.execute("INSERT INTO blocks (section_id, position, component, data, citations, origin, status, flags, tests) "
                           "VALUES (?,?,?,?,?,?,?,?,?)", (sid, b["position"], *values))
            elif b["mark"] == "replaced":
                db.execute("UPDATE blocks SET position=?, component=?, data=?, citations=?, origin=?, status=?, flags=?, tests=?, "
                           "previous=NULL, review_queue=0 WHERE id=?", (b["position"], *values, b["id"]))
            else:
                db.execute("UPDATE blocks SET position=? WHERE id=?", (b["position"], b["id"]))
        flag_progression(db, cid)
        close(mid, p | {"undo": before, "after": signature(sid)}, "accepted")
        record_owner_action(db, cid, "tutor", {"message": mid, "changes": [[c["action"], c["target"]] for c in p["changes"]]}, "accepted_proposal")
        return [block_json(b) for b in section_blocks(sid)]

    @r.post("/api/courses/{cid}/tutor/messages/{mid}/rollback")
    def rollback(cid: int, mid: int):
        """Puts the Section back as it was before the proposal was accepted, unless it changed again since."""
        m, p = proposal(cid, mid, "accepted")
        sid = m["section_id"]
        if "undo" not in p:
            raise HTTPException(409, "this proposal was accepted before rollbacks were kept")
        if p["after"] != signature(sid):
            raise HTTPException(409, "the Section changed since this was accepted, so it can't be rolled back")
        db.execute("DELETE FROM blocks WHERE section_id=?", (sid,))
        for b in p["undo"]:  # the rows whole, ids included: notes and results stay attached
            db.execute(f"INSERT INTO blocks ({', '.join(b)}) VALUES ({', '.join('?' * len(b))})", tuple(b.values()))
        flag_progression(db, cid)
        close(mid, {k: v for k, v in p.items() if k not in ("undo", "after")}, "rolled_back")
        record_owner_action(db, cid, "tutor", {"message": mid}, "rolled_back_proposal")
        return [block_json(b) for b in section_blocks(sid)]

    @r.post("/api/courses/{cid}/tutor/messages/{mid}/dismiss", status_code=204)
    def dismiss(cid: int, mid: int):
        _, p = proposal(cid, mid)
        close(mid, p, "dismissed")
        return Response(status_code=204)

    return r
