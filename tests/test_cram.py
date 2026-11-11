import datetime as dt

import pytest

from course_factory.cram import cheat_item, compile_sheet

from conftest import make_pdf
from course_factory import learner
from test_chapters import generate


@pytest.fixture
def with_exam(material):
    make_pdf(material / "examen_2024.pdf", 2)
    make_pdf(material / "examen_2024_corrige.pdf", 1)
    return material


@pytest.fixture
def clock(monkeypatch):
    t = {"now": dt.datetime(2026, 11, 10, 9, 0, tzinfo=dt.UTC)}
    monkeypatch.setattr(learner, "now", lambda: t["now"])
    return t


def cram_section(prompt, files):
    """Blocks tagged with the Chapter's Question Type, like the real model is asked to."""
    chapter = prompt.split("Chapter: ", 1)[1].split("\n", 1)[0]
    tag = [f"Type {chapter}"]
    return {"blocks": [
        {"component": "theorem_box", "origin": "model_added", "exam_types": tag,
         "data": {"kind": "definition", "title": f"Def {chapter}", "statement": "Un ensemble est convexe si le segment y reste."}},
        {"component": "exercise", "origin": "model_added", "exam_types": tag,
         "data": {"title": "Ex", "statement": "Calculer le pas optimal.", "correction": "On pose le pas."}},
        {"component": "key_formula", "origin": "model_added",
         "data": {"name": "Pas", "latex": "x_{k+1} = x_k - t \\nabla f(x_k)", "meaning": "Un pas de gradient."}},
        {"component": "quiz", "origin": "model_added", "exam_types": tag, "data": {"questions": [
            {"prompt": "Convexe ?", "options": ["oui", "non"], "correct": [0], "explanation": "Par définition."}]}}]}


def published(client, material, model, **kw):
    model.handlers["write_section"] = cram_section
    cid = generate(client, material, model, **kw)
    for c in client.get(f"/api/courses/{cid}/outline").json()["chapters"]:
        client.post(f"/api/courses/{cid}/chapters/{c['id']}/publish")
    return cid


def blocks_of(client, cid):
    return [(ch["title"], b) for ch in client.get(f"/api/courses/{cid}/reader").json() for s in ch["sections"] for b in s["blocks"]]


def test_cram_sections_are_written_for_the_question_types_and_deep_ones_are_not(client, with_exam, model):
    cid = generate(client, with_exam, model)
    types = client.get(f"/api/courses/{cid}/cram").json()["question_types"]
    assert [(t["name"], t["points"], t["likelihood"]) for t in types] == [
        ("Type Méthodes de descente", 14, "high"), ("Type Convexité", 6, "medium")]
    prompt = next(p for step, p in model.prompts if step == "write_section" and "Chapter: Convexité" in p)
    brief = prompt.split("Cram brief: ", 1)[1].split("\n", 1)[0]
    assert '"profile": "problem"' in brief and "Type Convexité" in brief and "Montrer que" in brief and "Hessienne" in brief
    assert "Type Méthodes" not in brief  # only the Chapter's own types
    assert client.delete(f"/api/courses/{cid}").status_code == 204  # its Question Types go with it

    model.prompts.clear()
    generate(client, with_exam, model, goal={"goal": "deep"})
    prompt = next(p for step, p in model.prompts if step == "write_section")
    assert "Cram brief: none" in prompt


def test_exam_likelihood_follows_the_points_and_exercises_get_the_exam_time(client, with_exam, model, clock):
    cid = published(client, with_exam, model)
    blocks = blocks_of(client, cid)
    defs = {ch: b["cram"] for ch, b in blocks if b["component"] == "theorem_box"}
    assert defs["Méthodes de descente"]["likelihood"] == "high" and defs["Convexité"]["likelihood"] == "medium"
    assert defs["Convexité"]["questions"][0]["exam"] == "Examen 2024" and defs["Convexité"]["types"] == ["Type Convexité"]
    exercise = next(b for ch, b in blocks if ch == "Méthodes de descente" and b["component"] == "exercise")
    assert exercise["cram"]["minutes"] == 84  # 120 min for 20 points, and its type's Question is worth 14
    formula = next(b for ch, b in blocks if ch == "Méthodes de descente" and b["component"] == "key_formula")
    assert formula["cram"]["likelihood"] == "medium" and formula["cram"]["types"] == []  # untagged: from its Chapter, at most medium
    # high-likelihood items are already Cards in Cram, before any reading
    fronts = [c["front"] for c in client.get(f"/api/courses/{cid}/cards/due").json()]
    assert any("Def Méthodes de descente" in f for f in fronts) and not any("Def Convexité" in f for f in fronts)


def test_cheat_sheet_lists_checked_items_most_likely_first_within_budget(client, with_exam, model):
    cid = published(client, with_exam, model)
    sheet = client.get(f"/api/courses/{cid}/cheatsheet").json()
    items = sheet["items"]
    # grouped by Chapter, then kind; the fake's two Chapters repeat each other's definition and formula, so each is kept once
    assert [(i["chapter"], i["kind"]) for i in items] == [("Méthodes de descente", "definition"), ("Méthodes de descente", "formula")]
    assert items[0]["title"] == "Def Méthodes de descente" and items[0]["likelihood"] == "high"
    assert all(i["section_id"] and i["block_id"] for i in items)
    assert sum(len(i["title"]) + len(i["body"]) for i in items) <= sheet["budget_chars"]
    one = client.get(f"/api/courses/{cid}/cheatsheet", params={"chapter": items[1]["chapter_id"]}).json()["items"]
    assert {i["chapter"] for i in one} == {"Méthodes de descente"}


def test_cheat_sheet_leaves_out_flagged_blocks(client, with_exam, model):
    def section(prompt, files):
        out = cram_section(prompt, files)
        out["blocks"][2]["data"]["latex"] = "\\frac{1}{"  # broken: flagged
        return out
    model.handlers["write_section"] = section
    cid = generate(client, with_exam, model)
    for c in client.get(f"/api/courses/{cid}/outline").json()["chapters"]:
        client.post(f"/api/courses/{cid}/chapters/{c['id']}/publish")
    assert "formula" not in {i["kind"] for i in client.get(f"/api/courses/{cid}/cheatsheet").json()["items"]}


def acts(day):
    return [a["kind"] for a in day["activities"]]


def test_cram_plan_spaces_passes_ends_with_mocks_and_a_light_eve(client, with_exam, model, clock):
    cid = published(client, with_exam, model)
    client.patch(f"/api/courses/{cid}", json={"goal": "cram", "exam_date": "2026-11-20"})
    plan = client.get(f"/api/courses/{cid}/cram").json()["plan"]
    days = plan["days"]
    assert len(days) == 10 and days[0]["date"] == "2026-11-10" and days[-1]["eve"]
    assert set(acts(days[-1])) <= {"cheatsheet", "mistakes", "cards"}  # no new material on the eve
    mocks = [i for i, d in enumerate(days) if "mock" in acts(d)]
    assert len(mocks) == 2 and all(i >= len(days) - 7 for i in mocks)
    for title in ("Convexité", "Méthodes de descente"):
        passes = [i for i, d in enumerate(days) for a in d["activities"] if a.get("title", "").endswith(title)]
        assert len(passes) >= 3 and passes == sorted(passes) and len(set(passes)) >= 3  # learn, then two later retrievals
    assert plan["skip"] == [] and plan["next"]["kind"] in ("cards", "learn")
    learn = next(a for a in days[0]["activities"] if a["kind"] == "learn")
    assert learn["title"] == "Learn: Méthodes de descente" and learn["section_id"]  # most points first

    client.patch(f"/api/courses/{cid}", json={"goal": "cram", "exam_date": "2026-11-13"})
    days = client.get(f"/api/courses/{cid}/cram").json()["plan"]["days"]
    assert len(days) == 3 and sum("mock" in acts(d) for d in days) == 0  # a Mock exam would cost a topic: learning first
    client.put(f"/api/courses/{cid}/cram/settings", json={"hours_per_day": 4})
    days = client.get(f"/api/courses/{cid}/cram").json()["plan"]["days"]
    assert sum("mock" in acts(d) for d in days) == 1  # under four days: one Mock exam


def test_too_little_time_skips_the_lowest_yield_topics_and_says_what_it_costs(client, with_exam, model, clock):
    cid = published(client, with_exam, model)
    client.patch(f"/api/courses/{cid}", json={"goal": "cram", "exam_date": "2026-11-12"})
    assert client.put(f"/api/courses/{cid}/cram/settings", json={"hours_per_day": 1.5}).status_code == 200
    plan = client.get(f"/api/courses/{cid}/cram").json()["plan"]
    assert [s["title"] for s in plan["skip"]] == ["Convexité"] and plan["skipped_points"] == 6 and plan["kept_points"] == 14


def test_a_mistake_schedules_variants_of_its_question_type(client, with_exam, model, clock):
    cid = published(client, with_exam, model)
    quiz = next(b for ch, b in blocks_of(client, cid) if ch == "Convexité" and b["component"] == "quiz")
    client.post(f"/api/courses/{cid}/blocks/{quiz['id']}/answers", json={"question": 0, "chosen": [1]})
    today = client.get(f"/api/courses/{cid}/cram").json()["plan"]["days"][0]
    variants = next(a for a in today["activities"] if a["kind"] == "variants")
    assert "mistakes" in acts(today) and variants["types"] == ["Type Convexité"]


def test_mixed_practice_interleaves_chapters_and_a_miss_becomes_a_card(client, with_exam, model, clock):
    cid = published(client, with_exam, model)
    items = client.get(f"/api/courses/{cid}/cram/mixed").json()
    assert {i["kind"] for i in items} == {"question"}  # nothing read yet: past Questions only
    assert len({i["chapter_id"] for i in items[:2]}) == 2  # round-robin over Chapters
    q = items[0]
    assert client.post(f"/api/courses/{cid}/cram/mixed/mark",
                       json={"mark": "missed", "chapter_id": q["chapter_id"], "question_id": q["question_id"]}).status_code == 200
    assert any(c["front"] == q["statement"] for c in client.get(f"/api/courses/{cid}/cards/due").json())
    variants = client.get(f"/api/courses/{cid}/cram/mixed", params={"types": "Type Convexité"}).json()
    assert [v["type"] for v in variants] == ["Type Convexité"]


def terminal(*entries, title="CRUD"):
    return {"component": "terminal", "data": {"title": title, "entries": [{"command": c, "output": "", "note": n} for c, n in entries]}}


def candidate(block, rank, order, chapter=1):
    kind, title, body, rows = cheat_item(block)
    return {"kind": kind, "title": title, "body": body, "rows": rows, "chapter_id": chapter, "_rank": (rank, order), "_order": (chapter, order)}


def test_commands_become_rows_and_repeats_merge_within_the_budget():
    put = "curl -X PUT 'localhost:9200/ventes?pretty' -H 'Content-Type: application/json' -d '{\"settings\":{\"number_of_shards\":3}}'"
    first = candidate(terminal((put, "Creates the index with **3 primary shards**."), ("GET _cat/indices?v", "")), 0, 2)
    again = candidate(terminal((put, "same"), ("GET _cat/indices?v", ""), title="REST API"), 1, 1)  # all its commands are in `first`
    more = candidate(terminal(("GET _cat/indices?v", ""), ("DELETE /ventes", "Drops it.")), 2, 3)
    defn = {"component": "theorem_box", "data": {"kind": "definition", "title": "Shard", "statement": "A shard is one Lucene index holding part of the documents."}}
    same = defn | {"data": defn["data"] | {"statement": "A shard is one Lucene index, holding a part of the documents."}}
    sheet = compile_sheet([first, again, more, candidate(defn, 0, 0), candidate(same, 1, 4)], budget=10_000)
    assert [(i["kind"], i["title"]) for i in sheet["items"]] == [("definition", "Shard"), ("commands", "CRUD"), ("commands", "CRUD")]
    assert sheet["items"][1]["rows"][0] == {"command": put, "note": "Creates the index with **3 primary shards**."}  # Markdown stays out of the code
    assert sheet["items"][2]["rows"] == [{"command": "DELETE /ventes", "note": "Drops it."}]  # its repeated command merged away
    assert sheet["left_out"] == 0
    small = compile_sheet([candidate(defn, 0, 0), first], budget=80)
    assert [i["kind"] for i in small["items"]] == ["definition"] and small["left_out"] == 1
