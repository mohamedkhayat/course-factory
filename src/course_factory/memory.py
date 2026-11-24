"""Learner memory: one-line facts about how the owner learns, read by the tutors and by Section writing. Preferences (no Course)
hold everywhere; patterns found in results (learner.refresh_patterns) belong to their Course."""
import datetime as dt
import json
import re

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from .context import Ctx

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
  id INTEGER PRIMARY KEY, course_id INTEGER REFERENCES courses(id), kind TEXT NOT NULL, text TEXT NOT NULL, origin TEXT NOT NULL,
  key TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""
OPEN = "```remember"
CLOSE = "\n```"
MAX_CHARS = 200
CAP = 20  # facts sent with a call: the rest would crowd out the material
LABELS = {"said": "you said so", "results": "from your results", "explain_differently": "from your Explain differently choices",
          "challenge": "found by a Challenge"}


class Hider:
    """Passes streamed text through without ever letting a ```remember fence out; the fences' bodies are kept in `fences`."""

    def __init__(self):
        self.buf, self.inside, self.fences = "", False, []

    def feed(self, chunk: str) -> str:
        self.buf += chunk
        out = ""
        while True:
            if not self.inside:
                i = self.buf.find(OPEN)
                if i < 0:
                    hold = next((k for k in range(len(OPEN) - 1, 0, -1) if self.buf.endswith(OPEN[:k])), 0)  # maybe the start of a fence
                    out += self.buf[:len(self.buf) - hold]
                    self.buf = self.buf[len(self.buf) - hold:]
                    return out
                out += self.buf[:i]
                self.buf, self.inside = self.buf[i + len(OPEN):], True
            else:
                j = self.buf.find(CLOSE)
                if j < 0:
                    return out
                self.fences.append(self.buf[:j])
                self.buf, self.inside = self.buf[j + len(CLOSE):].lstrip("\n"), False

    def finish(self) -> str:
        if self.inside:  # never closed: still not text for the learner
            self.fences.append(self.buf)
            self.buf = ""
        out, self.buf = self.buf, ""
        return out


def line_of(text) -> str | None:
    """The fact's text if it is one non-empty line within the limit."""
    text = text.strip() if isinstance(text, str) else ""
    return text if text and "\n" not in text and len(text) <= MAX_CHARS else None


def concepts(db, cid: int) -> set[str]:
    return {c for s in db.execute("SELECT s.teaches FROM sections s JOIN chapters c ON c.id=s.chapter_id WHERE c.course_id=?", (cid,))
            for c in json.loads(s["teaches"])}


def fact_json(row) -> dict:
    return {"id": row["id"], "course_id": row["course_id"], "kind": row["kind"], "text": row["text"], "origin": json.loads(row["origin"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def upsert(db, cid: int | None, kind: str, key: str, text: str, origin: dict, at: str) -> int | None:
    """Saves a fact; its key replaces or dedupes. A pattern's text and origin follow the results; a preference already there stays
    as it is. Returns the id of a new or changed fact, None when nothing was saved."""
    old = db.execute("SELECT * FROM memory WHERE course_id IS ? AND key=?", (cid, key)).fetchone()
    if old is None:
        return db.execute("INSERT INTO memory (course_id, kind, text, origin, key, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                          (cid, kind, text, json.dumps(origin, ensure_ascii=False), key, at, at)).lastrowid
    if kind == "pattern" and old["text"] != text:
        db.execute("UPDATE memory SET text=?, origin=?, updated_at=? WHERE id=?", (text, json.dumps(origin, ensure_ascii=False), at, old["id"]))
        return old["id"]
    return None


def drop(db, cid: int, key: str) -> None:
    db.execute("DELETE FROM memory WHERE course_id=? AND key=?", (cid, key))


def facts(db, cid: int) -> list[dict]:
    """All preferences and the Course's patterns, newest first, capped."""
    return [fact_json(r) for r in db.execute("SELECT * FROM memory WHERE course_id IS NULL OR course_id=? ORDER BY updated_at DESC, id DESC LIMIT ?",
                                             (cid, CAP))]


def memory_text(db, cid: int) -> str:
    """The facts as Markdown lines for the prompts; the id lets the model replace a preference."""
    return "\n".join(f"- [{f['id']}] {f['text']} ({LABELS[f['origin']['by']]}, {f['updated_at'][:10]})" for f in facts(db, cid)) \
        or "(nothing remembered yet)"


def remember(db, bodies: list[str], cid: int, message: int, at: str) -> dict | None:
    """The fact a reply's ```remember fence asks for (the last one, if the model wrote several), or None when it is invalid or
    already known. A preference holds for all Courses, optionally replacing one the learner now contradicts."""
    try:
        o = json.loads(bodies[-1]) if bodies else None
    except json.JSONDecodeError:
        return None
    text = line_of(o.get("text")) if isinstance(o, dict) else None
    if text is None:
        return None
    if o.get("kind") == "preference":
        if isinstance(o.get("replaces"), int):
            db.execute("DELETE FROM memory WHERE id=? AND kind='preference'", (o["replaces"],))
        key, scope, origin = " ".join(re.findall(r"\w+", text.lower())), None, {"by": "said", "message": message}
    elif o.get("kind") == "misunderstanding" and o.get("concept") in concepts(db, cid):
        key, scope, origin = f"challenge:{o['concept']}", cid, {"by": "challenge", "concept": o["concept"], "message": message}
    else:
        return None
    fid = upsert(db, scope, "preference" if scope is None else "pattern", key, text, origin, at)
    return {"id": fid, "text": text} if fid else None


def remembered_json(db, fid) -> dict | None:
    """The fact a stored message made, unless it was undone since."""
    row = db.execute("SELECT id, text FROM memory WHERE id=?", (fid,)).fetchone() if fid else None
    return dict(row) if row else None


class Preference(BaseModel):
    text: str = Field(min_length=1)


def router(ctx: Ctx) -> APIRouter:
    db = ctx.db
    r = APIRouter()

    def checked(text: str) -> str:
        if (line := line_of(text)) is None:
            raise HTTPException(422, f"one line of at most {MAX_CHARS} characters")
        return line

    @r.get("/api/memory")
    def listing(course_id: int | None = None):
        """Every fact, preferences first, then patterns by Course; or one Course's patterns with the preferences."""
        rows = db.execute("SELECT m.*, c.name course FROM memory m LEFT JOIN courses c ON c.id=m.course_id WHERE ? IS NULL OR m.course_id IS NULL "
                          "OR m.course_id=? ORDER BY m.course_id IS NOT NULL, m.course_id, m.updated_at DESC, m.id DESC", (course_id, course_id))
        return [fact_json(m) | {"course": m["course"]} for m in rows]

    @r.post("/api/memory", status_code=201)
    def add(body: Preference):
        text = checked(body.text)
        at = dt.datetime.now(dt.UTC).isoformat()
        fid = upsert(db, None, "preference", " ".join(re.findall(r"\w+", text.lower())), text, {"by": "said"}, at)
        if fid is None:
            raise HTTPException(409, "already remembered")
        return fact_json(db.execute("SELECT * FROM memory WHERE id=?", (fid,)).fetchone())

    @r.put("/api/memory/{fid}")
    def edit(fid: int, body: Preference):
        text = checked(body.text)
        if not db.execute("UPDATE memory SET text=? WHERE id=?", (text, fid)).rowcount:
            raise HTTPException(404, "no such fact")
        return fact_json(db.execute("SELECT * FROM memory WHERE id=?", (fid,)).fetchone())

    @r.delete("/api/memory/{fid}", status_code=204)
    def delete(fid: int):
        """Delete in Settings, and Undo under an answer."""
        if not db.execute("DELETE FROM memory WHERE id=?", (fid,)).rowcount:
            raise HTTPException(404, "no such fact")
        return Response(status_code=204)

    return r
