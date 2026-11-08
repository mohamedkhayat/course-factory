import sqlite3
from pathlib import Path

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
  inputs TEXT NOT NULL, output TEXT, error TEXT, owner_action TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn
