"""Cram: Question Types, Exam Likelihood, the Cheat Sheet, exam technique, mixed practice and the Cram Plan.

Everything here is computed from the past papers and the learner's progress; the model only sorts Questions into types."""

import datetime as dt
import json
import re
import math
import random

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from . import learner
from .chapters import language_rule, block_json
from .context import Ctx
from .outline import profile_of
from .pi_step import StepFailed, run_pi_step

LEVELS = ("high", "medium", "low")
ITEM_KINDS = {"theorem_box", "key_formula", "algorithm"}  # the Blocks a fallback on Chapter Exam Weight rates
SECTION_MIN, PASS_MIN, CARDS_MIN, MISTAKES_MIN, VARIANTS_MIN, MIXED_MIN = 15, 20, 15, 15, 15, 25
EVE_SHEET_MIN, EVE_MISTAKES_MIN, EVE_RETRIEVAL_MIN = 30, 20, 30
REVIEW_KINDS = ("card_review", "quiz_answer", "self_mark", "written_grade", "code_answer", "mixed")


class TypePlan(BaseModel):
    name: str = Field(min_length=1)
    trigger: str = ""
    chapter: str | None = None
    template: str = ""
    questions: list[int] = Field(min_length=1)


class TypesPlan(BaseModel):
    types: list[TypePlan] = Field(min_length=1)


class CramSettings(BaseModel):
    hours_per_day: float = Field(gt=0, le=16)


class MixedMark(BaseModel):
    mark: str = Field(pattern="^(got|partly|missed)$")
    chapter_id: int | None = None
    block_id: int | None = None
    question_id: int | None = None


# Question Types

def past_questions(db, cid: int, scoped: bool = True) -> list:
    """The Past papers' Questions; scoped: only the papers set for the learner's cohort, the ones that weigh the Course."""
    return db.execute("SELECT q.*, e.id exam_id, e.title exam, e.duration_min, c.title chapter FROM questions q "
                      "JOIN exams e ON e.id=q.exam_id LEFT JOIN chapters c ON c.id=q.chapter_id "
                      "WHERE e.course_id=? AND e.kind='past_paper' AND (e.in_scope=1 OR NOT ?) ORDER BY e.id, q.position", (cid, scoped)).fetchall()


def classify_questions(ctx: Ctx, cid: int, force: bool = False) -> None:
    """Sorts the past papers' Questions into Question Types, once (force re-sorts). A Question the model leaves out
    gets its Chapter's catch-all type, so every Question counts."""
    db = ctx.db
    qs = past_questions(db, cid, scoped=False)  # every paper gets types: changing the scope then needs no model
    if not qs or (not force and all(q["question_type_id"] for q in qs)):
        return
    titles = {r["title"]: r["id"] for r in db.execute("SELECT id, title FROM chapters WHERE course_id=? ORDER BY position", (cid,))}
    plan = run_pi_step(db, ctx.backend, "classify_questions", {
        "questions": [{"id": q["id"], "statement": q["statement"], "points": q["points"], "chapter": q["chapter"],
                       "model_answer": q["model_answer"], "scheme": json.loads(q["scheme"] or "null")} for q in qs],
        "chapters": list(titles), "language": language_rule(db, cid)}, TypesPlan, ctx.course_dir(cid), course_id=cid)
    by_id = {q["id"]: q for q in qs}
    types: dict[str, dict] = {}
    seen: set[int] = set()
    for t in plan.types:
        mine = [i for i in t.questions if i in by_id and i not in seen]
        seen |= set(mine)
        if mine:
            entry = types.setdefault(t.name.strip(), {"trigger": t.trigger, "template": t.template,
                                                      "chapter_id": titles.get(t.chapter or ""), "questions": []})
            entry["questions"] += mine
    for q in qs:
        if q["id"] not in seen:
            name = f"{q['chapter'] or 'Other'}: other questions"
            types.setdefault(name, {"trigger": "", "template": "", "chapter_id": q["chapter_id"], "questions": []})["questions"].append(q["id"])
    db.execute("UPDATE questions SET question_type_id=NULL WHERE exam_id IN (SELECT id FROM exams WHERE course_id=?)", (cid,))
    db.execute("DELETE FROM question_types WHERE course_id=?", (cid,))
    for name, t in types.items():
        chapter_id = t["chapter_id"] or most_common([by_id[i]["chapter_id"] for i in t["questions"]])
        tid = db.execute("INSERT INTO question_types (course_id, name, trigger, template, chapter_id) VALUES (?,?,?,?,?)",
                         (cid, name, t["trigger"], t["template"], chapter_id)).lastrowid
        db.execute(f"UPDATE questions SET question_type_id=? WHERE id IN ({','.join('?' * len(t['questions']))})", (tid, *t["questions"]))


def most_common(xs: list):
    xs = [x for x in xs if x is not None]
    return max(set(xs), key=xs.count) if xs else None


def thirds(values: dict) -> dict:
    """Rank -> level: the top third (by value) is high, the next third medium, the rest low. Zero is never rated."""
    ranked = sorted((k for k, v in values.items() if v > 0), key=lambda k: -values[k])
    n = len(ranked)
    return {k: LEVELS[min(2, i * 3 // n)] for i, k in enumerate(ranked)}


def question_types(db, cid: int) -> list[dict]:
    """Every Question Type with its points, how many past papers ask it, its share of the points and its Exam Likelihood."""
    rows = db.execute("SELECT t.*, c.title chapter FROM question_types t LEFT JOIN chapters c ON c.id=t.chapter_id "
                      "WHERE t.course_id=? ORDER BY t.id", (cid,)).fetchall()
    qs = past_questions(db, cid)
    total = sum(q["points"] for q in qs) or 1
    prepared: dict[str, int] = {}  # coverage: how many Blocks prepare for each type
    for (names,) in db.execute("SELECT b.exam_types FROM blocks b JOIN sections s ON s.id=b.section_id JOIN chapters c ON c.id=s.chapter_id "
                               "WHERE c.course_id=?", (cid,)):
        for n in json.loads(names or "[]"):
            prepared[n] = prepared.get(n, 0) + 1
    out = []
    for t in rows:
        mine = [q for q in qs if q["question_type_id"] == t["id"]]
        if not mine:
            continue  # asked only in papers for another cohort
        out.append({"id": t["id"], "name": t["name"], "trigger": t["trigger"], "template": t["template"],
                    "chapter_id": t["chapter_id"], "chapter": t["chapter"], "points": sum(q["points"] for q in mine),
                    "papers": len({q["exam_id"] for q in mine}), "blocks": prepared.get(t["name"], 0), "share": round(sum(q["points"] for q in mine) / total, 3),
                    "questions": [{"id": q["id"], "exam": q["exam"], "points": q["points"], "statement": q["statement"]} for q in mine]})
    levels = thirds({t["name"]: t["points"] * (1 + 0.5 * (t["papers"] - 1)) for t in out})  # asked in several papers weighs more
    for t in out:
        t["likelihood"] = levels.get(t["name"], "low")
    return sorted(out, key=lambda t: -t["points"])


def minutes_per_point(db, cid: int) -> float | None:
    row = db.execute("SELECT SUM(e.duration_min) d, (SELECT SUM(q.points) FROM questions q JOIN exams e2 ON e2.id=q.exam_id "
                     "WHERE e2.course_id=? AND e2.kind='past_paper' AND e2.in_scope=1) p FROM exams e "
                     "WHERE e.course_id=? AND e.kind='past_paper' AND e.in_scope=1",
                     (cid, cid)).fetchone()
    return row["d"] / row["p"] if row["d"] and row["p"] else None


class Likelihood:
    """Exam Likelihood of Blocks: from the Question Types a Block prepares for, else (for items) from its Chapter's Exam Weight."""

    def __init__(self, db, cid: int):
        self.types = {t["name"]: t for t in question_types(db, cid)}
        self.chapters = thirds({r["id"]: r["exam_weight"] for r in db.execute("SELECT id, exam_weight FROM chapters WHERE course_id=?", (cid,))})
        self.mpp = minutes_per_point(db, cid)

    def of(self, component: str, exam_types: list[str], chapter_id: int) -> str | None:
        levels = [self.types[n]["likelihood"] for n in exam_types if n in self.types]
        if levels:
            return min(levels, key=LEVELS.index)
        if component in ITEM_KINDS and chapter_id in self.chapters:
            return max(self.chapters[chapter_id], "medium", key=LEVELS.index)  # an unlinked item is at most medium
        return None

    def minutes(self, block: dict, exam_types: list[str]) -> int | None:
        """An exercise's time limit: its own, else the exam's minutes for the mean points of its Question Types' Questions."""
        if block["component"] != "exercise":
            return None
        if block["data"].get("minutes"):
            return block["data"]["minutes"]
        pts = [q["points"] for n in exam_types if n in self.types for q in self.types[n]["questions"]]
        return max(1, round(self.mpp * sum(pts) / len(pts))) if pts and self.mpp else None


def annotate(ctx: Ctx, cid: int, chapters: list[dict]) -> list[dict]:
    """Adds Cram info to the Reader's Chapters: each Chapter's Cram Profile, each Block's Exam Likelihood, the past
    Questions it prepares for and an exercise's time limit. Deep Courses are left as they are."""
    db = ctx.db
    if db.execute("SELECT goal FROM courses WHERE id=?", (cid,)).fetchone()["goal"] != "cram":
        return chapters
    lk = Likelihood(db, cid)
    for ch in chapters:
        ch["profile"] = profile_of(ctx, db.execute("SELECT * FROM chapters WHERE id=?", (ch["id"],)).fetchone())
        for s in ch["sections"]:
            for b in s["blocks"]:
                names = b.get("exam_types", [])
                info = {"likelihood": lk.of(b["component"], names, ch["id"]), "types": [n for n in names if n in lk.types],
                        "questions": [{"id": q["id"], "exam": q["exam"], "points": q["points"]}
                                      for n in names if n in lk.types for q in lk.types[n]["questions"]][:3],
                        "minutes": lk.minutes(b, names)}
                if any(info.values()):
                    b["cram"] = info
    return chapters


# Cheat Sheet

KINDS = ["definition", "theorem", "proposition", "lemma", "corollary", "property", "formula", "method", "question", "commands", "tip", "trap", "exam"]
REPEAT_TEXT = 0.6  # share of distinct words two items of a kind share before the later one is a repeat


def cheat_item(b: dict) -> tuple[str, str, str, list[dict] | None] | None:
    """(kind, title, Markdown body, command rows) of a Block worth a line on the Cheat Sheet, or None. A terminal's
    commands become {command, note} rows, so its notes render as Markdown beside the code, not inside it."""
    d, c = b["data"], b["component"]
    if c == "theorem_box":
        return d["kind"], d.get("title", ""), d["statement"], None
    if c == "key_formula":
        return "formula", d["name"], f"$${d['latex']}$$\n\n{d['meaning']}", None
    if c == "algorithm":
        steps = "\n".join(f"{i}. {s}" for i, s in enumerate(d["steps"], 1))
        return "method", d["name"], (f"*When:* {d['when']}\n\n" if d.get("when") else "") + steps, None
    if c == "callout" and d["tone"] in ("warning", "exam", "tip"):
        return {"warning": "trap", "exam": "exam", "tip": "tip"}[d["tone"]], "", d["text"], None
    if c == "terminal":
        rows = [{"command": e["command"].strip(), "note": (e.get("note") or "").strip()} for e in d["entries"] if e["command"].strip()]
        return "commands", d.get("title", ""), rows_text(rows), rows
    return None


def rows_text(rows: list[dict]) -> str:
    return "\n".join(r["command"] + "\n" + r["note"] for r in rows)


def compile_sheet(candidates: list[dict]) -> dict:
    """The sheet from its candidate items: repeats merged (a command already listed, or a text sharing most of its words
    with a likelier item of its kind, which wins), then shown by Chapter and kind. Each candidate has `_rank`
    (likelihood, then course order) and `_order` (course order)."""
    words = lambda i: set(re.findall(r"\w{4,}", (i["title"] + " " + i["body"]).lower()))
    seen: set[str] = set()
    distinct: list[dict] = []
    for i in sorted(candidates, key=lambda i: i["_rank"]):
        if i["rows"] is not None:
            rows = [r for r in i["rows"] if " ".join(r["command"].split()) not in seen]
            seen |= {" ".join(r["command"].split()) for r in i["rows"]}
            if not rows:
                continue
            i = i | {"rows": rows, "body": rows_text(rows)}
        elif any(k["kind"] == i["kind"] and len(words(i) & words(k)) >= REPEAT_TEXT * min(len(words(i)), len(words(k)))
                 for k in distinct if words(i) and words(k)):
            continue
        distinct.append(i)
    distinct.sort(key=lambda i: (i["_order"][0], KINDS.index(i["kind"]) if i["kind"] in KINDS else len(KINDS), i["_order"]))
    return {"items": [{k: v for k, v in i.items() if not k.startswith("_")} for i in distinct]}


def cheat_sheet(ctx: Ctx, cid: int, chapter_id: int | None = None) -> dict:
    """The Cheat Sheet, compiled from the published, checked Blocks (compile_sheet). Every item links back to its Section."""
    db = ctx.db
    lk = Likelihood(db, cid)
    items = []
    for row in db.execute("SELECT b.*, s.id sid, s.title section, s.position spos, c.id chid, c.title chapter, c.position cpos "
                          "FROM blocks b JOIN sections s ON s.id=b.section_id JOIN chapters c ON c.id=s.chapter_id "
                          "WHERE c.course_id=? AND c.status='published' AND b.status='ok' AND (? IS NULL OR c.id=?)",
                          (cid, chapter_id, chapter_id)).fetchall():
        item = cheat_item(block_json(row))
        if item:
            level = lk.of(row["component"], json.loads(row["exam_types"]), row["chid"])
            order = (row["cpos"], row["spos"], row["position"])
            items.append({"block_id": row["id"], "kind": item[0], "title": item[1], "body": item[2], "rows": item[3], "likelihood": level,
                          "chapter_id": row["chid"], "chapter": row["chapter"], "section_id": row["sid"], "section": row["section"],
                          "_rank": (LEVELS.index(level) if level else 3, *order), "_order": order})
    # the past papers' Question Types: how to recognise each and the steps that earn its marks; one asked across Chapters goes first
    pos = dict(db.execute("SELECT id, position FROM chapters WHERE course_id=?", (cid,)).fetchall())
    for n, t in enumerate(question_types(db, cid)):
        if chapter_id is None or t["chapter_id"] == chapter_id:
            body = (f"*Recognise it:* {t['trigger']}\n\n" if t["trigger"] else "") + t["template"]
            order = (pos.get(t["chapter_id"], -1), -1, n)
            items.append({"block_id": -t["id"], "kind": "question", "title": t["name"], "body": body, "rows": None,
                          "likelihood": t["likelihood"], "chapter_id": t["chapter_id"], "chapter": t["chapter"] or "Across the Chapters",
                          "section_id": None, "section": None, "_rank": (LEVELS.index(t["likelihood"]), *order), "_order": order})
    return compile_sheet(items)


def technique(ctx: Ctx, cid: int) -> dict:
    """Exam technique from the past papers: minutes per point, and per Question Type its trigger, answer template and
    the steps the Marking schemes give marks for."""
    db = ctx.db
    papers = [{"title": e["title"], "duration_min": e["duration_min"], "points": e["points"]} for e in db.execute(
        "SELECT e.title, e.duration_min, SUM(q.points) points FROM exams e JOIN questions q ON q.exam_id=e.id "
        "WHERE e.course_id=? AND e.kind='past_paper' AND e.in_scope=1 GROUP BY e.id ORDER BY e.id", (cid,))]
    schemes = {q["id"]: json.loads(q["scheme"] or "null") or [] for q in past_questions(db, cid)}
    types = []
    for t in question_types(db, cid):
        marks: dict[str, float] = {}
        for q in t["questions"]:
            for s in schemes.get(q["id"], []):
                marks[s["step"]] = marks.get(s["step"], 0) + s["points"]
        types.append({k: t[k] for k in ("name", "trigger", "template", "points", "papers", "likelihood", "chapter")}
                     | {"method_marks": [{"step": k, "points": v} for k, v in sorted(marks.items(), key=lambda kv: -kv[1])[:6]]})
    return {"minutes_per_point": minutes_per_point(db, cid), "papers": papers, "types": types}


# Cram Plan

def plan(today: dt.date, exam_date: dt.date, minutes_per_day: int, topics: list[dict], due_cards: int = 0,
         mistakes: int = 0, mistake_types: list[str] = (), mocks: list[dict] = ()) -> dict:
    """The day-by-day Cram Plan from today to the exam's eve. Pure: recomputed on every change, never stored.

    topics: {chapter_id, title, priority, profile, points, learn_minutes, reviews_done, section_id}, in course order.
    mocks: {exam_id, title, duration_min, done}, Mock exams first. Rules (see the spec's evidence notes): triage by points
    per minute with Priority focus always kept; three spaced passes per kept topic (learn, then two retrievals); mixed
    practice once two problem topics are learnt; two timed Mock exams in the final week (one when under four days remain),
    but never at the cost of a topic; the eve is the Cheat Sheet, mistakes and light retrieval only."""
    n = (exam_date - today).days
    if n <= 0:
        return {"days": [], "skip": [], "skipped_points": 0, "kept_points": 0}
    wanted = 0 if n < 2 else 1 if n < 4 else 2
    wanted = max(0, wanted - sum(1 for m in mocks if m.get("done")))
    pending = [m for m in mocks if not m.get("done")]
    args = (today, n, minutes_per_day, topics, due_cards, mistakes, mistake_types)
    base = _plan(*args, [])
    for k in range(min(wanted, len(pending)), 0, -1):
        out = _plan(*args, pending[:k])
        if out["skipped_points"] <= base["skipped_points"] and len(out["skip"]) <= len(base["skip"]):
            return out
    return base


def _plan(today, n, minutes_per_day, topics, due_cards, mistakes, mistake_types, mocks) -> dict:
    out: dict = {"days": [], "skip": [], "skipped_points": 0, "kept_points": 0}
    eve = n - 1
    cap = [minutes_per_day] * n
    days: list[list[dict]] = [[] for _ in range(n)]

    def put(d: int, act: dict):
        days[d].append(act)
        cap[d] -= act["minutes"]

    put(eve, {"kind": "cheatsheet", "title": "Read and rebuild the Cheat Sheet", "minutes": min(EVE_SHEET_MIN, cap[eve])})
    if mistakes and cap[eve] > 0:
        put(eve, {"kind": "mistakes", "title": "Go over your mistakes", "minutes": min(EVE_MISTAKES_MIN, cap[eve])})
    if cap[eve] > 0:
        put(eve, {"kind": "cards", "title": "Light retrieval: due Cards, no new material", "minutes": min(EVE_RETRIEVAL_MIN, cap[eve])})
    mock_days = [eve - 1, max(0, eve - 3)]
    for d, m in zip(mock_days, mocks):
        put(d, {"kind": "mock", "title": f"Timed Mock exam: {m['title']}", "minutes": m["duration_min"] + 20, "exam_id": m["exam_id"]})
    for d in range(eve):
        if d > 0 or due_cards:
            put(d, {"kind": "cards", "title": "Due Cards", "minutes": CARDS_MIN})
        if (mistakes or d > 0) and d not in mock_days[:len(mocks)]:  # a Mock exam's correction is the day's mistakes
            put(d, {"kind": "mistakes", "title": "Redo yesterday's mistakes", "minutes": MISTAKES_MIN})
        if mistake_types and d == 0:
            put(d, {"kind": "variants", "title": "Variants of what you missed: " + ", ".join(mistake_types),
                    "minutes": VARIANTS_MIN, "types": list(mistake_types)})

    def cost(t):
        return t["learn_minutes"] + max(0, 2 - t["reviews_done"]) * PASS_MIN

    budget = sum(max(0, c) for c in cap[:eve])
    ranked = sorted(topics, key=lambda t: (t["priority"] != "focus", -(t["points"] / cost(t)) if cost(t) else -math.inf))
    kept = []
    for t in ranked:
        if t["priority"] == "focus" or cost(t) <= budget:
            kept.append(t)
            budget -= cost(t)
        else:
            out["skip"].append({"chapter_id": t["chapter_id"], "title": t["title"], "points": t["points"]})
    out["skipped_points"] = sum(s["points"] for s in out["skip"])
    out["kept_points"] = sum(t["points"] for t in kept)

    gap = max(2, round(n * 0.2))  # the second retrieval waits longer: a gap of about a fifth of the time left
    d, learnt, problem_days = 0, {}, []
    for t in kept:
        left, last = t["learn_minutes"], -1
        while left > 0 and d < eve:
            take = min(left, cap[d])
            if take >= min(5, left):
                put(d, {"kind": "learn", "title": f"Learn: {t['title']}", "minutes": take, "chapter_id": t["chapter_id"],
                        "section_id": t.get("section_id")})
                left, last = left - take, d
            if cap[d] < 5:
                d += 1
        learnt[t["chapter_id"]] = last
        if t["profile"] == "problem":
            problem_days.append(last)
    for t in kept:
        ld = learnt[t["chapter_id"]]
        for p, offset in list(enumerate((1, 1 + gap), start=2))[t["reviews_done"]:]:
            if eve == 0:
                break
            target = min(max(ld + offset, 0), eve - 1)
            day = next((x for x in range(target, eve) if cap[x] >= PASS_MIN), target)
            put(day, {"kind": "review", "title": f"Retrieval pass {p}: {t['title']}", "minutes": PASS_MIN, "chapter_id": t["chapter_id"]})
    if len(problem_days) >= 2:
        start = sorted(problem_days)[1] + 1
        for x in range(max(start, 0), eve):
            if cap[x] >= MIXED_MIN and not any(a["kind"] == "mock" for a in days[x]):
                put(x, {"kind": "mixed", "title": "Mixed practice across problem types", "minutes": MIXED_MIN})
    order = ["cards", "mistakes", "variants", "learn", "review", "mixed", "mock", "cheatsheet"]
    out["days"] = [{"date": (today + dt.timedelta(days=i)).isoformat(), "eve": i == eve,
                    "minutes": sum(a["minutes"] for a in acts), "activities": sorted(acts, key=lambda a: order.index(a["kind"]))}
                   for i, acts in enumerate(days)]
    return out


def mistakes_of(db, cid: int) -> list:
    """Quiz Blocks whose latest answer to one of their questions was wrong."""
    return db.execute(
        "SELECT DISTINCT b.id, b.exam_types FROM quiz_attempts a JOIN blocks b ON b.id=a.block_id JOIN sections s ON s.id=b.section_id "
        "JOIN chapters c ON c.id=s.chapter_id WHERE c.course_id=? AND a.correct=0 AND a.id=(SELECT MAX(id) FROM quiz_attempts "
        "WHERE block_id=a.block_id AND question=a.question)", (cid,)).fetchall()


def course_plan(ctx: Ctx, cid: int) -> dict:
    db = ctx.db
    course = db.execute("SELECT * FROM courses WHERE id=?", (cid,)).fetchone()
    today = learner.today()
    pts = {}
    for q in past_questions(db, cid):
        pts[q["chapter_id"]] = pts.get(q["chapter_id"], 0) + q["points"]
    topics = []
    for ch in db.execute("SELECT * FROM chapters WHERE course_id=? AND priority!='skip' ORDER BY position", (cid,)).fetchall():
        unread = db.execute("SELECT s.id FROM sections s WHERE s.chapter_id=? AND NOT EXISTS (SELECT 1 FROM reads r WHERE r.section_id=s.id) "
                            "ORDER BY s.position", (ch["id"],)).fetchall()
        reviews = db.execute(f"SELECT COUNT(DISTINCT substr(at, 1, 10)) FROM actions WHERE chapter_id=? AND kind IN ({','.join('?' * len(REVIEW_KINDS))})",
                             (ch["id"], *REVIEW_KINDS)).fetchone()[0]
        topics.append({"chapter_id": ch["id"], "title": ch["title"], "priority": ch["priority"], "profile": profile_of(ctx, ch),
                       "points": pts.get(ch["id"], 0), "learn_minutes": len(unread) * SECTION_MIN, "ready": ch["status"] == "published",
                       "reviews_done": min(2, reviews if not unread else 0), "section_id": unread[0]["id"] if unread else None})
    mistaken = mistakes_of(db, cid)
    types = sorted({n for m in mistaken for n in json.loads(m["exam_types"])})
    mocks = [{"exam_id": e["id"], "title": e["title"], "duration_min": e["duration_min"],
              "done": bool(db.execute("SELECT 1 FROM copies WHERE exam_id=? AND handed_in_at IS NOT NULL", (e["id"],)).fetchone())}
             for e in db.execute("SELECT * FROM exams WHERE course_id=? AND (kind!='past_paper' OR in_scope=1) "
                                "ORDER BY kind='past_paper', id", (cid,))]
    due = db.execute("SELECT COUNT(*) FROM cards WHERE course_id=? AND due<=?", (cid, learner.now().isoformat())).fetchone()[0]
    if not course["exam_date"]:
        return {"days": [], "skip": [], "skipped_points": 0, "kept_points": 0, "needs_date": True}
    out = plan(today, dt.date.fromisoformat(course["exam_date"]), round(course["hours_per_day"] * 60), topics, due,
               len(mistaken), types, mocks)
    ready = {t["chapter_id"]: t["ready"] for t in topics}
    for day in out["days"]:
        for a in day["activities"]:
            if "chapter_id" in a:
                a["ready"] = ready.get(a["chapter_id"], False)
    if out["days"]:
        done_today = done_kinds(db, cid, today, due, len(mistaken))
        for a in out["days"][0]["activities"]:
            a["done"] = done_today(a)
        out["next"] = next((a for a in out["days"][0]["activities"] if not a["done"]), None)
    return out


def done_kinds(db, cid: int, today: dt.date, due: int, mistakes: int):
    """Whether one of today's activities is done, from what the learner did today."""
    acts = db.execute("SELECT a.kind, a.chapter_id, a.at FROM actions a LEFT JOIN chapters c ON c.id=a.chapter_id "
                      "WHERE (c.course_id=? OR a.chapter_id IS NULL)", (cid,)).fetchall()
    todays = [a for a in acts if dt.datetime.fromisoformat(a["at"]).astimezone().date() == today]

    def done(a: dict) -> bool:
        k = a["kind"]
        if k == "cards":
            return due == 0
        if k == "mistakes":
            return mistakes == 0
        if k == "learn":
            return a.get("section_id") is None
        if k == "review":
            return any(x["chapter_id"] == a["chapter_id"] and x["kind"] in REVIEW_KINDS for x in todays)
        if k in ("mixed", "variants"):
            return any(x["kind"] == "mixed" for x in todays)
        if k == "mock":
            return bool(db.execute("SELECT 1 FROM copies WHERE exam_id=? AND handed_in_at IS NOT NULL", (a["exam_id"],)).fetchone())
        return any(x["kind"] == "cheatsheet" for x in todays)
    return done


def mixed_items(ctx: Ctx, cid: int, chapter_id: int | None, types: list[str], n: int) -> list[dict]:
    """Practice across topics, interleaved: exercises and worked examples from read Sections, and past Questions.
    With types, only past Questions of those Question Types (a mistake's variants); with a Chapter, only that Chapter."""
    db = ctx.db
    pools: dict = {}
    for q in past_questions(db, cid):
        tname = db.execute("SELECT name FROM question_types WHERE id=?", (q["question_type_id"],)).fetchone() if q["question_type_id"] else None
        if (types and (not tname or tname["name"] not in types)) or (chapter_id and q["chapter_id"] != chapter_id):
            continue
        pools.setdefault(q["chapter_id"], []).append({
            "kind": "question", "question_id": q["id"], "chapter_id": q["chapter_id"], "title": f"{q['exam']} ({q['points']:g} pts)",
            "statement": q["statement"], "answer": q["model_answer"], "scheme": json.loads(q["scheme"] or "null"),
            "type": tname["name"] if tname else None})
    if not types:
        for row in db.execute("SELECT b.*, c.id chid FROM blocks b JOIN sections s ON s.id=b.section_id JOIN chapters c ON c.id=s.chapter_id "
                              "JOIN reads r ON r.section_id=s.id WHERE c.course_id=? AND c.status='published' AND b.status='ok' "
                              "AND b.component IN ('exercise', 'worked_example') AND (? IS NULL OR c.id=?)", (cid, chapter_id, chapter_id)):
            d = json.loads(row["data"])
            ex = row["component"] == "exercise"
            pools.setdefault(row["chid"], []).append({
                "kind": "exercise", "block_id": row["id"], "chapter_id": row["chid"], "title": d["title"],
                "statement": d["statement"] if ex else d["problem"],
                "answer": d["correction"] if ex else "\n\n".join(d["steps"]) + f"\n\n**{d['answer']}**", "scheme": None, "type": None})
    rng = random.Random(learner.today().isoformat())  # the same set all day, a new one tomorrow
    for p in pools.values():
        rng.shuffle(p)
    out, queues = [], list(pools.values())
    while queues and len(out) < n:  # round-robin over Chapters: interleaving is the point
        for q in list(queues):
            if q:
                out.append(q.pop())
            if not q:
                queues.remove(q)
            if len(out) >= n:
                break
    return out


def unlock_likely_cards(ctx: Ctx, cid: int, chapter_id: int) -> None:
    """In Cram, a published Chapter's high-likelihood items become Cards at once, before they are read."""
    db = ctx.db
    if db.execute("SELECT goal FROM courses WHERE id=?", (cid,)).fetchone()["goal"] != "cram":
        return
    lk = Likelihood(db, cid)
    for row in db.execute("SELECT b.* FROM blocks b JOIN sections s ON s.id=b.section_id WHERE s.chapter_id=? AND b.status='ok'",
                          (chapter_id,)).fetchall():
        if row["component"] in learner.CARD_COMPONENTS and lk.of(row["component"], json.loads(row["exam_types"]), chapter_id) == "high":
            for part, front, back in learner.card_faces(block_json(row)):
                learner.add_card(ctx, cid, front, back, block_id=row["id"], part=part)


def router(ctx: Ctx) -> APIRouter:
    db = ctx.db
    r = APIRouter()

    def course_or_404(cid: int):
        row = db.execute("SELECT * FROM courses WHERE id=?", (cid,)).fetchone()
        if row is None:
            raise HTTPException(404, "no such Course")
        return row

    @r.get("/api/courses/{cid}/cram")
    def get_cram(cid: int):
        course = course_or_404(cid)
        return {"goal": course["goal"], "exam_date": course["exam_date"], "hours_per_day": course["hours_per_day"],
                "plan": course_plan(ctx, cid), "question_types": question_types(db, cid), "technique": technique(ctx, cid),
                "unclassified": db.execute("SELECT COUNT(*) FROM questions q JOIN exams e ON e.id=q.exam_id WHERE e.course_id=? "
                                           "AND e.kind='past_paper' AND e.in_scope=1 AND q.question_type_id IS NULL", (cid,)).fetchone()[0]}

    @r.put("/api/courses/{cid}/cram/settings")
    def cram_settings(cid: int, body: CramSettings):
        course_or_404(cid)
        db.execute("UPDATE courses SET hours_per_day=? WHERE id=?", (body.hours_per_day, cid))
        return {"hours_per_day": body.hours_per_day}

    @r.post("/api/courses/{cid}/cram/prepare", status_code=202)
    def prepare(cid: int, tasks: BackgroundTasks):
        """Sorts the past papers into Question Types for a Course generated before they existed (GPU work)."""
        course_or_404(cid)

        def run():
            try:
                classify_questions(ctx, cid, force=True)
            except StepFailed:
                pass  # traced; the Cram page still works without types
        tasks.add_task(run)
        return {"started": True}

    @r.get("/api/courses/{cid}/cheatsheet")
    def get_cheat_sheet(cid: int, chapter: int | None = None):
        course_or_404(cid)
        return cheat_sheet(ctx, cid, chapter)

    @r.post("/api/courses/{cid}/cheatsheet/done")
    def cheat_sheet_done(cid: int):
        course_or_404(cid)
        learner.record(ctx, "cheatsheet")
        return {"ok": True}

    @r.get("/api/courses/{cid}/cram/mixed")
    def get_mixed(cid: int, chapter: int | None = None, types: str = "", n: int = 8):
        course_or_404(cid)
        return mixed_items(ctx, cid, chapter, [t for t in types.split("|") if t], max(1, min(n, 30)))

    @r.post("/api/courses/{cid}/cram/mixed/mark")
    def mark_mixed(cid: int, body: MixedMark):
        """A self-marked mixed-practice item; a miss comes back as a due Card."""
        course_or_404(cid)
        learner.record(ctx, "mixed", body.chapter_id, body.mark == "got")
        if body.mark != "got":
            if body.block_id:
                row = db.execute("SELECT * FROM blocks WHERE id=?", (body.block_id,)).fetchone()
                if row:
                    for part, front, back in learner.card_faces(block_json(row)):
                        learner.add_card(ctx, cid, front, back, block_id=row["id"], part=part)
                    db.execute("UPDATE cards SET due=? WHERE block_id=?", (learner.now().isoformat(), body.block_id))
            if body.question_id:
                q = db.execute("SELECT * FROM questions WHERE id=?", (body.question_id,)).fetchone()
                if q:
                    learner.add_card(ctx, cid, q["statement"], q["model_answer"], question_id=q["id"])
                    db.execute("UPDATE cards SET due=? WHERE question_id=?", (learner.now().isoformat(), q["id"]))
        return {"ok": True}

    return r
