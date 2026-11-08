import json
import threading
import time

import pytest

from course_factory import pi_step
from course_factory.pi_step import Gatekeeper, QueueTimeout, StepFailed
from test_learner import published
from test_outline import worded_pages  # noqa: F401  (fixture)


def events(resp) -> list[tuple[str, dict]]:
    out = []
    for block in resp.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_tutor_streams_a_cited_answer_and_keeps_the_conversation(client, material, model, worded_pages):  # noqa: F811
    cid, sections = published(client, material, model)
    r = client.post(f"/api/courses/{cid}/tutor", json={"question": "ensemble convexe ?", "section_id": sections[0]["id"]})
    assert r.headers["content-type"].startswith("text/event-stream")
    evs = events(r)
    tokens = [d["text"] for e, d in evs if e == "token"]
    assert len(tokens) > 1 and "".join(tokens).startswith("Une fonction")
    kind, done = evs[-1]
    assert kind == "done" and done["citations"] == [{"source": "cours.pdf", "page": 1}]  # the made-up page is dropped
    prompt = next(p for s, p in model.prompts if s == "tutor")
    assert "ensemble convexe définition" in prompt and "Section: Ensembles convexes" in prompt
    r2 = client.post(f"/api/courses/{cid}/tutor", json={"question": "et le gradient ?", "conversation_id": done["conversation_id"]})
    assert events(r2)[-1][1]["conversation_id"] == done["conversation_id"]
    assert "ensemble convexe ?" in [p for s, p in model.prompts if s == "tutor"][-1]  # history goes in
    conv = client.get(f"/api/courses/{cid}/tutor/{done['conversation_id']}").json()
    assert [m["role"] for m in conv] == ["learner", "tutor", "learner", "tutor"]
    assert any(t["step"] == "tutor" and t["output"].startswith("Une fonction") for t in client.get(f"/api/courses/{cid}/traces").json())


def test_tutor_is_hidden_during_an_exam(client, material, model):
    cid, _ = published(client, material, model)
    eid = client.get(f"/api/courses/{cid}/exams").json()[0]["id"]
    copy = client.post(f"/api/courses/{cid}/exams/{eid}/copies").json()
    assert client.post(f"/api/courses/{cid}/tutor", json={"question": "?"}).status_code == 409
    client.post(f"/api/courses/{cid}/copies/{copy['id']}/hand-in")
    assert client.post(f"/api/courses/{cid}/tutor", json={"question": "?"}).status_code == 200


def test_tutor_failure_is_reported_in_the_stream(client, material, model):
    cid, _ = published(client, material, model)
    model.handlers["tutor"] = lambda prompt, files: (_ for _ in ()).throw(StepFailed("model down"))
    assert events(client.post(f"/api/courses/{cid}/tutor", json={"question": "?"}))[-1] == ("error", {"message": "model down"})


def hold(gate, live, started, release):
    with gate.lane(live):
        started.set()
        release.wait(5)


def test_generation_borrows_the_second_lane_only_while_no_live_work():
    gate = Gatekeeper(2)
    a, b, stop = threading.Event(), threading.Event(), threading.Event()
    threading.Thread(target=hold, args=(gate, False, a, stop)).start()
    assert a.wait(1)
    threading.Thread(target=hold, args=(gate, False, b, stop)).start()
    assert b.wait(1)  # idle: generation borrows the second lane
    with pytest.raises(QueueTimeout):
        with gate.lane(live=True, wait=0.1):  # both lanes busy: Live work waits (no preemption)
            pass
    stop.set()
    time.sleep(0.1)
    live, stop2 = threading.Event(), threading.Event()
    threading.Thread(target=hold, args=(gate, True, live, stop2)).start()
    assert live.wait(1)
    with gate.lane(live=False, wait=0.1):  # generation still gets its one lane
        with pytest.raises(QueueTimeout):
            with gate.lane(live=False, wait=0.1):  # but can't borrow while Live work runs
                pass
    stop2.set()


def test_waiting_live_work_goes_before_waiting_generation():
    gate = Gatekeeper(1)
    order, stop, started = [], threading.Event(), threading.Event()
    threading.Thread(target=hold, args=(gate, False, started, stop)).start()
    assert started.wait(1)

    def take(live, name):
        with gate.lane(live, wait=2):
            order.append(name)
    gen = threading.Thread(target=take, args=(False, "gen"))
    gen.start()
    time.sleep(0.05)
    live = threading.Thread(target=take, args=(True, "live"))
    live.start()
    time.sleep(0.05)
    stop.set()
    gen.join(3)
    live.join(3)
    assert order == ["live", "gen"]


def answer(text):
    def backend(step, prompt, files, workdir):
        return text
    return backend


def test_step_retries_on_queue_timeout_then_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(pi_step, "QUEUE_WAIT", 0.05)
    monkeypatch.setattr(pi_step, "GATE", Gatekeeper(0))
    with pytest.raises(StepFailed, match="no lane"):
        pi_step.call_backend(answer("x"), "s", "p", [], tmp_path, live=True)
    gate = Gatekeeper(1)
    monkeypatch.setattr(pi_step, "GATE", gate)
    stop, started = threading.Event(), threading.Event()
    threading.Thread(target=hold, args=(gate, True, started, stop)).start()
    assert started.wait(1)
    threading.Timer(0.12, stop.set).start()  # frees the lane after a couple of timeouts
    assert pi_step.call_backend(answer("ok"), "s", "p", [], tmp_path, live=False) == "ok"
