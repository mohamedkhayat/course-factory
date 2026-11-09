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
    for table, column in [("questions", "chapter_id INTEGER"), ("traces", "duration_ms INTEGER"), ("traces", "checks TEXT")]:  # columns added after a table first shipped
        try:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
        except sqlite3.OperationalError:
            pass  # already there
    return db

OUTLINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS chapters (
  id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES courses(id), position INTEGER NOT NULL,
  title TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'normal', exam_hits INTEGER NOT NULL DEFAULT 0,
  exam_weight REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'planned'
);
CREATE TABLE IF NOT EXISTS sections (
  id INTEGER PRIMARY KEY, chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
  position INTEGER NOT NULL, title TEXT NOT NULL, pages TEXT NOT NULL DEFAULT '[]'
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
CREATE TABLE IF NOT EXISTS copies (
  id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exams(id), started_at TEXT NOT NULL, deadline TEXT NOT NULL,
  answers TEXT NOT NULL DEFAULT '{}', files TEXT NOT NULL DEFAULT '[]', handed_in_at TEXT, grade TEXT
);
"""
