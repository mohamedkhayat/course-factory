import datetime as dt

import pytest

from course_factory import learner
from test_chapters import chapters, generate


@pytest.fixture
def clock(monkeypatch):
    t = {"now": dt.datetime(2026, 11, 10, 9, 0, tzinfo=dt.UTC)}
    monkeypatch.setattr(learner, "now", lambda: t["now"])
    return t


def published(client, material, model):
    cid = generate(client, material, model)
    for c in chapters(client, cid).values():
        client.post(f"/api/courses/{cid}/chapters/{c['id']}/publish")
    reader = client.get(f"/api/courses/{cid}/reader").json()
    return cid, [s for ch in reader for s in ch["sections"]]


def test_place_is_remembered_and_reading_unlocks_cards(client, material, model, clock):
    cid = generate(client, material, model)
    first = next(iter(chapters(client, cid).values()))
    sid = first["sections"][0]["id"]
    assert client.put(f"/api/courses/{cid}/place", json={"section_id": sid}).status_code == 404  # not published yet
    client.post(f"/api/courses/{cid}/chapters/{first['id']}/publish")
    assert client.get(f"/api/courses/{cid}/cards/due").json() == []
    client.put(f"/api/courses/{cid}/place", json={"section_id": sid})
    client.put(f"/api/courses/{cid}/place", json={"section_id": sid})
    assert client.get(f"/api/courses/{cid}/place").json() == {"section_id": sid, "read": [sid]}
    due = client.get(f"/api/courses/{cid}/cards/due").json()
    assert len(due) == 2  # the definition and the quiz question; no duplicates on re-reading
    assert due[0]["front"].startswith("**Definition**") and "oui" in due[1]["back"]


def test_citation_opens_the_source_page(client, material, model):
    cid, _ = published(client, material, model)
    r = client.get(f"/api/courses/{cid}/sources/cours.pdf/pages/1")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    assert client.get(f"/api/courses/{cid}/sources/cours.pdf/pages/9").status_code == 404


def test_flagging_a_block(client, material, model):
    cid, sections = published(client, material, model)
    bid = sections[0]["blocks"][0]["id"]
    assert client.post(f"/api/courses/{cid}/blocks/{bid}/flags", json={"reason": "unclear", "note": "?"}).status_code == 201
    assert client.post(f"/api/courses/{cid}/blocks/{bid}/flags", json={"reason": "boring"}).status_code == 422
    flags = client.get(f"/api/courses/{cid}/flags").json()
    assert [(f["block_id"], f["reason"], f["note"]) for f in flags] == [(bid, "unclear", "?")]


def test_quiz_feedback_mistakes_and_stats(client, material, model):
    cid, sections = published(client, material, model)
    quiz = sections[0]["blocks"][1]
    url = f"/api/courses/{cid}/blocks/{quiz['id']}"
    r = client.post(f"{url}/answers", json={"question": 0, "chosen": [1]}).json()
    assert r == {"correct": False, "correct_options": [0], "explanation": "Par définition."}
    m = client.get(f"/api/courses/{cid}/mistakes").json()
    assert [(x["block_id"], x["chosen"]) for x in m] == [(quiz["id"], [1])]
    assert client.post(f"{url}/answers", json={"question": 0, "chosen": [0]}).json()["correct"]
    assert client.get(f"/api/courses/{cid}/mistakes").json() == []
    assert client.get(f"{url}/stats").json() == [{"attempts": 2, "correct": 1, "picked": [1, 1]}]
    assert client.post(f"{url}/answers", json={"question": 3, "chosen": [0]}).status_code == 422
    theorem = sections[0]["blocks"][0]["id"]
    assert client.post(f"/api/courses/{cid}/blocks/{theorem}/answers", json={"question": 0, "chosen": [0]}).status_code == 422


def test_review_shows_next_intervals_and_reschedules(client, material, model, clock):
    cid, sections = published(client, material, model)
    client.put(f"/api/courses/{cid}/place", json={"section_id": sections[0]["id"]})
    card = client.get(f"/api/courses/{cid}/cards/due").json()[0]
    iv = card["next_interval_seconds"]
    assert list(iv) == ["À revoir", "Difficile", "Bien", "Facile"]
    assert iv["À revoir"] <= iv["Difficile"] <= iv["Bien"] <= iv["Facile"]
    r = client.post(f"/api/courses/{cid}/cards/{card['id']}/review", json={"rating": "Facile"}).json()
    assert dt.datetime.fromisoformat(r["due"]) > clock["now"]
    assert card["id"] not in [c["id"] for c in client.get(f"/api/courses/{cid}/cards/due").json()]
    assert client.post(f"/api/courses/{cid}/cards/{card['id']}/review", json={"rating": "Super"}).status_code == 422


def test_every_card_comes_due_before_the_exam(client, material, model, clock):
    cid, sections = published(client, material, model)  # Cram, exam on 2027-01-15
    client.put(f"/api/courses/{cid}/place", json={"section_id": sections[0]["id"]})
    card = client.get(f"/api/courses/{cid}/cards/due").json()[0]
    eve = dt.datetime(2027, 1, 14, 8, 0).astimezone()
    for _ in range(8):  # always "Facile": FSRS alone would push it months out
        due = dt.datetime.fromisoformat(client.post(f"/api/courses/{cid}/cards/{card['id']}/review", json={"rating": "Facile"}).json()["due"])
        assert due <= eve
        if due == eve:
            break
        clock["now"] = due
    assert due == eve


def test_sat_exam_questions_become_cards(client, material, model):
    cid, _ = published(client, material, model)
    eid = client.get(f"/api/courses/{cid}/exams").json()[0]["id"]
    copy = client.post(f"/api/courses/{cid}/exams/{eid}/copies").json()
    client.post(f"/api/courses/{cid}/copies/{copy['id']}/hand-in")
    fronts = [c["front"] for c in client.get(f"/api/courses/{cid}/cards/due").json()]
    assert fronts == ["Appliquer le gradient."]


def test_focus_session_counts_active_time_and_only_with_an_action(client, material, model, clock):
    cid, sections = published(client, material, model)
    empty = client.post("/api/focus", json={"course_id": cid}).json()
    assert (empty["work_min"], empty["break_min"]) == (25, 5)
    clock["now"] += dt.timedelta(minutes=10)
    client.post(f"/api/focus/{empty['id']}/end")
    s = client.post("/api/focus", json={"course_id": cid}).json()
    clock["now"] += dt.timedelta(minutes=5)
    assert client.post(f"/api/focus/{s['id']}/tick", json={"active_seconds": 120}).json()["active_seconds"] == 120
    assert client.post(f"/api/focus/{s['id']}/tick", json={"active_seconds": 900}).json()["active_seconds"] == 300  # capped
    client.put(f"/api/courses/{cid}/place", json={"section_id": sections[0]["id"]})
    client.post(f"/api/courses/{cid}/blocks/{sections[0]['blocks'][1]['id']}/answers", json={"question": 0, "chosen": [0]})
    done = client.post(f"/api/focus/{s['id']}/end").json()
    assert done["counts"] and done["sections_read"] == 1 and done["quiz"] == {"correct": 1, "total": 1}
    assert client.post(f"/api/focus/{s['id']}/tick", json={"active_seconds": 1}).status_code == 409
    st = client.get(f"/api/stats?course_id={cid}").json()
    assert st["today_sessions"] == 1 and st["daily_goal"] == 4 and st["streak"] == 1
    assert st["exam_countdown_days"] == (dt.date(2027, 1, 15) - learner.today()).days
    first_chapter = next(c for c in chapters(client, cid).values() if c["sections"][0]["id"] == sections[0]["id"])
    assert st["minutes_per_chapter"] == {str(first_chapter["id"]): 5}
    assert sum(st["heatmap"].values()) == 5
    assert client.put("/api/settings", json={"daily_goal": 6}).json() == {"daily_goal": 6}


def test_streak_forgives_one_missed_day_per_week():
    d = dt.date(2026, 11, 12)  # a Thursday
    day = lambda n: d - dt.timedelta(days=n)  # noqa: E731
    assert learner.streak({day(0), day(1), day(2)}, d) == 3
    assert learner.streak({day(1), day(2)}, d) == 2  # today not done yet
    assert learner.streak({day(0), day(2), day(3)}, d) == 3  # Wednesday forgiven
    assert learner.streak({day(0), day(2), day(4)}, d) == 2  # two misses in one week
    assert learner.streak({day(0), day(2), day(3), day(4), day(5), day(7), day(8)}, d) == 7  # one per week, two weeks
    assert learner.streak(set(), d) == 0
