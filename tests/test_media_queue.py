import threading
import time

import pytest

from course_factory.media_queue import MediaQueue, Stopped


def until(cond, seconds=2.0):
    end = time.time() + seconds
    while not cond():
        assert time.time() < end, "timed out"
        time.sleep(0.01)


def test_a_job_shows_its_progress_waits_while_paused_and_stops_at_its_next_step():
    q, went, hold = MediaQueue(), [], threading.Event()

    def work():
        for i in range(5):
            q.checkpoint(i, 5, "speaking")
            went.append(i)
            if i == 1:
                hold.wait(2)
    f = q.submit(work, kind="listen", label="Listen · Normes", course=3, stoppable=True)
    until(lambda: went == [0, 1])
    job = q.view()["jobs"][0]
    assert (job["state"], job["done"], job["total"], job["step"], job["label"]) == ("running", 1, 5, "speaking", "Listen · Normes")
    q.pause(True)
    hold.set()
    time.sleep(0.1)
    assert went == [0, 1]  # paused at its next step
    assert q.stop(job["id"])
    with pytest.raises(Stopped):
        f.result(2)
    assert went == [0, 1] and q.view() == {"paused": True, "jobs": []}


def test_paused_an_install_still_runs_and_background_work_waits_behind_what_the_owner_asked_for():
    q, order = MediaQueue(), []
    q.pause(True)
    ahead = q.submit(lambda: order.append("ahead"), background=True, stoppable=True)
    asked = q.submit(lambda: order.append("asked"), stoppable=True)
    assert q.submit(lambda: "installed", kind="install").result(2) == "installed"
    assert not asked.done()
    queued = q.submit(lambda: (q.checkpoint(0, 3), order.append("dropped")), label="drop", stoppable=True)
    assert [j["label"] for j in q.view()["jobs"]] == ["", "drop", ""]  # what the owner asked for, then the background
    assert q.stop(q.view()["jobs"][1]["id"])  # a queued job is dropped: whoever waits on it hears
    with pytest.raises(Stopped):
        queued.result(2)
    q.pause(False)
    ahead.result(2)
    assert order == ["asked", "ahead"]
    assert not q.stop(999)
