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


def ask(client, cid, question, **body):
    return events(client.post(f"/api/courses/{cid}/tutor", json={"question": question, **body}))[-1][1]


def test_conversations_are_listed_per_section_reopened_and_deleted(client, material, model):
    cid, sections = published(client, material, model)
    a = ask(client, cid, "convexe ?", section_id=sections[0]["id"])["conversation_id"]
    b = ask(client, cid, "gradient ?", section_id=sections[1]["id"])["conversation_id"]
    listed = client.get(f"/api/courses/{cid}/tutor").json()
    assert [(c["id"], c["question"], c["section_id"]) for c in listed] == [(b, "gradient ?", sections[1]["id"]), (a, "convexe ?", sections[0]["id"])]
    assert [c["id"] for c in client.get(f"/api/courses/{cid}/tutor", params={"section_id": sections[0]["id"]}).json()] == [a]
    ask(client, cid, "et ensuite ?", conversation_id=a)
    assert "convexe ?" in [p for s, p in model.prompts if s == "tutor"][-1]
    assert client.delete(f"/api/courses/{cid}/tutor/{a}").status_code == 204
    assert client.get(f"/api/courses/{cid}/tutor/{a}").status_code == 404
    assert [c["id"] for c in client.get(f"/api/courses/{cid}/tutor").json()] == [b]


NEW = {"component": "theorem_box", "origin": "model_added", "data": {"kind": "definition", "title": "Point stationnaire",
                                                                      "statement": "Un point où le gradient s'annule."}}


def proposing(model, proposal):
    model.handlers["tutor"] = lambda prompt, files: "Voici un bloc.\n\n```proposal\n" + json.dumps(proposal) + "\n```"


def blocks_of(client, cid, sid):
    return next(s for ch in client.get(f"/api/courses/{cid}/reader").json() for s in ch["sections"] if s["id"] == sid)["blocks"]


def test_a_tutor_proposal_is_checked_then_added_or_replaced_on_accept(client, material, model):
    cid, sections = published(client, material, model)
    sid = sections[0]["id"]
    first, *rest = blocks_of(client, cid, sid)
    proposing(model, {"action": "add", "after_block_id": first["id"], "block": NEW})
    done = ask(client, cid, "ajoute un bloc", section_id=sid)
    prompt = next(p for s, p in model.prompts if s == "tutor")
    assert f"[{first['id']}] {first['component']}:" in prompt and "- theorem_box {" in prompt  # its Blocks and the Catalogue
    assert done["proposal"]["changes"][0]["block"]["component"] == "theorem_box" and done["proposal"]["flags"]["errors"] == []
    added = client.post(f"/api/courses/{cid}/tutor/messages/{done['message_id']}/accept").json()[1]
    assert [b["id"] for b in blocks_of(client, cid, sid)] == [first["id"], added["id"], *(b["id"] for b in rest)]
    assert client.post(f"/api/courses/{cid}/tutor/messages/{done['message_id']}/accept").status_code == 409  # once only
    assert any(t["owner_action"] == "accepted_proposal" for t in client.get(f"/api/courses/{cid}/traces").json())
    proposing(model, {"action": "replace", "block_id": first["id"], "block": NEW | {"data": NEW["data"] | {"title": "Remplacé"}}})
    done = ask(client, cid, "remplace le premier bloc", section_id=sid)
    client.post(f"/api/courses/{cid}/tutor/messages/{done['message_id']}/accept")
    assert blocks_of(client, cid, sid)[0]["id"] == first["id"] and blocks_of(client, cid, sid)[0]["data"]["title"] == "Remplacé"
    ids = [b["id"] for b in blocks_of(client, cid, sid)]
    proposing(model, {"action": "move", "block_id": ids[0], "after_block_id": ids[-1]})  # reorder: first goes last
    done = ask(client, cid, "mets le premier bloc à la fin", section_id=sid)
    assert done["proposal"]["changes"][0]["action"] == "move" and done["proposal"]["changes"][0]["block"]["id"] == ids[0]
    client.post(f"/api/courses/{cid}/tutor/messages/{done['message_id']}/accept")
    assert [b["id"] for b in blocks_of(client, cid, sid)] == [*ids[1:], ids[0]]
    proposing(model, {"action": "move", "block_id": ids[0]})  # no "after": back to the start
    done = ask(client, cid, "remets-le au début", section_id=sid)
    client.post(f"/api/courses/{cid}/tutor/messages/{done['message_id']}/accept")
    assert [b["id"] for b in blocks_of(client, cid, sid)] == ids
    proposing(model, {"action": "move", "block_id": ids[0], "after_block_id": 999999})
    assert ask(client, cid, "déplace", section_id=sid)["proposal"]["flags"]["errors"]
    proposing(model, {"changes": [{"block_id": ids[0]}]})  # the error names what is missing, so the tutor can fix it
    assert ask(client, cid, "déplace", section_id=sid)["proposal"]["flags"]["errors"] == ['proposal: a change has no "action" key']


def test_a_plan_of_changes_is_previewed_applied_together_and_rolled_back(client, material, model):
    cid, sections = published(client, material, model)
    sid = sections[0]["id"]
    before = blocks_of(client, cid, sid)
    a, b, *rest = [x["id"] for x in before]
    proposing(model, {"changes": [{"action": "remove", "block_id": a}, {"action": "add", "after_block_id": b, "block": NEW},
                                  {"action": "move", "block_id": b, "after_block_id": rest[-1]}]})
    done = ask(client, cid, "réorganise la section", section_id=sid)
    mid = done["message_id"]
    assert [c["action"] for c in done["proposal"]["changes"]] == ["remove", "add", "move"] and not done["proposal"]["can_undo"]
    seen = client.get(f"/api/courses/{cid}/tutor/messages/{mid}/preview").json()  # the Section as it would be, nothing written
    assert [(x["id"] if x["id"] > 0 else "new", x["mark"]) for x in seen] == [(a, "removed"), ("new", "added"), *((i, None) for i in rest), (b, "moved")]
    assert blocks_of(client, cid, sid) == before
    assert client.post(f"/api/courses/{cid}/tutor/messages/{mid}/rollback").status_code == 409  # nothing to roll back yet
    after = client.post(f"/api/courses/{cid}/tutor/messages/{mid}/accept").json()
    assert [x["id"] for x in after][1:] == [*rest, b] and after[0]["component"] == "theorem_box" and a not in [x["id"] for x in after]
    assert client.get(f"/api/courses/{cid}/tutor/{done['conversation_id']}").json()[-1]["proposal"]["can_undo"]
    client.post(f"/api/courses/{cid}/tutor/messages/{mid}/rollback")
    assert blocks_of(client, cid, sid) == before  # same ids, same order, same content
    assert client.get(f"/api/courses/{cid}/tutor/{done['conversation_id']}").json()[-1]["proposal"]["status"] == "rolled_back"
    proposing(model, {"action": "remove", "block_id": a})  # a Section edited since can't be rolled back over the edit
    one = ask(client, cid, "supprime le premier", section_id=sid)["message_id"]
    client.post(f"/api/courses/{cid}/tutor/messages/{one}/accept")
    proposing(model, {"action": "remove", "block_id": b})
    two = ask(client, cid, "et le suivant", section_id=sid)["message_id"]
    client.post(f"/api/courses/{cid}/tutor/messages/{two}/accept")
    assert client.post(f"/api/courses/{cid}/tutor/messages/{one}/rollback").status_code == 409


def test_a_question_is_taken_back_with_what_follows_unless_a_change_from_it_was_applied(client, material, model):
    cid, sections = published(client, material, model)
    sid = sections[0]["id"]
    one = ask(client, cid, "première", section_id=sid)
    conv = one["conversation_id"]
    two = ask(client, cid, "deuxième", section_id=sid, conversation_id=conv)
    assert client.delete(f"/api/courses/{cid}/tutor/messages/{two['question_id']}").status_code == 204
    assert [m["text"] for m in client.get(f"/api/courses/{cid}/tutor/{conv}").json() if m["role"] == "learner"] == ["première"]
    proposing(model, {"action": "add", "block": NEW})
    three = ask(client, cid, "ajoute", section_id=sid, conversation_id=conv)
    client.post(f"/api/courses/{cid}/tutor/messages/{three['message_id']}/accept")
    assert client.delete(f"/api/courses/{cid}/tutor/messages/{three['question_id']}").status_code == 409
    client.post(f"/api/courses/{cid}/tutor/messages/{three['message_id']}/rollback")
    assert client.delete(f"/api/courses/{cid}/tutor/messages/{one['question_id']}").status_code == 204  # the whole conversation
    assert client.get(f"/api/courses/{cid}/tutor/{conv}").status_code == 404


def test_a_proposal_failing_the_checks_cannot_be_accepted(client, material, model):
    cid, sections = published(client, material, model)
    proposing(model, {"action": "add", "block": {"component": "theorem_box", "origin": "model_added", "data": {"kind": "definition"}}})
    done = ask(client, cid, "ajoute un bloc", section_id=sections[0]["id"])
    assert done["proposal"]["flags"]["errors"]
    assert client.post(f"/api/courses/{cid}/tutor/messages/{done['message_id']}/accept").status_code == 409
    assert len(blocks_of(client, cid, sections[0]["id"])) == len(sections[0]["blocks"])


def test_explain_this_differently_asks_the_tutor_about_one_block_citing_only_the_section_pages(client, material, model):
    cid, sections = published(client, material, model)
    sid = sections[0]["id"]
    block = blocks_of(client, cid, sid)[0]
    done = ask(client, cid, "Explain this differently: simpler", section_id=sid, block_id=block["id"], style="simpler")
    prompt = [p for s, p in model.prompts if s == "tutor"][-1]
    assert "more simply" in prompt and f"The Block ({block['component']})" in prompt
    assert done["citations"] == [{"source": "cours.pdf", "page": 1}]  # the Section's page; no search passages
    other = blocks_of(client, cid, sections[1]["id"])[0]
    r = client.post(f"/api/courses/{cid}/tutor", json={"question": "?", "section_id": sid, "block_id": other["id"], "style": "deeper"})
    assert r.status_code == 404
    assert client.post(f"/api/courses/{cid}/tutor", json={"question": "?", "section_id": sid, "block_id": block["id"],
                                                          "style": "louder"}).status_code == 422
    assert client.get(f"/api/courses/{cid}/tutor/{done['conversation_id']}").json()[0]["text"] == "Explain this differently: simpler"
