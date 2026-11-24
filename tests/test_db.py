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


def test_a_block_write_on_any_thread_reaches_that_courses_subscribers_only(tmp_path):
    """Other devices refetch on this event; Runs write Blocks from pool threads, so the trigger must cross threads."""
    import asyncio

    from course_factory import events

    db = dbm.connect(tmp_path / "t.db")
    for name in ("a", "b"):
        cid = db.execute("INSERT INTO courses (name, folder) VALUES (?, '/a')", (name,)).lastrowid
        ch = db.execute("INSERT INTO chapters (course_id, position, title) VALUES (?, 0, 'C')", (cid,)).lastrowid
        db.execute("INSERT INTO sections (chapter_id, position, title) VALUES (?, 0, 'S')", (ch,))

    async def main():
        mine, other = events.subscribe(1), events.subscribe(2)
        with ThreadPoolExecutor(1) as pool:
            bid = await asyncio.get_running_loop().run_in_executor(pool, lambda: db.execute(
                "INSERT INTO blocks (section_id, position, component, data, origin) VALUES (1, 0, 'prose', '{}', 'model')").lastrowid)
        assert await asyncio.wait_for(mine.get(), 1) == {"type": "blocks", "chapter_id": 1, "section_id": 1}
        db.execute("DELETE FROM blocks WHERE id=?", (bid,))
        assert await asyncio.wait_for(mine.get(), 1) == {"type": "blocks", "chapter_id": 1, "section_id": 1}
        assert other.empty()
        events.unsubscribe(1, mine)
        events.unsubscribe(2, other)
        assert not events._subs

    asyncio.run(main())
