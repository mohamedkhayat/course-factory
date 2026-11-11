"""Hybrid search over Passages: FTS5 + sqlite-vec, reranked. A Passage never spans pages, so a hit is a Citation."""

import sqlite3
from typing import Protocol

import sqlite_vec

PASSAGE_CHARS = 1200
CANDIDATES = 30


class SearchModels(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def rerank(self, query: str, texts: list[str]) -> list[float]: ...


class LocalSearchModels:
    """bge-m3 embeddings and bge-reranker-v2-m3 on CPU, loaded on first use from the HF cache."""

    dim = 1024

    def __init__(self):
        self._embedder = self._reranker = None

    def embed(self, texts):
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer

            self._embedder = SentenceTransformer("BAAI/bge-m3", device="cpu")
        return self._embedder.encode(texts, normalize_embeddings=True, batch_size=8).tolist()

    def rerank(self, query, texts):
        if self._reranker is None:
            from sentence_transformers import CrossEncoder

            self._reranker = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cpu")
        return [float(s) for s in self._reranker.predict([(query, t) for t in texts])]


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
    ids: list[int] = []
    if fq := fts_query(query):
        ids += [r[0] for r in db.execute(
            "SELECT p.id FROM passages_fts f JOIN passages p ON p.id=f.rowid WHERE passages_fts MATCH ? AND p.course_id=? "
            "ORDER BY bm25(passages_fts) LIMIT ?", (fq, course_id, CANDIDATES))]
    vec = sqlite_vec.serialize_float32(models.embed([query])[0])
    # vec0 knn is global; over-fetch then keep this Course's rows
    near = db.execute("SELECT rowid FROM passages_vec WHERE embedding MATCH ? AND k=? ORDER BY distance", (vec, CANDIDATES * 4)).fetchall()
    ids += [r[0] for r in near]
    rows = {r["id"]: r for r in db.execute(
        f"SELECT p.id, p.page, p.text, s.name source FROM passages p JOIN sources s ON s.id=p.source_id "
        f"WHERE p.course_id=? AND p.id IN ({','.join('?' * len(set(ids)))})", (course_id, *set(ids)))} if ids else {}
    cands = [rows[i] for i in dict.fromkeys(ids) if i in rows]
    if not cands:
        return []
    scores = models.rerank(query, [c["text"] for c in cands])
    ranked = sorted(zip(scores, cands), key=lambda x: -x[0])[:k]
    return [{"source": c["source"], "page": c["page"], "text": c["text"], "score": s} for s, c in ranked]
