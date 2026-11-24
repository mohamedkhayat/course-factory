"""Hybrid search over Passages: FTS5 + sqlite-vec, reranked. A Passage never spans pages, so a hit is a Citation."""

import ctypes
from itertools import zip_longest
import sqlite3
import sys
import threading
from typing import Callable, Protocol

import sqlite_vec

PASSAGE_CHARS = 1200
CANDIDATES = 30
RERANKED = 40  # the reranker runs a 568M model on CPU per candidate: 150 of them took minutes and 12+ cores per question
RERANK_TOKENS = 512  # a Passage is ~300 tokens; the model's default 8192 lets one long pair cost the whole batch


class SearchModels(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def rerank(self, query: str, texts: list[str]) -> list[float]: ...


class LocalSearchModels:
    """bge-m3 embeddings and bge-reranker-v2-m3, loaded on first use from the HF cache. They live on the CPU; `device()` saying
    "cuda" moves them to the GPU for one call only, so they never keep VRAM a model swapped in later needs."""

    dim = 1024

    def __init__(self, device: Callable[[], str] = lambda: "cpu"):
        self._embedder = self._reranker = None
        self._device = device
        self._lock = threading.Lock()  # one inference at a time: concurrent ones each loaded the models and multiplied the memory

    def embed(self, texts):
        with self._lock:
            if self._embedder is None:
                from sentence_transformers import SentenceTransformer

                self._embedder = SentenceTransformer("BAAI/bge-m3", device="cpu")
            m = self._embedder
            return self._run(m, lambda: m.encode(texts, normalize_embeddings=True, batch_size=8).tolist())

    def rerank(self, query, texts):
        with self._lock:
            if self._reranker is None:
                from sentence_transformers import CrossEncoder

                self._reranker = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cpu", max_length=RERANK_TOKENS)
            m = self._reranker
            return self._run(m, lambda: [float(s) for s in m.predict([(query, t) for t in texts])])

    def _run(self, model, fn):
        import torch

        try:
            if self._device() == "cuda" and torch.cuda.is_available():
                try:
                    model.to("cuda", torch.float16)  # half the VRAM: next to Basalt 2.7 GB of the 32 GB are free
                    return fn()
                except torch.OutOfMemoryError:  # the chat model filled the GPU: the CPU is slower but answers
                    print("search: the GPU is full, running on the CPU", file=sys.stderr, flush=True)
                finally:
                    model.to("cpu", torch.float32)
                    torch.cuda.empty_cache()
            return fn()
        finally:
            _trim()


def _trim() -> None:
    """Hands freed memory back to the OS: glibc keeps torch's activations in its arenas, and the app grew to 38 GB in 6 hours."""
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):  # not glibc
        pass


def setup(db: sqlite3.Connection, dim: int) -> None:
    db.executescript(f"""
    CREATE TABLE IF NOT EXISTS passages (
      id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL, source_id INTEGER NOT NULL REFERENCES sources(id),
      page INTEGER NOT NULL, text TEXT NOT NULL
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(text, content='passages', content_rowid='id');
    CREATE VIRTUAL TABLE IF NOT EXISTS passages_vec USING vec0(embedding float[{dim}]);
    """)


def split_page(text: str) -> list[str]:
    paras, pieces, cur = text.split("\n\n"), [], ""
    for p in paras:
        while len(p) > PASSAGE_CHARS:
            pieces.append(p[:PASSAGE_CHARS])
            p = p[PASSAGE_CHARS:]
        if len(cur) + len(p) + 2 > PASSAGE_CHARS and cur:
            pieces.append(cur)
            cur = ""
        cur = f"{cur}\n\n{p}" if cur else p
    if cur.strip():
        pieces.append(cur)
    return [p.strip() for p in pieces if p.strip()]


def drop_passages(db: sqlite3.Connection, course_id: int) -> None:
    """Removes a Course's Passages from the table and both indexes."""
    old = [r["id"] for r in db.execute("SELECT id FROM passages WHERE course_id=?", (course_id,))]
    for pid in old:
        db.execute("INSERT INTO passages_fts(passages_fts, rowid, text) SELECT 'delete', id, text FROM passages WHERE id=?", (pid,))
        db.execute("DELETE FROM passages_vec WHERE rowid=?", (pid,))
    db.execute("DELETE FROM passages WHERE course_id=?", (course_id,))


def index_course(db: sqlite3.Connection, models: SearchModels, course_id: int) -> int:
    """(Re)builds the Passages of a Course from its readable pages of non-excluded Sources."""
    drop_passages(db, course_id)
    rows = db.execute("""SELECT s.id sid, p.n, p.text FROM pages p JOIN sources s ON s.id=p.source_id
                         WHERE s.course_id=? AND s.excluded=0 AND p.readable=1 ORDER BY s.id, p.n""", (course_id,)).fetchall()
    pieces = [(r["sid"], r["n"], t) for r in rows for t in split_page(r["text"] or "")]
    for i in range(0, len(pieces), 64):
        batch = pieces[i : i + 64]
        vectors = models.embed([t for _, _, t in batch])
        for (sid, n, text), vec in zip(batch, vectors):
            pid = db.execute("INSERT INTO passages (course_id, source_id, page, text) VALUES (?,?,?,?)", (course_id, sid, n, text)).lastrowid
            db.execute("INSERT INTO passages_fts(rowid, text) VALUES (?,?)", (pid, text))
            db.execute("INSERT INTO passages_vec(rowid, embedding) VALUES (?,?)", (pid, sqlite_vec.serialize_float32(vec)))
    return len(pieces)


def fts_query(q: str) -> str:
    words = ["".join(ch for ch in w if ch.isalnum()) for w in q.split()]
    return " OR ".join(f'"{w}"' for w in words if w)


def search(db: sqlite3.Connection, models: SearchModels, course_id: int, query: str, k: int = 8) -> list[dict]:
    fts: list[int] = []
    if fq := fts_query(query):
        fts = [r[0] for r in db.execute(
            "SELECT p.id FROM passages_fts f JOIN passages p ON p.id=f.rowid WHERE passages_fts MATCH ? AND p.course_id=? "
            "ORDER BY bm25(passages_fts) LIMIT ?", (fq, course_id, CANDIDATES))]
    vec = sqlite_vec.serialize_float32(models.embed([query])[0])
    # vec0 knn is global; over-fetch then keep this Course's rows
    near = db.execute("SELECT rowid FROM passages_vec WHERE embedding MATCH ? AND k=? ORDER BY distance", (vec, CANDIDATES * 4)).fetchall()
    ids = set(fts) | {r[0] for r in near}
    rows = {r["id"]: r for r in db.execute(
        f"SELECT p.id, p.page, p.text, s.name source FROM passages p JOIN sources s ON s.id=p.source_id "
        f"WHERE p.course_id=? AND p.id IN ({','.join('?' * len(ids))})", (course_id, *ids))} if ids else {}
    # the best of each list, taken in turn, so neither crowds out the other within the reranker's budget
    order = [i for pair in zip_longest(fts, [r[0] for r in near]) for i in pair if i in rows]
    cands = [rows[i] for i in dict.fromkeys(order)][:RERANKED]
    if not cands:
        return []
    scores = models.rerank(query, [c["text"] for c in cands])
    ranked = sorted(zip(scores, cands), key=lambda x: -x[0])[:k]
    return [{"source": c["source"], "page": c["page"], "text": c["text"], "score": s} for s, c in ranked]
