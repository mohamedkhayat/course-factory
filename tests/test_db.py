from concurrent.futures import ThreadPoolExecutor

from course_factory import db as dbm


def test_the_connection_survives_concurrent_requests(tmp_path):
    """FastAPI runs sync routes on a thread pool, so many threads use the database at once."""
    db = dbm.connect(tmp_path / "t.db")
    db.execute("INSERT INTO courses (name, folder) VALUES ('a', '/a')")

    def work(i):
        for _ in range(300):
            assert db.execute("SELECT * FROM courses WHERE id=?", (1,)).fetchone()["name"] == "a"
        return db.execute("INSERT INTO courses (name, folder) VALUES (?, '/b')", (f"c{i}",)).lastrowid

    with ThreadPoolExecutor(16) as pool:
        ids = list(pool.map(work, range(16)))
    assert len(set(ids)) == 16
    assert db.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 17
