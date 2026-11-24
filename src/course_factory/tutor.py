"""The tutor: Live work that answers from the Course's material, cites pages, and streams over SSE."""

import asyncio
import base64
import datetime as dt
import hashlib
import json
import re
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import iterate_in_threadpool
from fastapi.responses import StreamingResponse
from typing import Literal

from pydantic import BaseModel, Field

from . import cram, exams
from . import memory
from . import search as searchm
from .chapters import block_json, catalogue_text, checked_blocks, language_rule, page_texts
from .context import Ctx
from .learner import now, refresh_patterns
from .pi_step import attach_checks, escape_latex, record_owner_action, stream_pi_step
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


MAX_IMAGES = 6
IMAGE_BYTES = 8_000_000
MAX_CONTEXT_PAGES = 300  # about 125k tokens of page text: half the model's 262k window, the rest for the prompt and answer
IMAGE_URL = re.compile(r"data:image/(png|jpeg|webp);base64,(.+)", re.S)


Mode = Literal["step", "explain", "test", "beyond"]  # how much the tutor does (#30); unset: Step on a quoted line of a theoretical Course


class Anchor(BaseModel):
    source: str
    page: int


ANSWER_ID = r"^[A-Za-z0-9_-]{8,64}$"  # the page's id for an answer it streams: see watched


class Ask(BaseModel):
    question: str = Field(min_length=1)
    section_id: int | None = None
    conversation_id: int | None = None
    lab_step_id: int | None = None  # the Lab tutor: coaches on the learner's code, outputs and plots
    block_id: int | None = None  # the same coaching on a code_exercise Block; with style, the Block to explain again
    style: Literal["simpler", "example", "analogy", "deeper"] | None = None  # "Explain this differently" on a teaching Block
    mode: Mode | None = None  # Step, Explain, Test me or Beyond the course (#30)
    anchor: Anchor | None = None  # "Explain this step" on a selection: the page it was selected on (the Block's cited page, a page preview)
    code: str = Field("", max_length=50_000)
    outputs: list[dict] = Field([], max_length=50)  # nbformat outputs of the learner's last run
    images: list[str] = Field([], max_length=MAX_IMAGES)  # data: URLs the learner pasted or picked, for the model to see
    answer: str | None = Field(None, pattern=ANSWER_ID)  # the page's id for this answer: see watched
    attached: list[int] = Field([], max_length=12)  # Block ids the learner attached, from any Section of the Course
    items: dict[int, str] = {}  # attached Block id -> the id of the diagram item the question is about
    sections: list[int] = Field([], max_length=60)  # Sections (a whole Chapter is its Sections) the learner added as context


STYLES = {  # what the learner picked in "Explain this differently", as the instruction the tutor gets
    "simpler": "Explain it again more simply: plain words, shorter sentences, no notation it does not need.",
    "example": "Explain it again through one concrete worked example, with numbers or a real case.",
    "analogy": "Explain it again through an analogy, and say where the analogy stops being true.",
    "deeper": "Go deeper: why it holds, where it comes from, and how it connects to the rest of the Section.",
}
STEP_WORDS = 120
PAGES_BEFORE = 3  # shortcut: a Step answer sees the anchor and the 3 pages before it, not every earlier page; widen if it misses the setup
ANCHOR_HITS, ANCHOR_SHARE = 8, 0.45  # set on the owner's 83 optimisation questions: 25 anchored, each to the page it was pasted from
MODES = {
    "step": ("Mode: Step. The learner quoted a line of the course{where} and wants to know how it follows. Give only the missing "
             f"step or steps, in the course's notation, reusing the numbers and objects already on that page: at most {STEP_WORDS} words "
             "of text and at most one display chain of equations. Use only what that page and the pages before it show and the Concepts "
             "known so far: no new theorem, example, table or Block. Cite that page as {cite}, the Source's full name. When the course does not justify the step, say so in "
             "one line and mark your explanation as not from the course. Stop once the step is given: no summary, no question for the learner."),
    "explain": ("Mode: Explain. Answer what was asked, within what the course covers: no theorem, table or analysis the course does not "
                "have. When the learner asks how one line follows (from the course or from your last answer), give only that step, in a "
                "few lines. Stop once it is answered, with no question for the learner unless the Challenge applies."),
    "test": "Mode: Test me. The learner wants to be tested: ask one question at a time on what they ask about, and Challenge each answer.",
    "beyond": ("Mode: Beyond the course. The learner wants the wider theory around their last question: where it comes from, why it "
               "holds, how it generalises. Mark every part that is not in the material as not from the course."),
}


def words(text: str | None) -> set[str]:
    return set(re.findall(r"[^\W\d_]{3,}", (text or "").lower()))


def anchor(db, cid: int, text: str) -> dict | None:
    """The course page a quoted line comes from: the page sharing the most words with the message, when enough of the message's
    words are on it. Formulas alone don't match (their extracted text differs), so a paste of symbols only is not anchored."""
    w = words(text)
    if len(w) < ANCHOR_HITS:
        return None
    best, hits = None, 0
    for r in db.execute("SELECT s.name, p.n, p.text FROM pages p JOIN sources s ON s.id=p.source_id WHERE s.course_id=? AND s.excluded=0 "
                        "AND p.readable=1 ORDER BY s.name, p.n", (cid,)):
        if (h := len(w & words(r["text"]))) > hits:
            best, hits = r, h
    if best is None or hits < ANCHOR_HITS or hits / len(w) < ANCHOR_SHARE:
        return None
    return {"source": best["name"], "page": best["n"]}


def given_anchor(db, cid: int, at: Anchor | None) -> dict | None:
    """The page the learner selected on, when it is a readable page of this Course; else the selection is anchored by its words."""
    if at and db.execute("SELECT 1 FROM pages p JOIN sources s ON s.id=p.source_id WHERE s.course_id=? AND s.name=? AND p.n=? "
                         "AND s.excluded=0 AND p.readable=1", (cid, at.source, at.page)).fetchone():
        return {"source": at.source, "page": at.page}
    return None


def mode_of(db, cid: int, asked: str | None, anchored: dict | None) -> str:
    if asked:
        return asked
    theoretical = db.execute("SELECT subject FROM courses WHERE id=?", (cid,)).fetchone()["subject"] == "theoretical"
    return "step" if theoretical and anchored else "explain"


def mode_text(mode: str, anchored: dict | None) -> str:
    at = f"{anchored['source']} p.{anchored['page']}" if anchored else ""
    return MODES[mode].replace("{where}", f" ({at})" if anchored else "").replace("{cite}", f"[{at}]")


def step_pages(anchored: dict) -> list[dict]:
    """A Step answer's material: the anchored page and the pages before it in the same Source, never one after."""
    return [{"source": anchored["source"], "page": n} for n in range(max(1, anchored["page"] - PAGES_BEFORE), anchored["page"] + 1)]


def step_words(answer: str) -> int:
    """An answer's words, its display maths left out (the one chain a Step answer may show)."""
    return len(re.sub(r"\$\$.*?\$\$", " ", answer, flags=re.S).split())


def check_step(db, cid: int, step: str, mode: str, answer: str) -> None:
    """Records a Step answer's length on its Trace; over the budget it is the Failure class long-step-answer (shown, not refused)."""
    if mode != "step":
        return
    n = step_words(answer)
    trace = db.execute("SELECT MAX(id) FROM traces WHERE course_id=? AND step=?", (cid, step)).fetchone()[0]
    attach_checks(db, trace, {"errors": [], "warnings": [f"step answer: {n} words, over the {STEP_WORDS}-word budget"] if n > STEP_WORDS else []})


MAX_PLOTS = 4
OUTPUT_CHARS = 4000


def output_text(outputs: list[dict]) -> str:
    """The text a run printed, ANSI codes stripped and capped, for the Lab tutor."""
    parts = []
    for o in outputs:
        text = o.get("text") or (o.get("data") or {}).get("text/plain") or "\n".join(o.get("traceback") or [])
        parts.append("".join(text) if isinstance(text, list) else str(text))
    return re.sub(r"\x1b\[[0-9;]*m", "", "\n".join(parts))[-OUTPUT_CHARS:]


def context_text(ctx, cid: int, ids: list[int], open_id: int | None, pages: list[dict], sources: list[str] = ()) -> tuple[str, list[dict]]:
    """The Sections and whole source documents the learner added as context, as the prompt's text and the pages it may cite:
    each Section's pages (those not already given) and its Block ids, so the tutor can name them, then each document's pages."""
    if not ids and not sources:
        return "", []
    db = ctx.db
    rows = db.execute(f"SELECT s.id, s.title, s.pages, c.title chapter FROM sections s JOIN chapters c ON c.id=s.chapter_id "
                      f"WHERE c.course_id=? AND s.id IN ({','.join('?' * len(ids))}) ORDER BY c.position, s.position",
                      (cid, *ids)).fetchall() if ids else []
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "no such Section in this Course")
    seen = {(p["source"], p["page"]) for p in pages}
    out, cited = [], []
    for r in rows:
        if r["id"] == open_id:
            continue  # its pages and Blocks are in the prompt already
        refs = [p for p in json.loads(r["pages"]) if (p["source"], p["page"]) not in seen]
        seen |= {(p["source"], p["page"]) for p in refs}
        got = page_texts(ctx, cid, refs)
        cited += got
        if len(cited) > MAX_CONTEXT_PAGES:
            raise HTTPException(422, f"that context is over {MAX_CONTEXT_PAGES} pages: add fewer Sections or documents")
        blocks = "\n".join(f"  [{b['id']}] {b['component']}: {b['data'][:300]}" for b in db.execute(
            "SELECT id, component, data FROM blocks WHERE section_id=? ORDER BY position", (r["id"],)))
        out.append(f"Section \"{r['title']}\" (Chapter \"{r['chapter']}\")\nPages: {json.dumps(got, ensure_ascii=False)}\nBlocks:\n{blocks}")
    for name in dict.fromkeys(sources):
        row = db.execute("SELECT pages FROM sources WHERE course_id=? AND name=? AND excluded=0", (cid, name)).fetchone()
        if row is None:
            raise HTTPException(404, f"no such source in this Course: {name}")
        refs = [{"source": name, "page": n} for n in range(1, row["pages"] + 1) if (name, n) not in seen]
        seen |= {(name, r["page"]) for r in refs}
        got = page_texts(ctx, cid, refs)
        cited += got
        if len(cited) > MAX_CONTEXT_PAGES:
            raise HTTPException(422, f"that context is over {MAX_CONTEXT_PAGES} pages: add fewer Sections or documents")
        out.append(f"Whole document \"{name}\"\nPages: {json.dumps(got, ensure_ascii=False)}")
    if not out:
        return "", []
    return ("The learner added these Sections and documents as context: answer from them too, and cite their pages like the Section's.\n\n"
            + "\n\n".join(out)), cited


def save_images(urls: list[str], folder) -> tuple:
    """The learner's images (data: URLs) as files, so the model sees them. Anything else is refused, not skipped: the learner
    would think the tutor saw it."""
    paths = []
    for url in urls:
        m = IMAGE_URL.fullmatch(url)
        try:
            raw = base64.b64decode(m.group(2), validate=True) if m else b""
        except ValueError:
            raw = b""
        if not raw or len(raw) > IMAGE_BYTES:
            raise HTTPException(422, "send PNG, JPEG or WebP images under 8 MB")
        folder.mkdir(parents=True, exist_ok=True)
        paths.append(p := folder / f"{uuid.uuid4().hex[:10]}.{'jpg' if m.group(1) == 'jpeg' else m.group(1)}")
        p.write_bytes(raw)
    return tuple(paths)


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


BARE_CITE_RE = re.compile(r"\[p\.\s*(\d+)\]")


def sourced(text: str, anchored: dict | None) -> str:
    """A Step answer's bare [p.N] is a page of the anchored Source (1 of the 2 replayed Step answers cited so, Nov 20)."""
    return BARE_CITE_RE.sub(lambda m: f"[{anchored['source']} p.{m.group(1)}]", text) if anchored else text


def citations_in(text: str, allowed: set[tuple[str, int]]) -> list[dict]:
    """The [source p.N] citations in an answer that point at material the tutor was actually given."""
    found = dict.fromkeys((s.strip(), int(n)) for s, n in CITE_RE.findall(text))
    return [{"source": s, "page": n} for s, n in found if (s, n) in allowed]


def proposal_json(text: str):
    """A proposal's JSON. The model's usual slips are one "}" too many after a Block's data (2 of 25 real proposals), which
    closes the Block early, a bare quote inside a string, as in code like `"ERROR" in x`, and the last "}" left out (2 each
    of the 4 that failed, Nov 14): where parsing stops, drop the "}" or escape the quote just before, or close the object at
    the end, a few times at most. LaTeX the model left unescaped
    (\\min, \\frac) is escaped first, as for every other model output."""
    text = escape_latex(text)
    for _ in range(12):
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            j = len(text[:e.pos].rstrip()) - 1
            if e.pos >= len(text.rstrip()) and e.msg.startswith("Expecting ','"):  # the input ended with the object still open
                text = text.rstrip() + "}"
                continue
            if j < 0 or text[j] not in '}"':
                raise
            text = text[:j] + ("" if text[j] == "}" else '\\"') + text[j + 1:]
    return json.loads(text)


INLINE_CITE_RE = re.compile(r"\s*\[([^\[\]]+?) p\.\s*(\d+)\]|\s*\[Block \d+\]")


def cited_out(block: dict, allowed: set[tuple[str, int]]) -> dict:
    """A tutor Block with its inline [source p.N] moved into its citations and its [Block N] dropped: in a Block they are
    dead text (the chips under it are the links), and Block ids change when a Block is replaced. A page the tutor was not
    given stays in the text."""
    cites = list(block.get("citations") or [])

    def out(m: re.Match) -> str:
        if m.group(1) is None:
            return ""
        key = (m.group(1).strip(), int(m.group(2)))
        if key not in allowed:
            return m.group(0)
        if not any((c.get("source"), c.get("page")) == key for c in cites if isinstance(c, dict)):
            cites.append({"source": key[0], "page": key[1]})
        return ""

    def walk(v):
        if isinstance(v, str):
            return INLINE_CITE_RE.sub(out, v)
        if isinstance(v, list):
            return [walk(x) for x in v]
        return {k: walk(x) for k, x in v.items()} if isinstance(v, dict) else v

    return {**block, "data": walk(block.get("data")), "citations": cites}


def shown(p: dict | None) -> dict | None:
    """A stored proposal as the panel gets it: always a list of changes (older ones held a single change), never the undo snapshot."""
    if p is None:
        return None
    return {"changes": p.get("changes") or ([p] if p.get("block") else []), "flags": p["flags"], "status": p["status"],
            "can_undo": "undo" in p}


def message_json(db, m) -> dict:
    return {"id": m["id"], "role": m["role"], "text": m["text"], "citations": json.loads(m["citations"]), "at": m["at"],
            "proposal": shown(json.loads(m["proposal"]) if m["proposal"] else None), "remembered": memory.remembered_json(db, m["remembered"]),
            "mode": m["mode"], "anchor": json.loads(m["anchor"]) if m["anchor"] else None}


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


def exam_running(db, cid: int) -> bool:
    """The tutor and the Course chat are hidden while a Copy is open."""
    return db.execute("SELECT 1 FROM copies c JOIN exams e ON e.id=c.exam_id WHERE e.course_id=? AND c.handed_in_at IS NULL "
                      "AND c.deadline > ?", (cid, exams.now().isoformat())).fetchone() is not None


def reading(question: str, passages: list[dict], extra: list[dict] = ()) -> list[dict]:
    """The first steps of the activity line: the search and the pages the answer is grounded on."""
    if not passages:
        return []
    seen = list(dict.fromkeys((p["source"], p["page"]) for p in [*passages, *extra]))
    return [{"kind": "search", "label": f"Searching for “{question[:60]}”"},
            *({"kind": "read", "label": f"Reading {s} p.{n}", "source": s, "page": n} for s, n in seen[:PASSAGES + 4])]


def attached_text(db, cid: int, ids: list[int], items: dict[int, str] = {}) -> str:
    """The Blocks the learner attached to a question, from any Section of the Course."""
    rows = db.execute(f"SELECT b.id, b.component, b.data, s.title FROM blocks b JOIN sections s ON s.id=b.section_id JOIN chapters c "
                      f"ON c.id=s.chapter_id WHERE c.course_id=? AND b.id IN ({','.join('?' * len(ids))})", (cid, *ids)).fetchall()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "no such Block in this Course")
    about = {r["id"]: next((i for i in json.loads(r["data"]).get("items", []) if isinstance(i, dict) and i.get("id") == items[r["id"]]), None)
             if r["id"] in items else None for r in rows}
    return "\n\nThe learner attached these Blocks:\n" + "\n".join(
        f"[{r['id']}] {r['component']} (Section \"{r['title']}\"): {r['data'][:4000]}"
        + (f"\nThe question is about this item of the diagram: {about[r['id']]['label']}: {about[r['id']]['explanation']}" if about[r["id"]] else "")
        for r in rows)


ANSWERS: dict[str, dict] = {}  # answers by the page's id for them, so a page whose connection dropped can find its answer

async def watched(request: Request, events, stop: threading.Event, answer: str | None = None):
    """The answer's events. With an `answer` id a dropped connection doesn't stop it: it runs to the end and is saved, the page
    finds it at GET answers/{id}, and only POST answers/{id}/stop stops it. Without one, the page closing the request kills the model."""
    if answer is not None:
        state = ANSWERS[answer] = {"stop": stop, "done": False, "conversation_id": None, "error": None}
        while len(ANSWERS) > 200:
            ANSWERS.pop(next(iter(ANSWERS)))
        loop, q = asyncio.get_running_loop(), asyncio.Queue()

        def drain():  # on its own thread, so it runs on when the response goes away
            try:
                for chunk in events:
                    event, _, data = chunk.partition("\ndata: ")
                    if event == "event: done":
                        state["conversation_id"] = json.loads(data)["conversation_id"]
                    elif event == "event: error":
                        state["error"] = json.loads(data)["message"]
                    loop.call_soon_threadsafe(q.put_nowait, chunk)
            except Exception as e:
                state["error"] = str(e)[:500]
                loop.call_soon_threadsafe(q.put_nowait, sse("error", {"message": state["error"]}))
            finally:
                state["done"] = True
                stop.set()
                loop.call_soon_threadsafe(q.put_nowait, None)
        threading.Thread(target=drain, daemon=True).start()
        while (chunk := await q.get()) is not None:
            yield chunk
        return
    it, nxt, checked = iterate_in_threadpool(events), None, time.monotonic()
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
            if time.monotonic() - checked > 0.5:  # while tokens keep coming the wait above never times out: check here too
                checked = time.monotonic()
                if await request.is_disconnected():
                    return
            yield chunk
    finally:
        stop.set()


def router(ctx: Ctx) -> APIRouter:
    db = ctx.db
    db.executescript(TUTOR_SCHEMA)
    have = {c["name"] for c in db.execute("PRAGMA table_info(tutor_messages)")}
    for column in ("proposal", "kind", "parts", "drill", "activity", "remembered", "style", "mode", "anchor"):  # mode, anchor: the tutor reply's mode and the course page it explains (#30); kind 'chat': a Course chat message (chat.py); parts, drill, activity are its; remembered: the id of the fact it made; style: Explain differently
        if column not in have:
            db.execute(f"ALTER TABLE tutor_messages ADD COLUMN {column} TEXT")

    def section_blocks(sid: int) -> list:
        return db.execute("SELECT * FROM blocks WHERE section_id=? ORDER BY position", (sid,)).fetchall()

    def signature(sid: int) -> str:
        return hashlib.sha1(json.dumps([[b["id"], b["position"], b["component"], b["data"]] for b in section_blocks(sid)]).encode()).hexdigest()

    def proposal_of(answer: str, cid: int, section, pages: list[dict], allowed: set[tuple[str, int]]) -> dict | None:
        """The changes the tutor proposes to the Section; its new Blocks go through the same checks as generated ones, and
        any error makes the whole proposal unacceptable."""
        found = ([None] + list(PROPOSAL_RE.finditer(answer)))[-1]  # the last: a model that changes its mind mid-answer means its final one
        if not found or section is None:
            return None
        rows = {b["id"]: b for b in section_blocks(section["id"])}
        try:
            p = proposal_json(found.group(1))
            raw = p["changes"] if "changes" in p else [p]
            for c in raw if isinstance(raw, list) else []:  # what the extra brace pushed out of the Block goes back in
                if isinstance(c, dict) and isinstance(c.get("block"), dict):
                    c["block"].update({k: c.pop(k) for k in ("citations", "origin", "tests") if k in c and k not in c["block"]})
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
                                "block": cited_out(c["block"], allowed) if action in ("add", "replace") else block_json(rows[target]),  # the Block as it is, for the card
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
        if exam_running(db, cid):
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
        activity: list[dict] = []
        mode, anchored = None, None  # the Lab tutor has no mode
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
            if body.attached:
                question += attached_text(db, cid, body.attached, body.items)
            if body.style is not None:  # explain one Block again from this Section's pages only, so its citations stay there
                block = next((b for b in section_blocks(section["id"]) if b["id"] == body.block_id), None) if section else None
                if block is None:
                    raise HTTPException(404, "no such Block in this Section")
                question = f"{STYLES[body.style]}\n\nThe Block ({block['component']}): {block['data']}"
            anchored = None if body.style else (given_anchor(db, cid, body.anchor) or anchor(db, cid, body.question))
            mode = "explain" if body.style else mode_of(db, cid, body.mode, anchored)
            if mode == "step" and anchored:  # only the quoted page and the ones before it, so the answer can't lean on what comes later
                pages, passages = page_texts(ctx, cid, step_pages(anchored)), []
                activity = [{"kind": "read", "label": f"Found it on {anchored['source']} p.{anchored['page']}", **anchored}]
            else:
                pages = page_texts(ctx, cid, json.loads(section["pages"])) if section else []
                passages = [] if body.style else [{"source": p["source"], "page": p["page"], "text": p["text"]}
                                                  for p in searchm.search(db, ctx.search, cid, body.question, PASSAGES)]
            context = context_text(ctx, cid, body.sections, section["id"] if section else None, pages)
            name, allowed = "tutor", {(p["source"], p["page"]) for p in pages + passages + context[1]}
            activity = activity or reading(body.question, passages, context[1])
            inputs = {"section": section["title"] if section else "", "pages": pages, "passages": passages, "context": context[0],
                      "history": history, "question": question, "catalogue": catalogue_text(ctx), "language": language_rule(db, cid),
                      "memory": memory.memory_text(db, cid), "mode": mode_text(mode, anchored if mode == "step" else None),
                      "exam": cram.exam_text(db, cid, section["chapter_id"] if section else None),
                      "blocks": "\n".join(f"[{b['id']}] {b['component']}: {b['data'][:4000]}" for b in section_blocks(section["id"]))
                      if section else "(no Section open: propose nothing)"}

        files += save_images(body.images, ctx.course_dir(cid) / "tutor" / "images")
        stop = threading.Event()

        def events():
            chunks, seen, hider = [], [], memory.Hider()  # seen: what the learner got of it, without the remember fence
            for a in activity:
                yield sse("activity", a)
            try:
                for chunk in stream_pi_step(db, ctx.backend, name, inputs, ctx.course_dir(cid), files, course_id=cid, stop=stop):
                    if "```proposal" not in "".join(chunks) and "```proposal" in "".join(chunks) + chunk:
                        yield sse("activity", {"kind": "write", "label": "Writing a proposal"})
                    chunks.append(chunk)
                    if text := hider.feed(chunk):
                        seen.append(text)
                        yield sse("token", {"text": text})
                if text := hider.finish():
                    seen.append(text)
                    yield sse("token", {"text": text})
            except Exception as e:  # the Trace already has it; tell the panel
                yield sse("error", {"message": str(e)[:500]})
                return
            answer = sourced("".join(chunks), anchored if mode == "step" else None)
            cites = citations_in(answer, allowed)
            if mode:
                check_step(db, cid, name, mode, "".join(seen))
            if name == "tutor" and section is not None and PROPOSAL_RE.search(answer):
                yield sse("activity", {"kind": "check", "label": "Checking the proposal"})
            proposal = proposal_of(answer, cid, section, inputs.get("pages", []), allowed) if name == "tutor" else None
            at = dt.datetime.now(dt.UTC).isoformat()
            first = db.execute("INSERT INTO tutor_messages (conversation_id, course_id, section_id, role, text, at, style) VALUES (?,?,?,?,?,?,?)",
                               (conv or 0, cid, body.section_id, "learner", body.question, at, body.style)).lastrowid
            cid_conv = conv or first
            if not conv:
                db.execute("UPDATE tutor_messages SET conversation_id=? WHERE id=?", (cid_conv, first))
            mid = db.execute("INSERT INTO tutor_messages (conversation_id, course_id, section_id, role, text, citations, at, proposal, mode, anchor) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?)", (cid_conv, cid, body.section_id, "tutor", "".join(seen).rstrip() if hider.fences else answer, json.dumps(cites), at,
                                                              json.dumps(proposal, ensure_ascii=False) if proposal else None, mode,
                                                              json.dumps(anchored) if mode == "step" and anchored else None)).lastrowid
            if body.style:
                refresh_patterns(db, cid)
            if name == "tutor" and (fact := memory.remember(db, hider.fences, cid, mid, now().isoformat())):
                db.execute("UPDATE tutor_messages SET remembered=? WHERE id=?", (fact["id"], mid))
                yield sse("remembered", fact)
            yield sse("done", {"conversation_id": cid_conv, "message_id": mid, "question_id": first, "citations": cites, "proposal": shown(proposal),
                               "mode": mode, "anchor": anchored if mode == "step" else None})

        return StreamingResponse(watched(request, events(), stop, body.answer), media_type="text/event-stream")

    @r.get("/api/courses/{cid}/answers/{answer}")
    def answer_state(cid: int, answer: str):
        """Where a tutor or chat answer is, for a page whose connection dropped while it streamed."""
        if (state := ANSWERS.get(answer)) is None:
            raise HTTPException(404, "that answer is gone: the app restarted")
        return {k: state[k] for k in ("done", "conversation_id", "error")}

    @r.post("/api/courses/{cid}/answers/{answer}/stop", status_code=204)
    def stop_answer(cid: int, answer: str):
        """The learner's Stop: kills the model; the answer isn't saved."""
        if state := ANSWERS.get(answer):
            state["stop"].set()

    @r.get("/api/courses/{cid}/tutor/{conversation_id}")
    def conversation(cid: int, conversation_id: int):
        rows = db.execute("SELECT * FROM tutor_messages WHERE conversation_id=? AND course_id=? ORDER BY id", (conversation_id, cid)).fetchall()
        if not rows:
            raise HTTPException(404, "no such conversation")
        return [message_json(db, m) for m in rows]

    @r.get("/api/courses/{cid}/tutor")
    def conversations(cid: int, section_id: int | None = None):
        """A Course's conversations, latest first: the first question, the Section it started in, the last activity."""
        rows = db.execute(
            "SELECT m.conversation_id AS id, m.text AS question, m.section_id, s.title AS section, "
            "(SELECT MAX(at) FROM tutor_messages x WHERE x.conversation_id=m.conversation_id AND x.course_id=m.course_id) AS last_at "
            "FROM tutor_messages m LEFT JOIN sections s ON s.id=m.section_id WHERE m.course_id=? AND m.id=m.conversation_id "
            "AND m.kind IS NULL AND (? IS NULL OR m.section_id=?) ORDER BY last_at DESC, m.id DESC", (cid, section_id, section_id)).fetchall()
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
