from conftest import FakeSearch
from course_factory import db as dbm, search


def test_rerank_sees_at_most_the_budget_of_this_courses_passages(tmp_path):
    db = dbm.connect(tmp_path / "x.db")
    seen = []

    class Counting(FakeSearch):
        def rerank(self, query, texts):
            seen.append(len(texts))
            return super().rerank(query, texts)
    models = Counting()
    search.setup(db, models.dim)
    db.execute("PRAGMA foreign_keys = OFF")
    db.execute("INSERT INTO sources (id, course_id, name, path) VALUES (1, 1, 'cours.pdf', 'cours.pdf')")
    for i in range(1, 201):
        text = f"gradient descent step {i}"
        db.execute("INSERT INTO passages (id, course_id, source_id, page, text) VALUES (?,1,1,1,?)", (i, text))
        db.execute("INSERT INTO passages_fts(rowid, text) VALUES (?,?)", (i, text))
        db.execute("INSERT INTO passages_vec(rowid, embedding) VALUES (?,?)", (i, search.sqlite_vec.serialize_float32(models.embed([text])[0])))
    hits = search.search(db, models, 1, "gradient descent", 8)
    assert seen == [search.RERANKED] and len(hits) == 8  # 150 candidates took minutes on CPU per chat question


def test_search_models_use_the_gpu_for_one_call_and_fall_back_to_the_cpu_when_it_is_full(monkeypatch):
    import torch
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)

    class Model:
        def __init__(self):
            self.moves, self.on = [], "cpu"

        def to(self, d, dtype=None):
            self.moves.append(d)
            self.on = d

    m, device = Model(), ["cuda"]
    models = search.LocalSearchModels(lambda: device[0])
    assert models._run(m, lambda: m.on) == "cuda" and m.on == "cpu"  # back on the CPU after the call: VRAM is freed

    def full():
        if m.on == "cuda":
            raise torch.OutOfMemoryError()
        return "cpu answer"
    assert models._run(m, full) == "cpu answer" and m.on == "cpu"

    device[0], m.moves = "cpu", []
    assert models._run(m, lambda: m.on) == "cpu" and m.moves == []  # not Basalt: never touches the GPU
