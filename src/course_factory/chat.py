"""The Course chat: the tutor at Course level. Answers mix Markdown with ```block fences; code splits them into parts, checks each
Block like a generated one (one repair round more than a Section's is the shared REPAIRS), and drops what still fails."""
import contextlib
import datetime as dt
import json
import queue
import re
import threading

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import cram, memory
from . import search as searchm
from . import learner
from .checks import heal_markdown
from .chapters import catalogue_text, checked_blocks, language_rule, page_texts, source_pages
from .context import Ctx
from .grading import QuestionGrade, score_steps
from .pi_step import StepFailed, run_pi_step, stream_pi_step
from .learner import PASS, Outcome, QuizAnswer, SelfMark, chat_scores, mastery, standings
from .progression import flag_progression, ledger_errors
from .tutor import (ANSWER_ID, HISTORY, MAX_IMAGES, PASSAGES, Mode, anchor, attached_text, check_step, citations_in, sourced, cited_out, context_text, exam_running,
                    mode_of, mode_text, proposal_json, reading, save_images, sse, step_pages, watched)

FENCE = "```block"
CLOSE = "\n```"
FILES_PROMPT = ("Course files: you have the tool course_shell, a shell in a read-only copy of the Course's files. /course/text/<file>.txt holds "
                "each file's read text with a '=== page N ===' line before each page; /course/sources holds the original files. Use it when "
                "the question needs more than the passages above (a whole document, every past exam, counting or comparing across files): "
                "list with `ls -R /course/text`, search with `grep -n`, read pages with `sed -n`. Cite what you read as [<file> p.<page>], "
                "<file> without /course/text/ and .txt. Run at most 15 commands, then answer.")
DRILL_GAP = 3  # a Concept missed in a Drill comes back after this many questions
WEAK_CONCEPTS = 5


class DrillStart(BaseModel):
    chapters: list[int] = Field([], max_length=60)  # none: the whole Course
    minutes: int = Field(15, ge=1, le=180)


class Say(BaseModel):
    question: str = Field(min_length=1)
    conversation_id: int | None = None
    images: list[str] = Field([], max_length=MAX_IMAGES)
    attached: list[int] = Field([], max_length=12)  # Block ids the learner attached, from any Section of the Course
    sections: list[int] = Field([], max_length=60)  # Sections added as context, on top of the conversation's pinned ones
    sources: list[str] = Field([], max_length=40)  # whole source documents added as context, every page
    shell: bool = False  # the model may run commands in a container holding the Course's files (sandbox.course_box)
    drill: DrillStart | None = None  # "Quiz me": starts a Drill with this new conversation
    stop_drill: bool = False  # ends the conversation's Drill with its summary
    mode: Mode | None = None  # Step, Explain, Test me or Beyond the course (#30); a Drill is always Test me
    answer: str | None = Field(None, pattern=ANSWER_ID)  # the page's id for this answer: see tutor.watched


class Redo(BaseModel):
    note: str = Field("", max_length=2000)  # empty: just another take on the same Block


class Rewrite(BaseModel):
    selection: str = Field(min_length=1, max_length=8000)  # as rendered on screen
    note: str = Field("", max_length=2000)


class Rewritten(BaseModel):
    text: str = Field(min_length=1)


class Place(BaseModel):
    section_id: int
    after_block_id: int | None = None


class Splitter:
    """Splits the streamed answer into Markdown text and ```block fences without ever letting fence text out. feed() and
    finish() return events: ("text", s), ("open", k), ("kind", k, component), ("block", k, raw_json), k counting the Blocks."""

    def __init__(self):
        self.buf, self.fenced, self.k, self.kind = "", False, -1, None

    def feed(self, chunk: str) -> list[tuple]:
        self.buf += chunk
        out = []
        while True:
            if not self.fenced:
                i = self.buf.find(FENCE)
                if i < 0:
                    hold = next((k for k in range(len(FENCE) - 1, 0, -1) if self.buf.endswith(FENCE[:k])), 0)  # maybe the start of a fence
                    if text := self.buf[:len(self.buf) - hold]:
                        out.append(("text", text))
                    self.buf = self.buf[len(self.buf) - hold:]
                    return out
                if self.buf[:i]:
                    out.append(("text", self.buf[:i]))
                self.buf, self.fenced, self.kind, self.k = self.buf[i + len(FENCE):], True, None, self.k + 1
                out.append(("open", self.k))
            else:
                j = self.buf.find(CLOSE)
                if j < 0:
                    if self.kind is None and (m := re.search(r'"component"\s*:\s*"(\w+)"', self.buf)):
                        self.kind = m.group(1)
                        out.append(("kind", self.k, self.kind))
                    return out
                out.append(("block", self.k, self.buf[:j]))
                self.buf, self.fenced = self.buf[j + len(CLOSE):].lstrip("\n"), False

    def finish(self) -> list[tuple]:
        if self.fenced:  # never closed: the Block is lost
            return [("block", self.k, self.buf)]
        return [("text", self.buf)] if self.buf else []


def history_text(m, answers: dict | None = None) -> str:
    """A stored message as the model reads it: the prose, with each Block's content (the model wrote it, and a Challenge of the
    learner's answer needs the question and its answer; only the learner must not see answers in the prose)."""
    parts = json.loads(m["parts"]) if m["parts"] else None
    if parts is None:
        return m["text"]
    return "\n".join(p["text"] if p["type"] == "md" else f"[Block shown: {p['kind']} {json.dumps(p['block']['data'], ensure_ascii=False)[:2000]}]"
                     + "".join(f"\n[The learner answered: {a}]" for a in (answers or {}).get((m["id"], i), {}).values())
                     if p["type"] == "block" else "[Drill summary]" for i, p in enumerate(parts))


def answer_text(text: str) -> str:
    """Prose of an answer as it is shown: the local model sometimes puts its whole {"text": ...} object inside "text", and
    escapes LaTeX backslashes twice; healed on save and on read, so answers stored before the fix show right too."""
    with contextlib.suppress(json.JSONDecodeError):
        if text.lstrip().startswith("{") and isinstance(inner := json.loads(text), dict) and isinstance(inner.get("text"), str):
            text = inner["text"]
    return heal_markdown(text)


def healed_parts(parts: list[dict]) -> list[dict]:
    return [p | {"text": answer_text(p["text"])} if p["type"] == "md" else p for p in parts]


def message_json(db, m) -> dict:
    return {"id": m["id"], "role": m["role"], "text": m["text"], "citations": json.loads(m["citations"]), "at": m["at"],
            "parts": healed_parts(json.loads(m["parts"])) if m["parts"] else None, "activity": json.loads(m["activity"]) if m["activity"] else [],
            "remembered": memory.remembered_json(db, m["remembered"]), "mode": m["mode"], "anchor": json.loads(m["anchor"]) if m["anchor"] else None}


def router(ctx: Ctx) -> APIRouter:
    db = ctx.db
    r = APIRouter()

    def course_or_404(cid: int):
        if db.execute("SELECT 1 FROM courses WHERE id=?", (cid,)).fetchone() is None:
            raise HTTPException(404, "no such Course")
        if exam_running(db, cid):
            raise HTTPException(409, "the Course chat is hidden during an exam")

    def conversation_rows(cid: int, conv: int):
        rows = db.execute("SELECT * FROM tutor_messages WHERE conversation_id=? AND course_id=? AND kind='chat' ORDER BY id", (conv, cid)).fetchall()
        if not rows:
            raise HTTPException(404, "no such conversation")
        return rows

    def meta_of(first) -> dict:
        return json.loads(first["drill"]) if first["drill"] else {}  # the first message holds the conversation's pinned Sections

    def concepts_of(cid: int) -> dict[str, tuple[int, str]]:
        """concept -> (reading-order index, title) of the Section that teaches it, every Section of the Course."""
        found: dict[str, tuple[int, str]] = {}
        for i, s in enumerate(db.execute("SELECT s.title, s.teaches FROM sections s JOIN chapters c ON c.id=s.chapter_id WHERE c.course_id=? "
                                         "ORDER BY c.position, s.position", (cid,))):
            for c in json.loads(s["teaches"]):
                found.setdefault(c, (i, s["title"]))
        return found

    def known_concepts(cid: int, concepts: dict, anchored: dict) -> dict:
        """The Concepts known by the time the learner reaches the anchored page: those of the Sections up to the first one that cites
        it. A page no Section cites keeps them all."""
        sections = [json.loads(s["pages"]) for s in db.execute("SELECT s.pages FROM sections s JOIN chapters c ON c.id=s.chapter_id WHERE "
                                                                "c.course_id=? ORDER BY c.position, s.position", (cid,))]
        at = next((i for i, ps in enumerate(sections) if any(p["source"] == anchored["source"] and p["page"] == anchored["page"] for p in ps)), None)
        return concepts if at is None else {c: v for c, v in concepts.items() if v[0] <= at}

    def checked(cid: int, raws: list[dict], pages: list[dict], allowed: set[tuple[str, int]], concepts: dict, on_stage, note: str = ""):
        """The Blocks of an answer through the same checks as a generated Block. A Concept the Course doesn't have is an error
        the model gets back to repair (the ledger, without the order: the Block belongs to no Section yet)."""
        raws = [cited_out(b, allowed) if isinstance(b, dict) else b for b in raws]
        notes = {}
        for i, b in enumerate(raws):
            if isinstance(b, dict) and isinstance(b.get("tests"), list):
                if err := ledger_errors([{"id": i, "component": "", "data": {}, "tests": b["tests"], "at": 1 << 30}], concepts).get(i):
                    notes[i] = "; ".join(err)
        if note:  # the learner's Regenerate instructions, for a single Block
            notes[0] = "; ".join(filter(None, [note, notes.get(0)]))
        return checked_blocks(ctx, cid, raws, pages, notes, on_stage, live=True, repairs=1)  # the spec's one repair: the learner is waiting

    def teaching(cid: int) -> dict[str, dict]:
        """concept -> the Section that teaches it, for links."""
        out: dict[str, dict] = {}
        for s in db.execute("SELECT s.id, s.title, s.teaches FROM sections s JOIN chapters c ON c.id=s.chapter_id WHERE c.course_id=? "
                            "ORDER BY c.position, s.position", (cid,)):
            for c in json.loads(s["teaches"]):
                out.setdefault(c, {"section_id": s["id"], "section": s["title"]})
        return out

    def drill_prompt(cid: int, conv: int | None, state: dict, over: bool) -> str:
        """What the Drill's turn gets: the facts code knows (weak Concepts of the chosen Chapters, the exam's Question Types, the
        Concepts missed earlier that are due back), and the one thing to do."""
        left = max(0, state["minutes"] * 60 - (learner.now() - dt.datetime.fromisoformat(state["started"])).total_seconds())
        if over:
            return ("DRILL OVER: write only two or three sentences closing the Drill (what went well, what to look at next), in the learner's "
                    "language. No question, no Block: the summary with its links is added after your words.")
        stands = standings(db, cid)
        wanted = set(state["chapters"])
        weak = sorted((c for c in mastery(db, cid, stands).values() if not wanted or c["chapter_id"] in wanted),
                      key=lambda c: (c["mastery"] is None, c["mastery"] or 0))
        weak = [f"{c['name']} (Section \"{c['section']}\", " + ("untried" if c["mastery"] is None else f"mastery {c['mastery']}") + ")"
                for c in weak if c["mastery"] is None or c["mastery"] < PASS][:WEAK_CONCEPTS]
        types = [f"{t['name']}: {t['trigger']}" for t in db.execute(
            "SELECT name, trigger FROM question_types WHERE course_id=? AND (? OR chapter_id IN (SELECT value FROM json_each(?)))",
            (cid, not wanted, json.dumps(sorted(wanted))))]
        back = missed_back(conv) if conv else []
        last = db.execute("SELECT MAX(id) id FROM tutor_messages WHERE conversation_id=? AND role='tutor'", (conv,)).fetchone()["id"] if conv else None
        answered = [f"{o['concept']}: {'right' if o['score'] >= PASS else 'partly right' if o['score'] > 0 else 'wrong'}"
                    + (f" (answered: {o['answer'][:600]})" if o["answer"] else "") for o in db.execute(
            "SELECT concept, score, answer FROM chat_outcomes WHERE message_id=? ORDER BY id", (last,))] if last else []
        return ("DRILL in progress, " + f"{int(left // 60)} min left. Ask exactly ONE practice question now, as one Block (quiz, fill_blanks or "
                "explain_back) that tests Concepts of the list above, and write nothing after it. When the learner's message answers your "
                "previous question, first apply the Challenge to that answer (never praise a wrong or partial one; name what is wrong, then "
                "your question is the follow-up from another side). Keep to the Chapters chosen.\n"
                f"Weak Concepts, weakest first: {json.dumps(weak, ensure_ascii=False)}\n"
                f"The exam's Question Types: {json.dumps(types, ensure_ascii=False)}\n"
                + (f"Recorded answers to your last question: {json.dumps(answered, ensure_ascii=False)}\n" if answered else "")
                + (f"Missed earlier in this Drill and due back now: ask about {json.dumps(back, ensure_ascii=False)} before anything else.\n" if back else ""))

    def missed_back(conv: int) -> list[str]:
        """Concepts missed in this conversation at least DRILL_GAP questions ago and not answered right since."""
        turns = [m["id"] for m in db.execute("SELECT id FROM tutor_messages WHERE conversation_id=? AND role='tutor' ORDER BY id", (conv,))]
        last: dict[str, tuple[int, float]] = {}
        for o in db.execute("SELECT concept, message_id, score FROM chat_outcomes WHERE message_id IN (SELECT id FROM tutor_messages WHERE conversation_id=?) "
                            "ORDER BY id", (conv,)):
            last[o["concept"]] = (o["message_id"], o["score"])
        return [c for c, (m, score) in last.items() if score < PASS and m in turns and len(turns) - turns.index(m) > DRILL_GAP]

    def drill_summary(cid: int, conv: int) -> dict:
        """What the Drill's answers came to, from what was recorded: Concepts that went right, and those to review, linked to the Section that teaches them."""
        scores, where = chat_scores(db, cid, conv), teaching(cid)
        return {"type": "summary", "right": [c for c, v in scores.items() if v >= PASS],
                "review": [{"concept": c, **where.get(c, {"section_id": None, "section": None})} for c, v in scores.items() if v < PASS]}

    @r.post("/api/courses/{cid}/chat")
    def say(cid: int, body: Say, request: Request):
        course_or_404(cid)
        conv, first, history, pinned, state = body.conversation_id, None, [], [], None
        if conv is not None:
            rows = conversation_rows(cid, conv)
            first, pinned, state = rows[0], meta_of(rows[0]).get("pinned", []), meta_of(rows[0]).get("drill")
            answers: dict[tuple, dict[int, str]] = {}  # what the learner last answered to each Block's questions, so a Challenge can address it
            for o in db.execute("SELECT message_id, part, question, score, answer FROM chat_outcomes WHERE message_id IN "
                                "(SELECT id FROM tutor_messages WHERE conversation_id=?) ORDER BY id", (conv,)):
                answers.setdefault((o["message_id"], o["part"]), {})[o["question"]] = \
                    f"question {o['question'] + 1}: {o['answer'][:600] or '(no text)'}, scored {round(o['score'], 2)}"  # one row per Concept: kept once
            history = [{"role": m["role"], "text": history_text(m, answers)} for m in rows[-HISTORY:]]
        if body.drill and conv is None:
            state = {"chapters": body.drill.chapters, "minutes": body.drill.minutes, "started": learner.now().isoformat(), "stopped": False}
        over = False
        if state and not state["stopped"]:
            over = body.stop_drill or (learner.now() - dt.datetime.fromisoformat(state["started"])).total_seconds() >= state["minutes"] * 60
        elif body.stop_drill:
            raise HTTPException(409, "there is no Drill to stop")
        drilling = bool(state and not state["stopped"])
        question = body.question + (attached_text(db, cid, body.attached) if body.attached else "")
        anchored = None if drilling else anchor(db, cid, body.question)
        mode = "test" if drilling else mode_of(db, cid, body.mode, anchored)
        step = mode == "step" and anchored is not None  # only the quoted page and the ones before it, so the answer can't lean on what comes later
        passages = page_texts(ctx, cid, step_pages(anchored)) if step and anchored else [
            {"source": p["source"], "page": p["page"], "text": p["text"]} for p in searchm.search(db, ctx.search, cid, body.question, PASSAGES)]
        context = context_text(ctx, cid, [*pinned, *body.sections], None, [], body.sources)
        allowed = {(p["source"], p["page"]) for p in passages + context[1]}
        if body.shell:
            if ctx.files_box is None:
                raise HTTPException(503, "the Course files container is not available")
            allowed |= {(name, n) for name, count in source_pages(ctx, cid).items() for n in range(1, count + 1)}  # it may read any page
        concepts = concepts_of(cid)
        known = known_concepts(cid, concepts, anchored) if step and anchored else concepts
        inputs = {"mode": mode_text(mode, anchored if mode == "step" else None), "language": language_rule(db, cid), "passages": passages, "context": context[0], "history": history, "question": question,
                  "catalogue": catalogue_text(ctx), "memory": memory.memory_text(db, cid), "drill": drill_prompt(cid, conv, state, over) if drilling else "",
                  "files": FILES_PROMPT if body.shell else "",
                  "exam": cram.exam_text(db, cid),
                  "concepts": "\n".join(f"- {t}: {c}" for c, (_, t) in known.items()) or "(none named)"}
        files = save_images(body.images, ctx.course_dir(cid) / "tutor" / "images")
        stop = threading.Event()
        activity = ([{"kind": "read", "label": f"Found it on {anchored['source']} p.{anchored['page']}", **anchored}] if step and anchored
                    else reading(body.question, passages, context[1]))

        def events():
            for a in activity:
                yield sse("activity", a)
            split, hider, raws, md, kinds = Splitter(), memory.Hider(), {}, [], {}
            order: list[tuple] = []  # ("md", text) and ("block", k), in the answer's order

            def handle(evs):
                for ev in evs:
                    if ev[0] in ("text", "flush"):
                        if text := hider.feed(ev[1]) if ev[0] == "text" else ev[1]:  # the remember fence never reaches the learner
                            md.append(text)
                            order.append(("md", text))
                            yield sse("token", {"text": text})
                    elif ev[0] == "open":
                        order.append(("block", ev[1]))
                        yield sse("activity", a := {"kind": "write", "label": "Writing a Block"})
                        activity.append(a)
                        yield sse("block", {"index": ev[1], "status": "writing", "kind": None})
                    elif ev[0] == "kind":
                        kinds[ev[1]] = ev[2]
                        yield sse("block", {"index": ev[1], "status": "writing", "kind": ev[2]})
                    else:
                        raws[ev[1]] = ev[2]
            calls: list[dict] = []
            try:
                if body.shell:
                    yield sse("activity", a := {"kind": "search", "label": "Opening the Course files"})
                    activity.append(a)
                with ctx.files_box(cid) if body.shell else contextlib.nullcontext() as box:
                    for chunk in stream_pi_step(db, ctx.backend, "chat", inputs, ctx.course_dir(cid), files, course_id=cid, stop=stop,
                                                sandbox=box, on_tool=calls.append):
                        while calls:
                            yield sse("activity", a := {"kind": "search", "label": f"Running {str(calls.pop(0).get('command', ''))[:120]}"})
                            activity.append(a)
                        yield from handle(split.feed(chunk))
                yield from handle(split.finish())
                yield from handle([("flush", hider.finish())])
            except Exception as e:  # the Trace already has it; the page shows it with a Retry
                yield sse("error", {"message": str(e)[:500]})
                return
            parsed = {}
            for k, raw in raws.items():
                try:
                    parsed[k] = proposal_json(raw)
                except json.JSONDecodeError:
                    parsed[k] = {"component": kinds.get(k, "?"), "data": {}, "_unparsed": True}
            result: dict[int, tuple[dict, dict]] = {}
            if parsed:
                ks = sorted(parsed)
                for k in ks:
                    yield sse("block", {"index": k, "status": "checking", "kind": kinds.get(k)})
                yield sse("activity", a := {"kind": "check", "label": f"Checking {len(ks)} Block{'s' if len(ks) > 1 else ''}"})
                activity.append(a)
                q: queue.Queue = queue.Queue()

                def work():
                    try:
                        q.put(("done", checked(cid, [parsed[k] for k in ks], passages + context[1], allowed, concepts, lambda s: q.put(("stage", s)))))
                    except Exception as e:
                        q.put(("error", e))
                threading.Thread(target=work, daemon=True).start()
                while (kind := (item := q.get())[0]) == "stage":
                    yield sse("activity", a := {"kind": "fix" if item[1] == "repairing" else "check",
                                                "label": "Fixing a Block" if item[1] == "repairing" else "Checking the Blocks against the pages"})
                    activity.append(a)
                if kind == "error":
                    yield sse("error", {"message": str(item[1])[:500]})
                    return
                result = {k: (b, f) for k, b, f in zip(ks, *item[1])}
            parts = []

            def add_md(t):
                if parts and parts[-1]["type"] == "md":
                    parts[-1]["text"] += t
                else:
                    parts.append({"type": "md", "text": t})
            for what, v in order:
                if what == "md":
                    add_md(v)
                    continue
                kind = kinds.get(v) or (result.get(v, ({},))[0].get("component")) or "Block"
                got = result.get(v)
                if got is None or got[1]["errors"] or parsed[v].get("_unparsed"):
                    add_md(f"\n\n*I couldn't draw the {kind} here: it failed its checks.*\n\n")
                    yield sse("block", {"index": v, "status": "dropped", "kind": kind})
                    continue
                block = {**got[0], "flags": got[1]["warnings"]}
                parts.append({"type": "block", "kind": got[0]["component"], "block": block, "saved": None})
                yield sse("block", {"index": v, "status": "ok", "kind": got[0]["component"], "block": block})
            parts = healed_parts([p for p in parts if p["type"] != "md" or p["text"].strip()])
            if step:
                parts = [p | {"text": sourced(p["text"], anchored)} if p["type"] == "md" else p for p in parts]
            check_step(db, cid, "chat", mode, "".join(md))
            if over:
                state["stopped"] = True
            text = "\n\n".join(p["text"].strip() for p in parts if p["type"] == "md")
            cites = citations_in(text, allowed)
            at = dt.datetime.now(dt.UTC).isoformat()
            asked = db.execute("INSERT INTO tutor_messages (conversation_id, course_id, role, text, at, kind) VALUES (?,?,?,?,?,?)",
                               (conv or 0, cid, "learner", body.question, at, "chat")).lastrowid
            cv = conv or asked
            if not conv:
                db.execute("UPDATE tutor_messages SET conversation_id=?, drill=? WHERE id=?",
                           (cv, json.dumps({"pinned": body.sections, "drill": state}) if body.sections or state else None, asked))
            elif over:
                db.execute("UPDATE tutor_messages SET drill=? WHERE id=?", (json.dumps({**meta_of(first), "drill": state}), first["id"]))
            if over:  # the summary needs this conversation's rows, which exist now
                parts.append(drill_summary(cid, cv))
            mid = db.execute("INSERT INTO tutor_messages (conversation_id, course_id, role, text, citations, at, kind, parts, activity, mode, anchor) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (cv, cid, "tutor", text, json.dumps(cites), at, "chat",
                                                                json.dumps(parts, ensure_ascii=False), json.dumps(activity), mode,
                                                                json.dumps(anchored) if step else None)).lastrowid
            if fact := memory.remember(db, hider.fences, cid, mid, learner.now().isoformat()):
                db.execute("UPDATE tutor_messages SET remembered=? WHERE id=?", (fact["id"], mid))
                yield sse("remembered", fact)
            yield sse("done", {"conversation_id": cv, "message_id": mid, "question_id": asked, "citations": cites, "parts": parts, "activity": activity,
                               "mode": mode, "anchor": anchored if step else None})

        return StreamingResponse(watched(request, events(), stop, body.answer), media_type="text/event-stream")

    @r.get("/api/courses/{cid}/chat")
    def conversations(cid: int):
        """The Course chat's conversations, latest first: the first question and the last activity."""
        rows = db.execute(
            "SELECT m.conversation_id AS id, m.text AS question, (SELECT MAX(at) FROM tutor_messages x WHERE x.conversation_id=m.conversation_id "
            "AND x.course_id=m.course_id) AS last_at FROM tutor_messages m WHERE m.course_id=? AND m.kind='chat' AND m.id=m.conversation_id "
            "ORDER BY last_at DESC, m.id DESC", (cid,)).fetchall()
        return [dict(c) for c in rows]

    @r.get("/api/courses/{cid}/chat/{conv}")
    def conversation(cid: int, conv: int):
        rows = conversation_rows(cid, conv)
        return {"pinned": meta_of(rows[0]).get("pinned", []), "drill": meta_of(rows[0]).get("drill"), "messages": [message_json(db, m) for m in rows]}

    @r.delete("/api/courses/{cid}/chat/{conv}", status_code=204)
    def delete_conversation(cid: int, conv: int):
        conversation_rows(cid, conv)
        db.execute("DELETE FROM tutor_messages WHERE conversation_id=? AND course_id=? AND kind='chat'", (conv, cid))
        return Response(status_code=204)

    @r.delete("/api/courses/{cid}/chat/messages/{mid}", status_code=204)
    def take_back(cid: int, mid: int):
        """Removes a message and everything after it, to rephrase. A Block saved from there on stays in its Section, so Undo comes first."""
        m = db.execute("SELECT * FROM tutor_messages WHERE id=? AND course_id=? AND kind='chat'", (mid, cid)).fetchone()
        if m is None:
            raise HTTPException(404, "no such message")
        later = db.execute("SELECT parts FROM tutor_messages WHERE conversation_id=? AND course_id=? AND id>=? AND parts IS NOT NULL",
                           (m["conversation_id"], cid, mid)).fetchall()
        if any(p.get("saved") for row in later for p in json.loads(row["parts"])):
            raise HTTPException(409, "a Block from here on was saved to a Section: undo that first, or keep these messages")
        db.execute("DELETE FROM chat_outcomes WHERE course_id=? AND message_id>=? AND message_id IN (SELECT id FROM tutor_messages WHERE conversation_id=?)",
                   (cid, mid, m["conversation_id"]))
        db.execute("DELETE FROM tutor_messages WHERE conversation_id=? AND course_id=? AND id>=?", (m["conversation_id"], cid, mid))
        return Response(status_code=204)

    @r.post("/api/courses/{cid}/chat/from-tutor/{conv}")
    def hand_over(cid: int, conv: int):
        """Copies a Section tutor conversation into a new Course chat conversation, its Section pinned as context."""
        course_or_404(cid)
        rows = db.execute("SELECT * FROM tutor_messages WHERE conversation_id=? AND course_id=? AND kind IS NULL ORDER BY id", (conv, cid)).fetchall()
        if not rows:
            raise HTTPException(404, "no such conversation")
        pinned = [rows[0]["section_id"]] if rows[0]["section_id"] is not None else []
        first = None
        for m in rows:
            parts = json.dumps([{"type": "md", "text": m["text"]}], ensure_ascii=False) if m["role"] == "tutor" else None
            mid = db.execute("INSERT INTO tutor_messages (conversation_id, course_id, role, text, citations, at, kind, parts, drill) "
                             "VALUES (?,?,?,?,?,?,?,?,?)", (first or 0, cid, m["role"], m["text"], m["citations"], m["at"], "chat", parts,
                                                            json.dumps({"pinned": pinned}) if first is None else None)).lastrowid
            if first is None:
                first = mid
                db.execute("UPDATE tutor_messages SET conversation_id=? WHERE id=?", (first, first))
        return {"conversation_id": first}

    def part_of(cid: int, mid: int, part: int, kind: str = "block"):
        m = db.execute("SELECT * FROM tutor_messages WHERE id=? AND course_id=? AND kind='chat' AND parts IS NOT NULL", (mid, cid)).fetchone()
        parts = json.loads(m["parts"]) if m else []
        if not 0 <= part < len(parts) or parts[part]["type"] != kind:
            raise HTTPException(404, "no such Block" if kind == "block" else "no such text")
        return m, parts, parts[part]

    def sections_of(cid: int) -> list[dict]:
        out = []
        for i, s in enumerate(db.execute("SELECT s.id, s.title, s.pages, c.title chapter FROM sections s JOIN chapters c ON c.id=s.chapter_id "
                                         "WHERE c.course_id=? ORDER BY c.position, s.position", (cid,))):
            blocks = [{"id": b["id"], "component": b["component"], "tests": json.loads(b["tests"])} for b in db.execute(
                "SELECT id, component, tests FROM blocks WHERE section_id=? ORDER BY position", (s["id"],))]
            out.append({"id": s["id"], "title": s["title"], "chapter": s["chapter"], "pages": json.loads(s["pages"]), "at": i, "blocks": blocks})
        return out

    @r.get("/api/courses/{cid}/chat/messages/{mid}/parts/{part}/suggest")
    def suggest(cid: int, mid: int, part: int):
        """Where a Block of an answer would go: the Section that teaches the Concepts it uses (the latest, when they span several),
        after the Section's Block that tests the most of them, else at the end. Every Section and its Blocks, for picking elsewhere."""
        course_or_404(cid)
        m, _, p = part_of(cid, mid, part)
        sections, tests = sections_of(cid), p["block"].get("tests") or []
        concepts = concepts_of(cid)
        at = max((concepts[t][0] for t in tests if t in concepts), default=None)
        if at is None:  # no Concept: the Section the conversation is pinned to, if any
            pinned = meta_of(conversation_rows(cid, m["conversation_id"])[0]).get("pinned", [])
            at = next((s["at"] for s in sections if s["id"] in pinned), None)
        target = next((s for s in sections if s["at"] == at), None)
        after = None
        if target:
            best = max(((len(set(b["tests"]) & set(tests)), i, b["id"]) for i, b in enumerate(target["blocks"])), default=(0, 0, None))
            after = best[2] if best[0] else None
        return {"section_id": target["id"] if target else None, "after_block_id": after,
                "sections": [{k: s[k] for k in ("id", "title", "chapter", "blocks")} | {"blocks": [{"id": b["id"], "component": b["component"]} for b in s["blocks"]]}
                             for s in sections]}

    def signature(component: str, data) -> str:
        return json.dumps([component, data], sort_keys=True, ensure_ascii=False)

    @r.post("/api/courses/{cid}/chat/messages/{mid}/parts/{part}/save")
    def save(cid: int, mid: int, part: int, body: Place):
        """Puts the Block into the Section after the chosen Block (the start of the Section: after nothing), re-checked against that
        Section's pages and the Concept ledger, Model-added and marked as from the chat."""
        course_or_404(cid)
        m, parts, p = part_of(cid, mid, part)
        if p.get("saved"):
            raise HTTPException(409, "this Block was already saved")
        sections = sections_of(cid)
        target = next((s for s in sections if s["id"] == body.section_id), None)
        if target is None:
            raise HTTPException(404, "no such Section")
        ids = [b["id"] for b in target["blocks"]]
        if body.after_block_id is not None and body.after_block_id not in ids:
            raise HTTPException(404, "no such Block in this Section")
        raw = {k: p["block"][k] for k in ("component", "data", "citations", "origin", "tests") if k in p["block"]}
        pages = page_texts(ctx, cid, target["pages"])
        blocks, flags = checked_blocks(ctx, cid, [raw], pages, live=True)
        block, flag = blocks[0], flags[0]
        errors = flag["errors"] + ledger_errors([{"id": 0, "component": block["component"], "data": block["data"], "tests": block.get("tests", []),
                                                  "at": target["at"]}], concepts_of(cid)).get(0, [])
        if errors:
            raise HTTPException(409, {"errors": errors})
        position = ids.index(body.after_block_id) + 1 if body.after_block_id is not None else 0
        db.execute("UPDATE blocks SET position=position+1 WHERE section_id=? AND position>=?", (target["id"], position))
        bid = db.execute("INSERT INTO blocks (section_id, position, component, data, citations, origin, status, flags, tests, chat_message) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?)", (target["id"], position, block["component"], json.dumps(block["data"], ensure_ascii=False),
                                                         json.dumps(block["citations"], ensure_ascii=False), "model_added", "ok",
                                                         json.dumps(flag["warnings"], ensure_ascii=False), json.dumps(block.get("tests", [])), mid)).lastrowid
        flag_progression(db, cid)
        p["saved"] = {"block_id": bid, "section_id": target["id"], "section": target["title"], "sig": signature(block["component"], block["data"])}
        db.execute("UPDATE tutor_messages SET parts=? WHERE id=?", (json.dumps(parts, ensure_ascii=False), mid))
        return {"saved": {k: v for k, v in p["saved"].items() if k != "sig"}}

    @r.post("/api/courses/{cid}/chat/messages/{mid}/parts/{part}/undo")
    def undo(cid: int, mid: int, part: int):
        """Takes the saved Block out of its Section again, unless it changed since."""
        course_or_404(cid)
        _, parts, p = part_of(cid, mid, part)
        saved = p.get("saved")
        if not saved:
            raise HTTPException(409, "this Block was not saved")
        row = db.execute("SELECT * FROM blocks WHERE id=?", (saved["block_id"],)).fetchone()
        if row is not None and signature(row["component"], json.loads(row["data"])) != saved["sig"]:
            raise HTTPException(409, "the Block changed since it was saved, so it can't be undone")
        if row is not None:
            db.execute("DELETE FROM blocks WHERE id=?", (row["id"],))
            for i, b in enumerate(db.execute("SELECT id FROM blocks WHERE section_id=? ORDER BY position", (row["section_id"],)).fetchall()):
                db.execute("UPDATE blocks SET position=? WHERE id=?", (i, b["id"]))
            flag_progression(db, cid)
        p["saved"] = None
        db.execute("UPDATE tutor_messages SET parts=? WHERE id=?", (json.dumps(parts, ensure_ascii=False), mid))
        return {"ok": True}

    @r.post("/api/courses/{cid}/chat/messages/{mid}/parts/{part}/regenerate")
    def regenerate(cid: int, mid: int, part: int, body: Redo):
        """Rewrites one Block of an answer, following the learner's instructions if any, through the same checks as when it was drawn.
        Practice already answered on the old Block stays counted: it was real practice of its Concepts."""
        course_or_404(cid)
        _, parts, p = part_of(cid, mid, part)
        if p.get("saved"):
            raise HTTPException(409, "this Block was saved: regenerate it in its Section")
        raw = {k: p["block"][k] for k in ("component", "data", "citations", "origin", "tests") if k in p["block"]}
        cites = raw.get("citations") or []
        note = body.note.strip() or "write a different take on this Block: same Component and purpose, fresh content"
        blocks, flags = checked(cid, [raw], page_texts(ctx, cid, cites), {(c["source"], c["page"]) for c in cites}, concepts_of(cid),
                                lambda s: None, note)
        if flags[0]["errors"]:
            raise HTTPException(409, {"errors": flags[0]["errors"]})
        p["block"], p["kind"] = {**blocks[0], "flags": flags[0]["warnings"]}, blocks[0]["component"]
        db.execute("UPDATE tutor_messages SET parts=? WHERE id=?", (json.dumps(parts, ensure_ascii=False), mid))
        return p

    @r.post("/api/courses/{cid}/chat/messages/{mid}/parts/{part}/rewrite")
    def rewrite(cid: int, mid: int, part: int, body: Rewrite):
        """Rewrites the passage of an answer's text the learner selected, following their instructions if any."""
        course_or_404(cid)
        m, parts, p = part_of(cid, mid, part, "md")
        try:
            out = run_pi_step(db, ctx.backend, "rewrite_text", {
                "text": p["text"], "selection": body.selection, "language": language_rule(db, cid), "pages": page_texts(ctx, cid, json.loads(m["citations"])),
                "note": body.note.strip() or "explain it differently, more clearly"}, Rewritten, ctx.course_dir(cid), course_id=cid, live=True)
        except StepFailed as e:
            raise HTTPException(502, f"the model could not rewrite it (busy or unavailable): {str(e)[:300]}")
        p["text"] = answer_text(out.text)
        text = "\n\n".join(q["text"].strip() for q in parts if q["type"] == "md")
        db.execute("UPDATE tutor_messages SET parts=?, text=? WHERE id=?", (json.dumps(parts, ensure_ascii=False), text, mid))
        return p

    # Practice answered in the chat: recorded against the Concepts the Block tests. Once the Block is saved into a Section its answers go
    # through that Block's own endpoints, so nothing here counts toward a Section.

    def practice_part(cid: int, mid: int, part: int, components: tuple[str, ...]):
        course_or_404(cid)
        m, _, p = part_of(cid, mid, part)
        if p["block"]["component"] not in components:
            raise HTTPException(422, f"not a {' or '.join(components)} Block")
        if p.get("saved"):
            raise HTTPException(409, "this Block was saved: answer it in its Section")
        return m, p

    def record(cid: int, m, part: int, p: dict, question: int, score: float, answer: str = "") -> None:
        drill = (meta_of(conversation_rows(cid, m["conversation_id"])[0]).get("drill") or {}).get("stopped") is False
        for concept in p["block"].get("tests") or []:  # a Block that tests nothing is practice for nothing
            db.execute("INSERT INTO chat_outcomes (course_id, concept, origin, message_id, part, question, score, answer, at) VALUES (?,?,?,?,?,?,?,?,?)",
                       (cid, concept, "drill" if drill else "chat", m["id"], part, question, score, answer, learner.now().isoformat()))
        learner.refresh_patterns(db, cid)

    @r.post("/api/courses/{cid}/chat/messages/{mid}/parts/{part}/answers")
    def answer_quiz(cid: int, mid: int, part: int, body: QuizAnswer):
        m, p = practice_part(cid, mid, part, ("quiz",))
        questions = p["block"]["data"]["questions"]
        if body.question >= len(questions):
            raise HTTPException(422, "no such question")
        q = questions[body.question]
        correct = sorted(set(body.chosen)) == sorted(set(q["correct"]))
        record(cid, m, part, p, body.question, float(correct), json.dumps(body.chosen))
        return {"correct": correct, "correct_options": q["correct"], "explanation": q["explanation"]}

    @r.post("/api/courses/{cid}/chat/messages/{mid}/parts/{part}/outcome")
    def outcome(cid: int, mid: int, part: int, body: Outcome):
        """Gaps are checked in the browser: this keeps the share got right."""
        m, p = practice_part(cid, mid, part, ("fill_blanks", "code_exercise"))
        record(cid, m, part, p, 0, body.score)
        return {"ok": True}

    @r.post("/api/courses/{cid}/chat/messages/{mid}/parts/{part}/self-mark")
    def self_mark(cid: int, mid: int, part: int, body: SelfMark):
        m, p = practice_part(cid, mid, part, ("explain_back", "exercise"))
        record(cid, m, part, p, 0, {"got": 1, "partly": 0.5, "missed": 0}[body.mark])
        return {"ok": True}

    class Written(BaseModel):
        text: str = Field(min_length=1, max_length=20000)

    @r.post("/api/courses/{cid}/chat/messages/{mid}/parts/{part}/grade")
    def grade_explain_back(cid: int, mid: int, part: int, body: Written):
        """An Explain back graded as in a Section: each rubric point is a one-point step of the Marking scheme."""
        m, p = practice_part(cid, mid, part, ("explain_back",))
        d = p["block"]["data"]
        scheme = [{"step": s, "points": 1.0} for s in d["rubric"]]
        workdir = ctx.course_dir(cid) / "tutor" / "graded"
        workdir.mkdir(parents=True, exist_ok=True)
        try:
            graded = run_pi_step(db, ctx.backend, "grade_answer", {"statement": d["prompt"], "model_answer": d["model_answer"], "scheme": scheme,
                                 "answer": body.text, "language": language_rule(db, cid)}, QuestionGrade, workdir, course_id=cid, live=True)
        except StepFailed as e:
            raise HTTPException(502, f"the model could not grade it (busy or unavailable): {str(e)[:300]}")
        steps = score_steps(scheme, graded)
        total, top = sum(s["awarded"] for s in steps), sum(s["points"] for s in steps)
        record(cid, m, part, p, 0, total / top if top else 0, body.text)
        return {"total": total, "max": top, "steps": steps}

    return r
