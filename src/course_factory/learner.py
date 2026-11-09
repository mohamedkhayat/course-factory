"""Learner features: reading progress, flags, quizzes and mistakes, Cards (FSRS), Focus Sessions, Daily Goal, Streak, stats."""

import datetime as dt
import json
import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from fsrs import Card, Rating, Scheduler
from pydantic import BaseModel, Field

from .chapters import LANGUAGE_RULE, block_json
from .pi_step import StepFailed, run_pi_step
from .context import Ctx

SCHEDULER = Scheduler(enable_fuzzing=False)
RATINGS = {"À revoir": Rating.Again, "Difficile": Rating.Hard, "Bien": Rating.Good, "Facile": Rating.Easy}
DEFAULT_DAILY_GOAL = 4
CARD_COMPONENTS = {"theorem_box", "key_formula", "worked_example", "exercise", "quiz"}

LEARNER_SCHEMA = """
CREATE TABLE IF NOT EXISTS reads (section_id INTEGER PRIMARY KEY REFERENCES sections(id) ON DELETE CASCADE, read_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS places (course_id INTEGER PRIMARY KEY REFERENCES courses(id), section_id INTEGER NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS block_flags (
  id INTEGER PRIMARY KEY, block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE, reason TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS quiz_attempts (
  id INTEGER PRIMARY KEY, block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE, question INTEGER NOT NULL,
  chosen TEXT NOT NULL, correct INTEGER NOT NULL, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cards (
  id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES courses(id), block_id INTEGER REFERENCES blocks(id) ON DELETE CASCADE,
  part INTEGER NOT NULL DEFAULT 0, question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
  front TEXT NOT NULL, back TEXT NOT NULL, fsrs TEXT NOT NULL, due TEXT NOT NULL,
  UNIQUE(block_id, part), UNIQUE(question_id)
);
CREATE TABLE IF NOT EXISTS reviews (id INTEGER PRIMARY KEY, card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
  rating TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS focus_sessions (
  id INTEGER PRIMARY KEY, course_id INTEGER REFERENCES courses(id), work_min INTEGER NOT NULL, break_min INTEGER NOT NULL,
  started_at TEXT NOT NULL, ended_at TEXT, active_seconds INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY, focus_id INTEGER REFERENCES focus_sessions(id), kind TEXT NOT NULL, chapter_id INTEGER,
  correct INTEGER, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def today() -> dt.date:
    return now().astimezone().date()  # days follow the machine's local clock


class Place(BaseModel):
    section_id: int


class FlagIn(BaseModel):
    reason: Literal["wrong", "unclear"]
    note: str = ""


class CodeAnswer(BaseModel):
    code: str = Field(max_length=20000)


class CodeGrade(BaseModel):
    correct: bool
    feedback: str
    hint: str = ""


class SelfMark(BaseModel):
    mark: Literal["got", "partly", "missed"]


class QuizAnswer(BaseModel):
    question: int = Field(ge=0)
    chosen: list[int] = Field(min_length=1)


class ReviewIn(BaseModel):
    rating: Literal["À revoir", "Difficile", "Bien", "Facile"]


class FocusStart(BaseModel):
    course_id: int | None = None
    work_min: int = Field(25, gt=0, le=180)
    break_min: int = Field(5, ge=0, le=60)


class FocusTick(BaseModel):
    active_seconds: int = Field(ge=0)


class Settings(BaseModel):
    daily_goal: int = Field(ge=1, le=20)


# Cards

def card_faces(block: dict) -> list[tuple[int, str, str]]:
    d, c = block["data"], block["component"]
    if c == "theorem_box":
        return [(0, f"**{d['kind'].capitalize()}** {d['title']}".strip(), d["statement"])]
    if c == "key_formula":
        return [(0, d["name"], f"$${d['latex']}$$\n\n{d['meaning']}")]
    if c == "worked_example":
        return [(0, d["problem"], "\n\n".join(d["steps"]) + f"\n\n**{d['answer']}**")]
    if c == "exercise":
        return [(0, d["statement"], d["correction"])]
    if c == "code_exercise":
        return [(0, d["task"], f"```{d['language']}\n{d['solution']}\n```")]
    if c == "fill_blanks":
        fence = (f"```{d['language']}\n", "\n```") if d["language"] else ("", "")
        gap = re.compile(r"\[\[(\d+)\]\]")
        return [(0, fence[0] + gap.sub("____", d["template"]) + fence[1],
                 fence[0] + gap.sub(lambda m: d["blanks"][int(m[1]) - 1]["answers"][0], d["template"]) + fence[1])]
    if c == "quiz":
        return [(i, q["prompt"], "\n".join(f"- {q['options'][k]}" for k in q["correct"]) + f"\n\n{q['explanation']}")
                for i, q in enumerate(d["questions"])]
    return []


def exam_eve(ctx: Ctx, cid: int) -> dt.datetime | None:
    row = ctx.db.execute("SELECT exam_date FROM courses WHERE id=?", (cid,)).fetchone()
    if not row or not row["exam_date"]:
        return None
    day = dt.date.fromisoformat(row["exam_date"]) - dt.timedelta(days=1)
    return dt.datetime.combine(day, dt.time(8), tzinfo=dt.datetime.now().astimezone().tzinfo)


def schedule(ctx: Ctx, cid: int, card: Card) -> str:
    """The FSRS due date, pulled in to the exam's eve so every Card is reviewed before the exam."""
    due = card.due
    eve = exam_eve(ctx, cid)
    if eve and now() < eve < due:
        due = eve
    return due.isoformat()


def add_card(ctx: Ctx, cid: int, front: str, back: str, block_id: int | None = None, part: int = 0, question_id: int | None = None):
    card = Card()
    card.due = now()
    ctx.db.execute("INSERT OR IGNORE INTO cards (course_id, block_id, part, question_id, front, back, fsrs, due) VALUES (?,?,?,?,?,?,?,?)",
                   (cid, block_id, part, question_id, front, back, json.dumps(card.to_dict()), card.due.isoformat()))


def unlock_section_cards(ctx: Ctx, cid: int, section_id: int) -> None:
    """A read Section's Blocks become Cards; once every Section of its Chapter is read, so do the Questions testing it."""
    db = ctx.db
    for row in db.execute("SELECT * FROM blocks WHERE section_id=? ORDER BY position", (section_id,)).fetchall():
        if row["component"] in CARD_COMPONENTS and row["status"] == "ok":
            for part, front, back in card_faces(block_json(row)):
                add_card(ctx, cid, front, back, block_id=row["id"], part=part)
    chid = db.execute("SELECT chapter_id FROM sections WHERE id=?", (section_id,)).fetchone()["chapter_id"]
    if db.execute("SELECT 1 FROM sections s WHERE s.chapter_id=? AND NOT EXISTS (SELECT 1 FROM reads r WHERE r.section_id=s.id)",
                  (chid,)).fetchone() is None:
        for q in db.execute("SELECT * FROM questions WHERE chapter_id=?", (chid,)).fetchall():
            add_card(ctx, cid, q["statement"], q["model_answer"], question_id=q["id"])


def unlock_exam_cards(ctx: Ctx, cid: int, exam_id: int) -> None:
    """Questions also become Cards once the learner has sat their Exam."""
    for q in ctx.db.execute("SELECT * FROM questions WHERE exam_id=?", (exam_id,)).fetchall():
        add_card(ctx, cid, q["statement"], q["model_answer"], question_id=q["id"])


def card_json(ctx: Ctx, cid: int, row) -> dict:
    card = Card.from_dict(json.loads(row["fsrs"]))
    preview = {}
    for label, rating in RATINGS.items():
        nxt, _ = SCHEDULER.review_card(card, rating, now())
        preview[label] = int((dt.datetime.fromisoformat(schedule(ctx, cid, nxt)) - now()).total_seconds())
    return {"id": row["id"], "front": row["front"], "back": row["back"], "due": row["due"], "next_interval_seconds": preview}


# Focus Sessions and actions

def open_session(ctx: Ctx) -> int | None:
    row = ctx.db.execute("SELECT id FROM focus_sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    return row["id"] if row else None


def record(ctx: Ctx, kind: str, chapter_id: int | None = None, correct: bool | None = None) -> None:
    ctx.db.execute("INSERT INTO actions (focus_id, kind, chapter_id, correct, at) VALUES (?,?,?,?,?)",
                   (open_session(ctx), kind, chapter_id, None if correct is None else int(correct), now().isoformat()))


def session_json(ctx: Ctx, row) -> dict:
    acts = ctx.db.execute("SELECT kind, correct FROM actions WHERE focus_id=?", (row["id"],)).fetchall()
    quiz = [a["correct"] for a in acts if a["kind"] == "quiz_answer"]
    return {"id": row["id"], "course_id": row["course_id"], "work_min": row["work_min"], "break_min": row["break_min"],
            "started_at": row["started_at"], "ended_at": row["ended_at"], "active_seconds": row["active_seconds"],
            "counts": bool(acts), "sections_read": sum(a["kind"] == "section_read" for a in acts),
            "quiz": {"correct": sum(quiz), "total": len(quiz)}, "cards_reviewed": sum(a["kind"] == "card_review" for a in acts),
            "lab_steps": sum(a["kind"] == "lab_step" for a in acts)}


def counted_days(ctx: Ctx) -> dict[dt.date, int]:
    """Local day -> number of Focus Sessions that recorded at least one action."""
    out: dict[dt.date, int] = {}
    for r in ctx.db.execute("SELECT f.started_at FROM focus_sessions f WHERE EXISTS (SELECT 1 FROM actions a WHERE a.focus_id=f.id)"):
        day = dt.datetime.fromisoformat(r["started_at"]).astimezone().date()
        out[day] = out.get(day, 0) + 1
    return out


def streak(days: set[dt.date], goal_today: dt.date) -> int:
    """Consecutive study days back from today; one missed day per ISO week is forgiven. Today not done yet doesn't break it."""
    n, day, forgiven = 0, goal_today, set()
    if day not in days:
        day -= dt.timedelta(days=1)
    while True:
        if day in days:
            n += 1
        elif day.isocalendar()[:2] not in forgiven and (day - dt.timedelta(days=1)) in days:
            forgiven.add(day.isocalendar()[:2])  # a forgiven day keeps the Streak but doesn't add to it
        else:
            return n
        day -= dt.timedelta(days=1)


def daily_goal(ctx: Ctx) -> int:
    row = ctx.db.execute("SELECT value FROM settings WHERE key='daily_goal'").fetchone()
    return int(row["value"]) if row else DEFAULT_DAILY_GOAL


def router(ctx: Ctx) -> APIRouter:
    db = ctx.db
    db.executescript(LEARNER_SCHEMA)
    r = APIRouter()

    def course_or_404(cid: int):
        row = db.execute("SELECT * FROM courses WHERE id=?", (cid,)).fetchone()
        if row is None:
            raise HTTPException(404, "no such Course")
        return row

    def published_section(cid: int, sid: int):
        row = db.execute("SELECT s.*, c.id chapter_id FROM sections s JOIN chapters c ON c.id=s.chapter_id "
                         "WHERE s.id=? AND c.course_id=? AND c.status='published'", (sid, cid)).fetchone()
        if row is None:
            raise HTTPException(404, "no such published Section")
        return row

    def published_block(cid: int, bid: int):
        row = db.execute("SELECT b.*, c.id chapter_id FROM blocks b JOIN sections s ON s.id=b.section_id JOIN chapters c ON c.id=s.chapter_id "
                         "WHERE b.id=? AND c.course_id=? AND c.status='published'", (bid, cid)).fetchone()
        if row is None:
            raise HTTPException(404, "no such published Block")
        return row

    # Reader

    @r.put("/api/courses/{cid}/place")
    def set_place(cid: int, body: Place):
        """Remembers where the learner is; opening a Section marks it read and unlocks its Cards."""
        sec = published_section(cid, body.section_id)
        db.execute("INSERT INTO places VALUES (?,?,?) ON CONFLICT(course_id) DO UPDATE SET section_id=excluded.section_id, "
                   "updated_at=excluded.updated_at", (cid, body.section_id, now().isoformat()))
        if db.execute("INSERT OR IGNORE INTO reads VALUES (?,?)", (body.section_id, now().isoformat())).rowcount:
            record(ctx, "section_read", sec["chapter_id"])
            unlock_section_cards(ctx, cid, body.section_id)
        return get_place(cid)

    @r.get("/api/courses/{cid}/place")
    def get_place(cid: int):
        course_or_404(cid)
        row = db.execute("SELECT section_id FROM places WHERE course_id=?", (cid,)).fetchone()
        read = [x["section_id"] for x in db.execute(
            "SELECT r.section_id FROM reads r JOIN sections s ON s.id=r.section_id JOIN chapters c ON c.id=s.chapter_id "
            "WHERE c.course_id=? ORDER BY r.section_id", (cid,))]
        return {"section_id": row["section_id"] if row else None, "read": read}

    @r.get("/api/courses/{cid}/sources/{name}/pages/{n}")
    def source_page(cid: int, name: str, n: int):
        """The rendered source page behind a Citation."""
        row = db.execute("SELECT p.image FROM pages p JOIN sources s ON s.id=p.source_id WHERE s.course_id=? AND s.name=? AND p.n=?",
                         (cid, name, n)).fetchone()
        if row is None or not row["image"]:
            raise HTTPException(404, "no such page")
        return FileResponse(row["image"], media_type="image/png")

    @r.post("/api/courses/{cid}/blocks/{bid}/flags", status_code=201)
    def flag_block(cid: int, bid: int, body: FlagIn):
        published_block(cid, bid)
        fid = db.execute("INSERT INTO block_flags (block_id, reason, note, created_at) VALUES (?,?,?,?)",
                         (bid, body.reason, body.note, now().isoformat())).lastrowid
        return {"id": fid}

    @r.get("/api/courses/{cid}/flags")
    def list_flags(cid: int):
        course_or_404(cid)
        return [dict(x) for x in db.execute(
            "SELECT f.* FROM block_flags f JOIN blocks b ON b.id=f.block_id JOIN sections s ON s.id=b.section_id "
            "JOIN chapters c ON c.id=s.chapter_id WHERE c.course_id=? ORDER BY f.id", (cid,))]

    # Quizzes and mistakes

    @r.post("/api/courses/{cid}/blocks/{bid}/answers")
    def answer_quiz(cid: int, bid: int, body: QuizAnswer):
        row = published_block(cid, bid)
        if row["component"] != "quiz":
            raise HTTPException(422, "not a quiz Block")
        questions = json.loads(row["data"])["questions"]
        if body.question >= len(questions):
            raise HTTPException(422, "no such question")
        q = questions[body.question]
        correct = sorted(set(body.chosen)) == sorted(set(q["correct"]))
        db.execute("INSERT INTO quiz_attempts (block_id, question, chosen, correct, at) VALUES (?,?,?,?,?)",
                   (bid, body.question, json.dumps(body.chosen), int(correct), now().isoformat()))
        record(ctx, "quiz_answer", row["chapter_id"], correct)
        return {"correct": correct, "correct_options": q["correct"], "explanation": q["explanation"]}

    @r.post("/api/courses/{cid}/blocks/{bid}/grade")
    def grade_code(cid: int, bid: int, body: CodeAnswer):
        """Grades a code_exercise answer against its task, with the reference solution as one correct answer."""
        row = published_block(cid, bid)
        if row["component"] != "code_exercise":
            raise HTTPException(422, "not a code exercise Block")
        d = json.loads(row["data"])
        try:
            grade = run_pi_step(db, ctx.backend, "grade_code", {
                "task": d["task"], "code_language": d["language"], "solution": d["solution"], "code": body.code,
                "language": LANGUAGE_RULE}, CodeGrade, ctx.course_dir(cid), course_id=cid, live=True)
        except StepFailed as e:
            raise HTTPException(502, f"grading failed: {e}")
        record(ctx, "code_answer", row["chapter_id"], grade.correct)
        return grade.model_dump()

    @r.post("/api/courses/{cid}/blocks/{bid}/self-mark")
    def self_mark(cid: int, bid: int, body: SelfMark):
        """The learner marks their own by-hand work after comparing it with the correction."""
        row = published_block(cid, bid)
        if row["component"] != "exercise" or json.loads(row["data"]).get("mode") != "hand":
            raise HTTPException(422, "not a by-hand exercise Block")
        record(ctx, "self_mark", row["chapter_id"], body.mark == "got")
        return {"ok": True}

    @r.get("/api/courses/{cid}/mistakes")
    def mistakes(cid: int):
        """Questions whose latest answer was wrong, newest first."""
        course_or_404(cid)
        rows = db.execute(
            "SELECT a.* FROM quiz_attempts a JOIN blocks b ON b.id=a.block_id JOIN sections s ON s.id=b.section_id "
            "JOIN chapters c ON c.id=s.chapter_id WHERE c.course_id=? AND a.id = (SELECT MAX(id) FROM quiz_attempts "
            "WHERE block_id=a.block_id AND question=a.question) AND a.correct=0 ORDER BY a.id DESC", (cid,)).fetchall()
        out = []
        for a in rows:
            q = json.loads(db.execute("SELECT data FROM blocks WHERE id=?", (a["block_id"],)).fetchone()["data"])["questions"][a["question"]]
            out.append({"block_id": a["block_id"], "question": a["question"], "prompt": q["prompt"], "options": q["options"],
                        "chosen": json.loads(a["chosen"]), "correct": q["correct"], "explanation": q["explanation"], "at": a["at"]})
        return out

    @r.get("/api/courses/{cid}/blocks/{bid}/stats")
    def quiz_stats(cid: int, bid: int):
        row = published_block(cid, bid)
        questions = json.loads(row["data"]).get("questions", [])
        out = [{"attempts": 0, "correct": 0, "picked": [0] * len(q["options"])} for q in questions]
        for a in db.execute("SELECT question, chosen, correct FROM quiz_attempts WHERE block_id=?", (bid,)):
            s = out[a["question"]]
            s["attempts"] += 1
            s["correct"] += a["correct"]
            for k in json.loads(a["chosen"]):
                if 0 <= k < len(s["picked"]):
                    s["picked"][k] += 1
        return out

    # Cards and Review

    @r.get("/api/courses/{cid}/cards/due")
    def due_cards(cid: int):
        course_or_404(cid)
        rows = db.execute("SELECT * FROM cards WHERE course_id=? AND due<=? ORDER BY due", (cid, now().isoformat())).fetchall()
        return [card_json(ctx, cid, x) for x in rows]

    @r.post("/api/courses/{cid}/cards/{card_id}/review")
    def review_card(cid: int, card_id: int, body: ReviewIn):
        row = db.execute("SELECT * FROM cards WHERE id=? AND course_id=?", (card_id, cid)).fetchone()
        if row is None:
            raise HTTPException(404, "no such Card")
        card, _ = SCHEDULER.review_card(Card.from_dict(json.loads(row["fsrs"])), RATINGS[body.rating], now())
        due = schedule(ctx, cid, card)
        db.execute("UPDATE cards SET fsrs=?, due=? WHERE id=?", (json.dumps(card.to_dict()), due, card_id))
        db.execute("INSERT INTO reviews (card_id, rating, at) VALUES (?,?,?)", (card_id, body.rating, now().isoformat()))
        chapter = db.execute("SELECT c.id FROM blocks b JOIN sections s ON s.id=b.section_id JOIN chapters c ON c.id=s.chapter_id "
                             "WHERE b.id=?", (row["block_id"],)).fetchone() if row["block_id"] else None
        record(ctx, "card_review", chapter["id"] if chapter else None)
        return {"id": card_id, "due": due}

    # Focus Sessions, Daily Goal, Streak

    @r.post("/api/focus", status_code=201)
    def start_focus(body: FocusStart):
        if body.course_id is not None:
            course_or_404(body.course_id)
        db.execute("UPDATE focus_sessions SET ended_at=? WHERE ended_at IS NULL", (now().isoformat(),))
        fid = db.execute("INSERT INTO focus_sessions (course_id, work_min, break_min, started_at) VALUES (?,?,?,?)",
                         (body.course_id, body.work_min, body.break_min, now().isoformat())).lastrowid
        return session_json(ctx, db.execute("SELECT * FROM focus_sessions WHERE id=?", (fid,)).fetchone())

    def focus_or_404(fid: int):
        row = db.execute("SELECT * FROM focus_sessions WHERE id=?", (fid,)).fetchone()
        if row is None:
            raise HTTPException(404, "no such Focus Session")
        return row

    @r.post("/api/focus/{fid}/tick")
    def tick(fid: int, body: FocusTick):
        """The client reports seconds of active time; capped by the Session's wall-clock length."""
        row = focus_or_404(fid)
        if row["ended_at"]:
            raise HTTPException(409, "this Focus Session has ended")
        wall = int((now() - dt.datetime.fromisoformat(row["started_at"])).total_seconds())
        db.execute("UPDATE focus_sessions SET active_seconds=? WHERE id=?", (min(wall, row["active_seconds"] + body.active_seconds), fid))
        return session_json(ctx, focus_or_404(fid))

    @r.post("/api/focus/{fid}/end")
    def end_focus(fid: int):
        if focus_or_404(fid)["ended_at"]:
            raise HTTPException(409, "this Focus Session has ended")
        db.execute("UPDATE focus_sessions SET ended_at=? WHERE id=?", (now().isoformat(), fid))
        return session_json(ctx, focus_or_404(fid))

    @r.get("/api/focus/{fid}")
    def get_focus(fid: int):
        return session_json(ctx, focus_or_404(fid))

    @r.put("/api/settings")
    def put_settings(body: Settings):
        db.execute("INSERT INTO settings VALUES ('daily_goal', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(body.daily_goal),))
        return {"daily_goal": daily_goal(ctx)}

    @r.get("/api/stats")
    def stats(course_id: int | None = None):
        days = counted_days(ctx)
        heat: dict[str, int] = {}
        for f in db.execute("SELECT started_at, active_seconds FROM focus_sessions f WHERE EXISTS (SELECT 1 FROM actions a WHERE a.focus_id=f.id)"):
            day = dt.datetime.fromisoformat(f["started_at"]).astimezone().date().isoformat()
            heat[day] = heat.get(day, 0) + f["active_seconds"] // 60
        out = {"daily_goal": daily_goal(ctx), "today_sessions": days.get(today(), 0), "streak": streak(set(days), today()),
               "heatmap": heat}
        if course_id is not None:
            course = course_or_404(course_id)
            out["exam_countdown_days"] = (dt.date.fromisoformat(course["exam_date"]) - today()).days if course["exam_date"] else None
            out["minutes_per_chapter"] = minutes_per_chapter(course_id)
        return out

    def minutes_per_chapter(cid: int) -> dict[int, int]:
        """A Session's active minutes, shared evenly among the Chapters it touched."""
        out: dict[int, float] = {}
        for f in db.execute("SELECT id, active_seconds FROM focus_sessions").fetchall():
            chs = [a["chapter_id"] for a in db.execute(
                "SELECT DISTINCT a.chapter_id FROM actions a JOIN chapters c ON c.id=a.chapter_id WHERE a.focus_id=? AND c.course_id=?",
                (f["id"], cid))]
            for ch in chs:
                out[ch] = out.get(ch, 0) + f["active_seconds"] / 60 / len(chs)
        return {ch: round(m) for ch, m in out.items()}

    return r
