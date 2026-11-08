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
    conn.executescript(OUTLINE_SCHEMA)
    return conn

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
  statement TEXT NOT NULL, points REAL NOT NULL, model_answer TEXT NOT NULL, scheme TEXT, flags TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS copies (
  id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exams(id), started_at TEXT NOT NULL, deadline TEXT NOT NULL,
  answers TEXT NOT NULL DEFAULT '{}', files TEXT NOT NULL DEFAULT '[]', handed_in_at TEXT, grade TEXT
);
"""
