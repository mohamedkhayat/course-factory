import datetime as dt
import json

from test_chapters import generate
from test_chat import EXPLAIN, QUIZ, chat_with, concept_of, done_of, say  # noqa: F401
from test_learner import clock, published  # noqa: F401  (fixture)
from test_outline import worded_pages  # noqa: F401  (fixture)
from test_tutor import events

PAPER = {"kind": "preference", "text": "No exercises to write on paper."}


def remember(obj) -> str:
    return "```remember\n" + json.dumps(obj) + "\n```"


def tutor_says(model, obj, text="Bien sûr, c'est noté."):
    model.handlers["tutor"] = lambda prompt, files: f"{text}\n\n{remember(obj)}\n"


def facts(client, **q):
    return client.get("/api/memory", params=q).json()


def prompt_of(model, step):
    return [p for s, p in model.prompts if s == step][-1]


def tutor_call(client, cid, sid, question="Explique", **body):
    return events(client.post(f"/api/courses/{cid}/tutor", json={"question": question, "section_id": sid, **body}))


def test_a_remember_fence_is_saved_hidden_announced_and_undone(client, material, model):
    cid, sections = published(client, material, model)
    tutor_says(model, PAPER)
    evs = tutor_call(client, cid, sections[0]["id"])
    assert "".join(d["text"] for e, d in evs if e == "token").strip() == "Bien sûr, c'est noté."
    fact = next(d for e, d in evs if e == "remembered")
    assert fact["text"] == PAPER["text"] and [e for e, _ in evs][-2:] == ["remembered", "done"]
    saved = facts(client)
    assert [(f["kind"], f["course_id"], f["origin"]["by"]) for f in saved] == [("preference", None, "said")]
    conv = client.get(f"/api/courses/{cid}/tutor/{evs[-1][1]['conversation_id']}").json()
    assert "remember" not in conv[-1]["text"] and conv[-1]["remembered"] == fact  # reopened: line and Undo survive
    assert client.delete(f"/api/memory/{fact['id']}").status_code == 204
    assert facts(client) == []
    assert client.get(f"/api/courses/{cid}/tutor/{evs[-1][1]['conversation_id']}").json()[-1]["remembered"] is None


def test_an_unclosed_fence_is_still_kept_out_of_the_text(client, material, model):
    cid, sections = published(client, material, model)
    model.handlers["tutor"] = lambda prompt, files: "Oui.\n\n``" + "`remember\n" + json.dumps(PAPER)  # never closed
    evs = tutor_call(client, cid, sections[0]["id"])
    assert "".join(d["text"] for e, d in evs if e == "token").strip() == "Oui."
    assert len(facts(client)) == 1


def test_the_same_preference_is_saved_once_and_a_contradiction_replaces_the_old_one(client, material, model):
    cid, sections = published(client, material, model)
    sid = sections[0]["id"]
    tutor_says(model, PAPER)
    tutor_call(client, cid, sid)
    again = tutor_call(client, cid, sid)
    assert not [e for e, _ in again if e == "remembered"] and len(facts(client)) == 1
    old = facts(client)[0]["id"]
    tutor_call(client, cid, sid)
    assert f"[{old}] No exercises to write on paper." in prompt_of(model, "tutor")  # the id is what a replacement names
    tutor_says(model, {"kind": "preference", "text": "Paper exercises are fine now.", "replaces": old})
    tutor_call(client, cid, sid)
    assert [f["text"] for f in facts(client)] == ["Paper exercises are fine now."]


def test_invalid_fences_are_dropped_but_still_hidden(client, material, model):
    cid, sections = published(client, material, model)
    sid = sections[0]["id"]
    for bad in ({"kind": "preference", "text": "x" * 201}, {"kind": "preference", "text": "two\nlines"}, {"kind": "preference", "text": ""},
                {"kind": "misunderstanding", "concept": "unknown concept", "text": "Confuses things."}, {"kind": "mood", "text": "Tired."}):
        tutor_says(model, bad)
        evs = tutor_call(client, cid, sid)
        assert not [e for e, _ in evs if e == "remembered"] and "remember" not in "".join(d["text"] for e, d in evs if e == "token")
    model.handlers["tutor"] = lambda prompt, files: "Ok.\n```remember\nnot json\n```"
    assert not [e for e, _ in tutor_call(client, cid, sid) if e == "remembered"]
    assert facts(client) == []


def test_the_course_chat_remembers_a_preference_and_a_challenge_misunderstanding(client, material, model):
    cid, _ = published(client, material, model)
    model.handlers["chat"] = lambda prompt, files: f"Non, pas tout à fait.\n\n{remember({'kind': 'misunderstanding', 'concept': 'gradient', 'text': 'Thinks the gradient points downhill.'})}"
    evs = say(client, cid, "Le gradient descend ?")
    assert "remember" not in "".join(d["text"] for e, d in evs if e == "token")
    done = done_of(evs)
    assert "remember" not in done["parts"][0]["text"]
    pattern = facts(client, course_id=cid)[0]
    assert (pattern["kind"], pattern["course_id"], pattern["origin"]["by"], pattern["origin"]["concept"]) == ("pattern", cid, "challenge", "gradient")
    conv = client.get(f"/api/courses/{cid}/chat/{done['conversation_id']}").json()["messages"]
    assert conv[-1]["remembered"]["id"] == pattern["id"]
    model.handlers["chat"] = lambda prompt, files: f"Ok.\n\n{remember(PAPER)}"
    assert [e for e, _ in say(client, cid, "pas de papier") if e == "remembered"] == ["remembered"]
    assert [f["kind"] for f in facts(client)] == ["preference", "pattern"]  # preferences first


def quiz_of(sections):
    return next(b for s in sections for b in s["blocks"] if b["component"] == "quiz")


def test_three_misses_make_a_pattern_and_three_rights_remove_it(client, material, model, clock):  # noqa: F811
    cid, sections = published(client, material, model)
    quiz = quiz_of(sections)
    url = f"/api/courses/{cid}/blocks/{quiz['id']}/answers"

    def answer(chosen):
        clock["now"] += dt.timedelta(minutes=1)
        client.post(url, json={"question": 0, "chosen": chosen})
    for _ in range(2):
        answer([1])
    assert facts(client, course_id=cid) == []
    answer([1])
    (found,) = facts(client, course_id=cid)
    assert found["kind"] == "pattern" and "3 misses" in found["text"] and "Nov 10" in found["text"] and found["origin"]["by"] == "results"
    answer([0])
    answer([0])
    assert len(facts(client, course_id=cid)) == 1
    answer([0])
    assert facts(client, course_id=cid) == []


def test_chat_practice_and_gaps_count_toward_patterns(client, material, model, clock):  # noqa: F811
    cid, _ = published(client, material, model)
    chat_with(model, QUIZ)
    done = done_of(say(client, cid, "interroge-moi"))
    base = f"/api/courses/{cid}/chat/messages/{done['message_id']}/parts/1"
    for _ in range(3):
        clock["now"] += dt.timedelta(minutes=1)
        client.post(base + "/answers", json={"question": 0, "chosen": [1]})
    assert [f["origin"]["concept"] for f in facts(client, course_id=cid)] == ["gradient"]


def test_a_challenge_misunderstanding_goes_after_three_right_answers(client, material, model, clock):  # noqa: F811
    cid, _ = published(client, material, model)
    model.handlers["chat"] = lambda prompt, files: "Non.\n\n" + remember({"kind": "misunderstanding", "concept": "gradient", "text": "Mixes up direction."}) + "\n\n" \
        + "```block\n" + json.dumps(QUIZ) + "\n```"
    done = done_of(say(client, cid, "Le gradient descend ?"))
    base = f"/api/courses/{cid}/chat/messages/{done['message_id']}/parts/1"
    for n in range(3):
        assert len(facts(client, course_id=cid)) == 1
        clock["now"] += dt.timedelta(minutes=1)
        client.post(base + "/answers", json={"question": 0, "chosen": [0]})
    assert facts(client, course_id=cid) == []


def test_choosing_the_same_explain_differently_style_three_times_makes_a_pattern(client, material, model):
    cid, sections = published(client, material, model)
    sid = sections[0]["id"]
    block = sections[0]["blocks"][0]
    for style in ("example", "example", "simpler"):
        tutor_call(client, cid, sid, block_id=block["id"], style=style)
    assert facts(client, course_id=cid) == []
    tutor_call(client, cid, sid, block_id=block["id"], style="example")
    (found,) = facts(client, course_id=cid)
    assert found["origin"] == {"by": "explain_differently", "style": "example", "picks": 3} and "worked example" in found["text"]
    for _ in range(3):
        tutor_call(client, cid, sid, block_id=block["id"], style="deeper")
    assert [f["origin"]["style"] for f in facts(client, course_id=cid)] == ["deeper"]  # no longer 3 of the last 5


def test_preferences_reach_every_course_and_patterns_only_their_own(client, material, model, clock):  # noqa: F811
    cid, sections = published(client, material, model)
    other, other_sections = published(client, material, model)
    assert client.post("/api/memory", json={"text": "Always start with an example."}).status_code == 201
    quiz = quiz_of(sections)
    for _ in range(3):
        clock["now"] += dt.timedelta(minutes=1)
        client.post(f"/api/courses/{cid}/blocks/{quiz['id']}/answers", json={"question": 0, "chosen": [1]})
    for c, s in ((cid, sections), (other, other_sections)):
        tutor_call(client, c, s[0]["id"])
        say(client, c, "salut")
        for step in ("tutor", "chat"):
            p = prompt_of(model, step)
            assert "Always start with an example." in p
            assert ("Keeps missing" in p) == (c == cid)


def test_sections_written_later_read_the_preferences(client, material, model):
    client.post("/api/memory", json={"text": "No exercises to write on paper."})
    cid = generate(client, material, model)
    assert "No exercises to write on paper." in prompt_of(model, "write_section")
    assert "Always start" not in prompt_of(model, "write_section")


def test_the_prompt_gets_at_most_the_cap_newest_facts(client, material, model):
    cid, sections = published(client, material, model)
    for n in range(25):
        client.post("/api/memory", json={"text": f"Preference number {n}."})
    tutor_call(client, cid, sections[0]["id"])
    p = prompt_of(model, "tutor")
    assert p.count("Preference number") == 20 and "Preference number 24." in p and "Preference number 4." not in p


def test_settings_lists_adds_edits_and_deletes_facts(client, material, model):
    cid, _ = published(client, material, model)
    made = client.post("/api/memory", json={"text": "Answer in French."}).json()
    assert made["kind"] == "preference" and made["course_id"] is None
    assert client.post("/api/memory", json={"text": "answer   in french"}).status_code == 409  # same fact
    assert client.post("/api/memory", json={"text": "a\nb"}).status_code == 422
    edited = client.put(f"/api/memory/{made['id']}", json={"text": "Answer in English."}).json()
    assert edited["text"] == "Answer in English." and edited["origin"] == made["origin"] and edited["created_at"] == made["created_at"]
    assert client.put("/api/memory/999", json={"text": "x"}).status_code == 404
    assert client.put(f"/api/memory/{made['id']}", json={"text": "y" * 201}).status_code == 422
    assert [f["text"] for f in facts(client)] == ["Answer in English."]
    assert client.delete(f"/api/memory/{made['id']}").status_code == 204 and client.delete(f"/api/memory/{made['id']}").status_code == 404


def test_deleting_a_course_deletes_its_patterns_and_keeps_preferences(client, material, model, clock):  # noqa: F811
    cid, sections = published(client, material, model)
    client.post("/api/memory", json={"text": "Answer in French."})
    for _ in range(3):
        clock["now"] += dt.timedelta(minutes=1)
        client.post(f"/api/courses/{cid}/blocks/{quiz_of(sections)['id']}/answers", json={"question": 0, "chosen": [1]})
    assert len(facts(client)) == 2 and len(facts(client, course_id=cid)) == 2
    assert client.delete(f"/api/courses/{cid}").status_code in (200, 204)
    assert [(f["text"], f["course_id"]) for f in facts(client)] == [("Answer in French.", None)]
