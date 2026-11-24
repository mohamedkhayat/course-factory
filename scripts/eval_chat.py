"""Replay the owner's real Course chat questions through the chat, to measure how the tutor answers (#30).

    uv run python scripts/eval_chat.py --course 11 --subject theoretical
    uv run python scripts/eval_chat.py --course 11 --subject mixed      # before: every answer in Explain

Works on a copy of the database (SQLite backup, the WAL included) and of the Course's folder, so the Course is never touched;
the replay set is read from it and never written anywhere else. Each question is asked in a new conversation, on the model
the app would use (CF_MODEL...). Prints one JSON row per mode: median and maximum reply length, the share citing the anchored
page, the share ending in a question, and the share citing pages after the anchor."""
import argparse
import json
import os
import shutil
import sqlite3
import statistics
import tempfile
from collections import defaultdict
from pathlib import Path

from fastapi.testclient import TestClient

from course_factory.app import create_app
from course_factory.pi_step import PiBackend
from course_factory.tutor import step_words

DATA = Path(os.environ.get("CF_DATA", Path.home() / ".local/share/course-factory"))


def copy_data(cid: int, work: Path) -> None:
    src = sqlite3.connect(f"file:{DATA / 'course-factory.db'}?mode=ro", uri=True)
    with sqlite3.connect(work / "course-factory.db") as dst:
        src.backup(dst)
    if (DATA / "courses" / str(cid)).exists():
        shutil.copytree(DATA / "courses" / str(cid), work / "courses" / str(cid))


def events(body: str) -> list[tuple[str, dict]]:
    out = []
    for chunk in body.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines() if ": " in line)
        if "event" in lines:
            out.append((lines["event"], json.loads(lines.get("data", "null"))))
    return out


def row(mode: str, replies: list[dict]) -> dict:
    lengths = [r["words"] for r in replies]
    anchored = [r for r in replies if r["anchor"]]
    share = lambda xs, f: round(sum(map(f, xs)) / len(xs), 2) if xs else None  # noqa: E731
    return {"mode": mode, "replies": len(replies), "median words": statistics.median(lengths), "max words": max(lengths),
            "cites the anchored page": share(anchored, lambda r: r["anchor"] in r["citations"]),
            "ends in a question": share(replies, lambda r: r["text"].rstrip().endswith("?")),
            "cites pages after the anchor": share(anchored, lambda r: any(c["source"] == r["anchor"]["source"] and c["page"] > r["anchor"]["page"]
                                                                          for c in r["citations"])),
            "failed": sum(r.get("error", False) for r in replies)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--course", type=int, default=11)
    p.add_argument("--subject", choices=["theoretical", "practical", "mixed"], default="theoretical")
    p.add_argument("--limit", type=int, default=0, help="only the first N questions")
    a = p.parse_args()
    with tempfile.TemporaryDirectory(prefix="cf-eval-chat-") as w:
        work = Path(w)
        copy_data(a.course, work)
        db = sqlite3.connect(work / "course-factory.db")
        questions = [q for (q,) in db.execute("SELECT text FROM tutor_messages WHERE course_id=? AND kind='chat' AND role='learner' "
                                              "AND text NOT LIKE 'data:image%' ORDER BY id", (a.course,))]
        db.execute("UPDATE courses SET subject=? WHERE id=?", (a.subject, a.course))
        db.commit()
        db.close()
        by_mode = defaultdict(list)
        with TestClient(create_app(work, PiBackend()), base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000)) as client:  # the host check
            for i, q in enumerate(questions[:a.limit or None]):
                evs = events(client.post(f"/api/courses/{a.course}/chat", json={"question": q}).text)
                done = next((d for e, d in evs if e == "done"), None)
                if done is None:
                    by_mode["failed"].append({"words": 0, "anchor": None, "citations": [], "text": "", "error": True})
                    continue
                text = "\n\n".join(p.get("text", "") for p in done.get("parts") or [] if p.get("type") == "md")
                citations = [{"source": c["source"], "page": c["page"]} for c in done.get("citations") or []]
                by_mode[done["mode"]].append({"words": step_words(text), "anchor": done.get("anchor"), "citations": citations, "text": text})
                print(f"{i + 1}/{len(questions)} {done['mode']} {step_words(text)} words", flush=True)
        for mode, replies in sorted(by_mode.items()):
            print(json.dumps(row(mode, replies), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
