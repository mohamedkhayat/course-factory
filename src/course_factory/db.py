import json
import sqlite3
import threading
from pathlib import Path
from typing import cast

import sqlite_vec

SCHEMA = """
CREATE TABLE IF NOT EXISTS courses (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, folder TEXT NOT NULL,
  goal TEXT, exam_date TEXT, run_error TEXT
);
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES courses(id),
  name TEXT NOT NULL, path TEXT NOT NULL, pages INTEGER NOT NULL DEFAULT 0,
  role TEXT, paired_with INTEGER REFERENCES sources(id), excluded INTEGER NOT NULL DEFAULT 0,
  UNIQUE (course_id, name)
);
CREATE TABLE IF NOT EXISTS pages (
  source_id INTEGER NOT NULL REFERENCES sources(id), n INTEGER NOT NULL,
  image TEXT, text TEXT, readable INTEGER, PRIMARY KEY (source_id, n)
);
CREATE TABLE IF NOT EXISTS traces (
  id INTEGER PRIMARY KEY, course_id INTEGER, step TEXT NOT NULL, harness_version TEXT NOT NULL,
  inputs TEXT NOT NULL, output TEXT, error TEXT, owner_action TEXT, duration_ms INTEGER, checks TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class PerThread(threading.local):
    """One sqlite3 connection per thread: a shared connection breaks under FastAPI's thread pool.

    Every statement autocommits, so connections never hold a transaction across calls."""

    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path, isolation_level=None, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.enable_load_extension(True)  # sqlite-vec, for search; loaded per connection
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)

    def __getattr__(self, name):
        return getattr(self.conn, name)


def connect(path: Path) -> sqlite3.Connection:
    db = cast(sqlite3.Connection, PerThread(path))
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript(SCHEMA)
    db.executescript(OUTLINE_SCHEMA)
    for table, column in [("questions", "chapter_id INTEGER"), ("traces", "duration_ms INTEGER"),
                          ("traces", "checks TEXT"), ("traces", "model TEXT"),
                          ("courses", "subject TEXT NOT NULL DEFAULT 'mixed'"),
                          ("sections", "generation_status TEXT NOT NULL DEFAULT 'planned'"),
                          ("questions", "question_type_id INTEGER"), ("chapters", "profile TEXT"),
                          ("blocks", "exam_types TEXT NOT NULL DEFAULT '[]'"), ("blocks", "previous TEXT"),
                          ("blocks", "review_queue INTEGER NOT NULL DEFAULT 0"),
                          ("courses", "hours_per_day REAL NOT NULL DEFAULT 2"), ("courses", "auto_resolve INTEGER NOT NULL DEFAULT 0"), ("sources", "sha256 TEXT"),
                          ("exams", "cohort TEXT"), ("exams", "in_scope INTEGER NOT NULL DEFAULT 1"),
                          ("sections", "teaches TEXT NOT NULL DEFAULT '[]'"), ("blocks", "tests TEXT NOT NULL DEFAULT '[]'"),
                          ("chapters", "plan TEXT"), ("courses", "language TEXT NOT NULL DEFAULT 'mixed'")]:
        try:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
        except sqlite3.OperationalError:
            pass  # already there
    _backfill_completed_sections(db)
    return db


def _backfill_completed_sections(db: sqlite3.Connection) -> None:
    """Recognize pre-migration Sections whose final checked Blocks were already committed."""
    section_ids: dict[tuple[int, str, str], list[int]] = {}
    for row in db.execute("SELECT ch.course_id, ch.title chapter, s.title section, s.id "
                          "FROM sections s JOIN chapters ch ON ch.id=s.chapter_id"):
        section_ids.setdefault((row["course_id"], row["chapter"], row["section"]), []).append(row["id"])
    latest: dict[tuple[int, str, str], list] = {}
    for row in db.execute("SELECT course_id, inputs, checks FROM traces WHERE step='write_section' "
                          "AND error IS NULL AND checks IS NOT NULL ORDER BY id"):
        try:
            inputs, checks = json.loads(row["inputs"]), json.loads(row["checks"])
            key = (row["course_id"], inputs["chapter"], inputs["section"])
            latest[key] = checks
        except (TypeError, KeyError, json.JSONDecodeError):
            continue
    for key, checks in latest.items():
        ids = section_ids.get(key, [])
        if len(ids) != 1 or not checks:
            continue  # duplicate titles or an ambiguous/empty trace are not safe to resume as complete
        count = db.execute("SELECT COUNT(*) FROM blocks WHERE section_id=?", (ids[0],)).fetchone()[0]
        if count == len(checks):
            db.execute("UPDATE sections SET generation_status='complete' WHERE id=?", (ids[0],))

OUTLINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS chapters (
  id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES courses(id), position INTEGER NOT NULL,
  title TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'normal', exam_hits INTEGER NOT NULL DEFAULT 0,
  exam_weight REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'planned'
);
CREATE TABLE IF NOT EXISTS sections (
  id INTEGER PRIMARY KEY, chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
  position INTEGER NOT NULL, title TEXT NOT NULL, pages TEXT NOT NULL DEFAULT '[]',
  generation_status TEXT NOT NULL DEFAULT 'planned'
);
CREATE TABLE IF NOT EXISTS blocks (
  id INTEGER PRIMARY KEY, section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
  position INTEGER NOT NULL, component TEXT NOT NULL, data TEXT NOT NULL, citations TEXT NOT NULL DEFAULT '[]',
  origin TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ok', flags TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS exams (
  id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES courses(id), kind TEXT NOT NULL,
  title TEXT NOT NULL, duration_min INTEGER NOT NULL, chapters TEXT NOT NULL DEFAULT '[]', source_id INTEGER REFERENCES sources(id)
);
CREATE TABLE IF NOT EXISTS questions (
  id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE, position INTEGER NOT NULL,
  statement TEXT NOT NULL, points REAL NOT NULL, model_answer TEXT NOT NULL, scheme TEXT, flags TEXT NOT NULL DEFAULT '[]',
  chapter_id INTEGER
);
CREATE TABLE IF NOT EXISTS question_types (
  id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES courses(id), name TEXT NOT NULL, trigger TEXT NOT NULL DEFAULT '',
  template TEXT NOT NULL DEFAULT '', chapter_id INTEGER, UNIQUE (course_id, name)
);
CREATE TABLE IF NOT EXISTS copies (
  id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exams(id), started_at TEXT NOT NULL, deadline TEXT NOT NULL,
  answers TEXT NOT NULL DEFAULT '{}', files TEXT NOT NULL DEFAULT '[]', handed_in_at TEXT, grade TEXT
);
"""
