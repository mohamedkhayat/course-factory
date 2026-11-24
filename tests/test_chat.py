import json

from test_learner import clock, published  # noqa: F401  (fixture)
from test_outline import worded_pages  # noqa: F401  (fixture)
from test_tutor import events

BLOCK = {"component": "theorem_box", "origin": "from_source", "citations": [{"source": "cours.pdf", "page": 2}], "tests": ["gradient"],
         "data": {"kind": "definition", "title": "Gradient", "statement": "Le gradient pointe vers la plus forte croissance."}}


def fence(block) -> str:
    return "```block\n" + json.dumps(block) + "\n```"


def say(client, cid, question, **body):
    return events(client.post(f"/api/courses/{cid}/chat", json={"question": question, **body}))


def done_of(evs):
    assert evs[-1][0] == "done", evs[-1]
    return evs[-1][1]


def blocks_of(client, cid, sid):
    return [b for ch in client.get(f"/api/courses/{cid}/reader").json() for s in ch["sections"] if s["id"] == sid for b in s["blocks"]]


def test_chat_streams_prose_and_draws_a_checked_block_without_leaking_the_fence(client, material, model):
    cid, _ = published(client, material, model)
    evs = say(client, cid, "c'est quoi le gradient ?")
    tokens = "".join(d["text"] for e, d in evs if e == "token")
    assert "```" not in tokens and "component" not in tokens and "Voici l'idée" in tokens and "Et la suite." in tokens
    statuses = [d["status"] for e, d in evs if e == "block"]
    assert statuses[0] == "writing" and "checking" in statuses and statuses[-1] == "ok"
    assert any(e == "activity" and d["kind"] == "write" for e, d in evs) and any(e == "activity" and d["kind"] == "check" for e, d in evs)
    done = done_of(evs)
    assert [p["type"] for p in done["parts"]] == ["md", "block", "md"]
    block = done["parts"][1]["block"]
    assert block["component"] == "theorem_box" and block["data"]["title"] == "Gradient" and block["citations"][0]["page"] == 2
    assert done["citations"] == [{"source": "cours.pdf", "page": 2}]
    assert done["activity"]


def test_a_block_that_fails_is_repaired_and_one_that_stays_broken_is_dropped(client, material, model):
    cid, _ = published(client, material, model)
    broken = BLOCK | {"data": {"kind": "definition", "title": "Gradient"}}  # no statement
    model.handlers["chat"] = lambda prompt, files: f"A.\n\n{fence(broken)}\n\nB."
    model.handlers["repair_block"] = lambda prompt, files: {"block": BLOCK}
    done = done_of(say(client, cid, "montre"))
    assert [p["type"] for p in done["parts"]] == ["md", "block", "md"] and any(a["kind"] == "fix" for a in done["activity"])
    model.handlers["repair_block"] = lambda prompt, files: {"block": broken}  # echoes: fixes nothing
    evs = say(client, cid, "montre encore")
    assert ("block", {"index": 0, "status": "dropped", "kind": "theorem_box"}) in evs
    done = done_of(evs)
    assert [p["type"] for p in done["parts"]] == ["md"] and "couldn't draw the theorem_box" in done["parts"][0]["text"]
    assert "{" not in done["parts"][0]["text"]


def test_a_concept_the_course_does_not_have_is_repaired_or_dropped(client, material, model):
    cid, _ = published(client, material, model)
    odd = BLOCK | {"tests": ["inconnu"]}
    model.handlers["chat"] = lambda prompt, files: fence(odd)
    model.handlers["repair_block"] = lambda prompt, files: {"block": BLOCK} if "not a Concept of this Course" in prompt else {"block": odd}
    assert done_of(say(client, cid, "x"))["parts"][0]["block"]["tests"] == ["gradient"]


def test_several_blocks_and_an_unclosed_fence(client, material, model):
    cid, _ = published(client, material, model)
    model.handlers["chat"] = lambda prompt, files: f"Un.\n\n{fence(BLOCK)}\n\n{fence(BLOCK)}\n\nFin."
    assert [p["type"] for p in done_of(say(client, cid, "deux"))["parts"]] == ["md", "block", "block", "md"]
    model.handlers["chat"] = lambda prompt, files: "Un.\n\n```block\n" + json.dumps(BLOCK)[:40]  # cut off
    done = done_of(say(client, cid, "coupé"))
    assert [p["type"] for p in done["parts"]] == ["md"] and "failed its checks" in done["parts"][0]["text"]


def test_citations_come_only_from_pages_the_call_saw(client, material, model):
    cid, _ = published(client, material, model)
    model.handlers["chat"] = lambda prompt, files: "Voir [cours.pdf p.2] et [made_up.pdf p.9]."
    assert done_of(say(client, cid, "gradient"))["citations"] == [{"source": "cours.pdf", "page": 2}]


def test_conversations_are_listed_reopened_taken_back_and_deleted(client, material, model):
    cid, _ = published(client, material, model)
    a = done_of(say(client, cid, "premier ?"))
    b = done_of(say(client, cid, "second ?", conversation_id=a["conversation_id"]))
    history = [p for s, p in model.prompts if s == "chat"][-1].split("The conversation so far")[1]
    assert "premier ?" in history and "[Block shown: theorem_box" in history and "Le gradient pointe" in history  # the model sees what it drew
    other = done_of(say(client, cid, "autre"))["conversation_id"]
    assert [c["id"] for c in client.get(f"/api/courses/{cid}/chat").json()] == [other, a["conversation_id"]]
    assert client.get(f"/api/courses/{cid}/tutor").json() == []  # the Section tutor's list is its own
    conv = client.get(f"/api/courses/{cid}/chat/{a['conversation_id']}").json()
    assert [m["role"] for m in conv["messages"]] == ["learner", "tutor", "learner", "tutor"] and conv["messages"][1]["parts"][1]["type"] == "block"
    assert client.delete(f"/api/courses/{cid}/chat/messages/{b['question_id']}").status_code == 204
    assert len(client.get(f"/api/courses/{cid}/chat/{a['conversation_id']}").json()["messages"]) == 2
    assert client.delete(f"/api/courses/{cid}/chat/{other}").status_code == 204
    assert client.get(f"/api/courses/{cid}/chat/{other}").status_code == 404


def test_context_sections_add_their_pages_and_too_much_is_refused(client, material, model, monkeypatch):
    cid, sections = published(client, material, model)
    seen = {}
    model.handlers["chat"] = lambda prompt, files: seen.update(prompt=prompt) or "Vu."
    done_of(say(client, cid, "compare", sections=[sections[-1]["id"]]))
    assert f'Section "{sections[-1]["title"]}"' in seen["prompt"]
    assert client.post(f"/api/courses/{cid}/chat", json={"question": "x", "sections": [999999]}).status_code == 404
    monkeypatch.setattr("course_factory.tutor.MAX_CONTEXT_PAGES", 0)
    assert client.post(f"/api/courses/{cid}/chat", json={"question": "x", "sections": [s["id"] for s in sections]}).status_code == 422


def test_whole_documents_add_every_page_and_an_unknown_one_is_refused(client, material, model):
    cid, _ = published(client, material, model)
    seen = {}
    model.handlers["chat"] = lambda prompt, files: seen.update(prompt=prompt) or "Voir [cours.pdf p.2]."
    done = done_of(say(client, cid, "tout le cours", sources=["cours.pdf"]))
    assert 'Whole document "cours.pdf"' in seen["prompt"] and {"source": "cours.pdf", "page": 2} in done["citations"]
    assert client.post(f"/api/courses/{cid}/chat", json={"question": "x", "sources": ["nope.pdf"]}).status_code == 404


def test_the_files_shell_gets_a_container_with_the_page_text_and_shows_its_commands(client, material, model, monkeypatch):
    from contextlib import contextmanager
    from course_factory import sandbox
    cid, _ = published(client, material, model)
    monkeypatch.setattr("course_factory.app.lab_image", lambda: "img")
    boxes = []

    @contextmanager
    def box(ctx, c, image):
        boxes.append((c, image, (sandbox.export_text(ctx, c) / "cours.pdf.txt").read_text(), "open"))
        yield "cf-files-test"
        boxes.append("removed")
    monkeypatch.setattr(sandbox, "course_box", box)
    seen = {}
    model.handlers["chat"] = lambda prompt, files: seen.update(prompt=prompt) or "Voir [cours.pdf p.1]."
    evs = say(client, cid, "compte les pages", shell=True)
    assert boxes[0][:2] == (cid, "img") and "=== page 2 ===" in boxes[0][2] and boxes[-1] == "removed"
    assert model.sandboxes[-1] == "cf-files-test" and "course_shell" in seen["prompt"]
    assert ("activity", {"kind": "search", "label": "Running ls -R /course/text"}) in evs
    assert done_of(evs)["citations"] == [{"source": "cours.pdf", "page": 1}]
    say(client, cid, "sans", shell=False)
    assert model.sandboxes[-1] is None and len(boxes) == 2  # no container unless asked


def test_chat_is_hidden_during_an_exam_and_a_model_failure_is_reported(client, material, model):
    cid, _ = published(client, material, model)
    eid = client.get(f"/api/courses/{cid}/exams").json()[0]["id"]
    copy = client.post(f"/api/courses/{cid}/exams/{eid}/copies").json()
    assert client.post(f"/api/courses/{cid}/chat", json={"question": "?"}).status_code == 409
    client.post(f"/api/courses/{cid}/copies/{copy['id']}/hand-in")
    from course_factory.pi_step import StepFailed
    model.handlers["chat"] = lambda prompt, files: (_ for _ in ()).throw(StepFailed("model down"))
    assert say(client, cid, "?")[-1] == ("error", {"message": "model down"})
    assert client.get(f"/api/courses/{cid}/chat").json() == []  # nothing saved: Retry sends it again


def test_prompt_carries_the_language_and_challenge_rules(client, material, model):
    cid, _ = published(client, material, model)
    done_of(say(client, cid, "x"))
    prompt = next(p for s, p in model.prompts if s == "chat")
    assert "Never praise a wrong or partial answer" in prompt and "language the learner writes in" in prompt and "Course's language rule" in prompt
    assert "never reveal the answers" in prompt.lower() and "never think aloud" in prompt and "- gradient" not in prompt.split("Concepts")[0]
    assert "Gradient: gradient" in prompt  # the Concepts a Block's "tests" may name


def test_save_suggests_the_teaching_section_saves_checked_model_added_and_undoes(client, material, model):
    cid, sections = published(client, material, model)
    done = done_of(say(client, cid, "gradient ?"))
    url = f"/api/courses/{cid}/chat/messages/{done['message_id']}/parts/1"
    s = client.get(url + "/suggest").json()
    gradient = next(x for x in sections if x["title"] == "Gradient")
    assert s["section_id"] == gradient["id"] and s["after_block_id"] is None  # the Section's Blocks test no Concept: the end
    before = blocks_of(client, cid, gradient["id"])
    saved = client.post(url + "/save", json={"section_id": s["section_id"], "after_block_id": before[0]["id"]})
    assert saved.status_code == 200 and saved.json()["saved"]["section_id"] == gradient["id"]
    after = blocks_of(client, cid, gradient["id"])
    assert [b["id"] for b in after][0] == before[0]["id"] and after[1]["data"]["title"] == "Gradient" and len(after) == len(before) + 1
    assert after[1]["origin"] == "model_added" and after[1]["from_chat"] is True and after[1]["tests"] == ["gradient"]
    assert client.post(url + "/save", json={"section_id": gradient["id"]}).status_code == 409  # not twice
    assert client.get(f"/api/courses/{cid}/chat/{done['conversation_id']}").json()["messages"][1]["parts"][1]["saved"]["section"] == "Gradient"
    assert client.post(url + "/undo").status_code == 200
    assert [b["id"] for b in blocks_of(client, cid, gradient["id"])] == [b["id"] for b in before]
    assert client.post(url + "/undo").status_code == 409


def test_save_refuses_a_change_since_and_a_block_that_fails_its_section(client, material, model):
    cid, sections = published(client, material, model)
    done = done_of(say(client, cid, "gradient ?"))
    url = f"/api/courses/{cid}/chat/messages/{done['message_id']}/parts/1"
    gradient = next(x for x in sections if x["title"] == "Gradient")
    client.post(url + "/save", json={"section_id": gradient["id"]})
    saved = next(b for b in blocks_of(client, cid, gradient["id"]) if b["from_chat"])
    assert client.delete(f"/api/courses/{cid}/chat/messages/{done['question_id']}").status_code == 409  # a saved Block holds its messages
    assert client.put(f"/api/courses/{cid}/blocks/{saved['id']}", json={"data": saved["data"] | {"title": "Changé"}}).status_code == 200
    assert client.post(url + "/undo").status_code == 409  # edited since: Undo would lose the edit
    first = next(x for x in sections if x["title"] == "Ensembles convexes")  # "gradient" is taught later than this Section
    done2 = done_of(say(client, cid, "encore"))
    r = client.post(f"/api/courses/{cid}/chat/messages/{done2['message_id']}/parts/1/save", json={"section_id": first["id"]})
    assert r.status_code == 409 and "taught later" in r.json()["detail"]["errors"][0]


def test_handover_copies_the_section_tutor_conversation_with_its_section_pinned(client, material, model):
    cid, sections = published(client, material, model)
    sid = sections[0]["id"]
    t = events(client.post(f"/api/courses/{cid}/tutor", json={"question": "convexe ?", "section_id": sid}))[-1][1]["conversation_id"]
    new = client.post(f"/api/courses/{cid}/chat/from-tutor/{t}").json()["conversation_id"]
    conv = client.get(f"/api/courses/{cid}/chat/{new}").json()
    assert conv["pinned"] == [sid] and [m["text"][:12] for m in conv["messages"]] == ["convexe ?", "Une fonction"]
    assert client.get(f"/api/courses/{cid}/tutor").json()[0]["id"] == t  # the Section tutor keeps its own
    seen = {}
    model.handlers["chat"] = lambda prompt, files: seen.update(prompt=prompt) or "Suite."
    done_of(say(client, cid, "et ensuite ?", conversation_id=new))
    assert "convexe ?" in seen["prompt"] and f'Section "{sections[0]["title"]}"' in seen["prompt"]


QUIZ = {"component": "quiz", "origin": "model_added", "tests": ["gradient"], "data": {"questions": [
    {"prompt": "Le gradient pointe vers ?", "options": ["la croissance", "la décroissance"], "correct": [0], "explanation": "Par définition."}]}}
EXPLAIN = {"component": "explain_back", "origin": "model_added", "tests": ["gradient"], "data": {
    "concept": "gradient", "prompt": "Explique le gradient.", "rubric": ["Direction", "Norme"], "model_answer": "Il pointe vers la plus forte croissance."}}


def chat_with(model, *blocks):
    model.handlers["chat"] = lambda prompt, files: "Essaie.\n\n" + "\n\n".join(fence(b) for b in blocks) + "\n"


def concept_of(client, cid, name):
    return next(c for c in client.get(f"/api/courses/{cid}/progress").json()["concepts"] if c["name"] == name)


def test_chat_practice_is_recorded_per_concept_and_never_counts_toward_a_section(client, material, model):
    cid, sections = published(client, material, model)
    gradient = next(s for s in sections if s["title"] == "Gradient")
    client.put(f"/api/courses/{cid}/place", json={"section_id": gradient["id"]})
    before = client.get(f"/api/courses/{cid}/progress").json()["chapters"]
    chat_with(model, QUIZ)
    done = done_of(say(client, cid, "interroge-moi"))
    url = f"/api/courses/{cid}/chat/messages/{done['message_id']}/parts/1"
    assert concept_of(client, cid, "gradient")["chat"] is None
    wrong = client.post(url + "/answers", json={"question": 0, "chosen": [1]}).json()
    assert wrong["correct"] is False and wrong["correct_options"] == [0]
    assert concept_of(client, cid, "gradient")["chat"] == 0 and concept_of(client, cid, "gradient")["mastery"] == 0
    assert client.get(f"/api/courses/{cid}/progress").json()["chapters"] == before  # Section progress is untouched
    assert client.get(f"/api/courses/{cid}/results").json() == {}
    weak = [i for i in client.get(f"/api/courses/{cid}/practice").json()["items"] if i["kind"] == "weak"]
    assert weak and "You missed “gradient” in the Course chat" in weak[0]["reason"]
    assert client.post(url + "/answers", json={"question": 0, "chosen": [0]}).json()["correct"] is True  # the latest answer counts
    assert concept_of(client, cid, "gradient")["chat"] == 1
    assert not [i for i in client.get(f"/api/courses/{cid}/practice").json()["items"] if "Course chat" in i["reason"]]


def test_gaps_and_explain_back_are_recorded_and_a_block_without_concepts_records_nothing(client, material, model):
    cid, _ = published(client, material, model)
    gaps = {"component": "fill_blanks", "origin": "model_added", "tests": ["gradient"],
            "data": {"title": "Trou", "template": "Le [[1]] pointe vers la croissance.", "blanks": [{"answers": ["gradient"]}]}}
    chat_with(model, gaps, EXPLAIN, QUIZ | {"tests": []})
    done = done_of(say(client, cid, "pratique"))
    base = f"/api/courses/{cid}/chat/messages/{done['message_id']}/parts/"
    assert client.post(base + "1/outcome", json={"score": 0.5}).status_code == 200
    assert concept_of(client, cid, "gradient")["chat"] == 0.5
    graded = client.post(base + "2/grade", json={"text": "Il pointe vers la croissance."}).json()  # the fake grader gives the first step in full
    assert graded["max"] == 2 and concept_of(client, cid, "gradient")["chat"] == graded["total"] / 2
    assert client.post(base + "3/answers", json={"question": 0, "chosen": [0]}).status_code == 200
    assert concept_of(client, cid, "gradient")["chat"] == graded["total"] / 2  # nothing recorded for it
    assert client.post(base + "1/answers", json={"question": 0, "chosen": [0]}).status_code == 422  # not a quiz
    assert client.post(base + "99/answers", json={"question": 0, "chosen": [0]}).status_code == 404


def test_a_saved_block_counts_like_any_block_of_its_section(client, material, model):
    cid, sections = published(client, material, model)
    gradient = next(s for s in sections if s["title"] == "Gradient")
    chat_with(model, QUIZ)
    done = done_of(say(client, cid, "quiz"))
    url = f"/api/courses/{cid}/chat/messages/{done['message_id']}/parts/1"
    assert client.post(url + "/save", json={"section_id": gradient["id"]}).status_code == 200
    assert client.post(url + "/answers", json={"question": 0, "chosen": [1]}).status_code == 409  # answered in its Section from now on
    saved = next(b for b in blocks_of(client, cid, gradient["id"]) if b["from_chat"])
    client.post(f"/api/courses/{cid}/blocks/{saved['id']}/answers", json={"question": 0, "chosen": [1]})
    assert client.get(f"/api/courses/{cid}/results").json()[str(saved["id"])]["last"] == 0
    assert concept_of(client, cid, "gradient")["chat"] is None


def drill_turn(client, cid, question="Suivant", **body):
    return done_of(say(client, cid, question, **body))


def test_drill_asks_one_question_a_turn_leans_on_weak_concepts_and_brings_a_miss_back(client, material, model):
    cid, sections = published(client, material, model)
    seen = []
    model.handlers["chat"] = lambda prompt, files: seen.append(prompt) or "Question.\n\n" + fence(QUIZ)
    first = drill_turn(client, cid, "Quiz me", drill={"minutes": 15})
    conv = first["conversation_id"]
    assert "DRILL in progress" in seen[0] and "ONE practice question" in seen[0] and "never praise" in seen[0].lower()
    assert 'gradient (Section \\"Gradient\\", untried)' in seen[0]
    assert [p["type"] for p in first["parts"]] == ["md", "block"]  # one question
    part = f"/api/courses/{cid}/chat/messages/{first['message_id']}/parts/1"
    assert client.post(part + "/answers", json={"question": 0, "chosen": [1]}).status_code == 200  # missed
    for n in range(4):
        drill_turn(client, cid, conversation_id=conv)
        assert ("due back now" in seen[-1]) == (n == 3)  # after three other questions
    assert "Missed earlier in this Drill and due back now: ask about [\"gradient\"]" in seen[-1]
    plain = done_of(say(client, cid, "hors drill"))  # another conversation: no Drill
    assert "DRILL" not in seen[-1] and plain["conversation_id"] != conv


def test_drill_stops_when_asked_or_at_the_time_limit_and_summarises_with_section_links(client, material, model, clock):
    import datetime as dt
    cid, sections = published(client, material, model)
    gradient = next(s for s in sections if s["title"] == "Gradient")
    seen = []
    model.handlers["chat"] = lambda prompt, files: seen.append(prompt) or "Question.\n\n" + fence(QUIZ)
    first = drill_turn(client, cid, "Quiz me", drill={"minutes": 10})
    client.post(f"/api/courses/{cid}/chat/messages/{first['message_id']}/parts/1/answers", json={"question": 0, "chosen": [1]})
    clock["now"] += dt.timedelta(minutes=11)  # past the limit: the next turn is the closing one
    model.handlers["chat"] = lambda prompt, files: seen.append(prompt) or "C'est fini."
    last = drill_turn(client, cid, "Suivant", conversation_id=first["conversation_id"])
    assert "DRILL OVER" in seen[-1]
    summary = last["parts"][-1]
    assert summary == {"type": "summary", "right": [], "review": [{"concept": "gradient", "section_id": gradient["id"], "section": "Gradient"}]}
    again = drill_turn(client, cid, "Encore", conversation_id=first["conversation_id"])  # a plain chat from here
    assert "DRILL" not in seen[-1] and again["parts"][-1]["type"] == "md"
    second = drill_turn(client, cid, "Quiz me", drill={"minutes": 10})
    stopped = drill_turn(client, cid, "stop", conversation_id=second["conversation_id"], stop_drill=True)
    assert "DRILL OVER" in seen[-1] and stopped["parts"][-1] == {"type": "summary", "right": [], "review": []}
    assert client.post(f"/api/courses/{cid}/chat", json={"question": "x", "stop_drill": True}).status_code == 409


def test_both_tutors_show_what_they_read_on_the_activity_line(client, material, model, worded_pages):  # noqa: F811
    cid, sections = published(client, material, model)
    for evs in (say(client, cid, "ensemble convexe ?"),
                events(client.post(f"/api/courses/{cid}/tutor", json={"question": "ensemble convexe ?", "section_id": sections[0]["id"]}))):
        acts = [d for e, d in evs if e == "activity"]
        assert acts[0]["kind"] == "search" and any(a["kind"] == "read" and a["source"] == "cours.pdf" for a in acts)


def test_the_next_turn_sees_the_block_and_what_the_learner_answered_so_it_can_challenge_it(client, material, model):
    cid, _ = published(client, material, model)
    chat_with(model, QUIZ)
    done = done_of(say(client, cid, "interroge-moi"))
    client.post(f"/api/courses/{cid}/chat/messages/{done['message_id']}/parts/1/answers", json={"question": 0, "chosen": [1]})
    seen = {}
    model.handlers["chat"] = lambda prompt, files: seen.update(prompt=prompt) or "Pas tout à fait."
    say(client, cid, "pourquoi j'ai faux ?", conversation_id=done["conversation_id"])
    question = QUIZ["data"]["questions"][0]["prompt"]
    assert question in seen["prompt"] and "The learner answered: question 1: [1], scored 0.0" in seen["prompt"]


def test_a_real_quiz_fence_with_raw_latex_and_one_brace_too_many_parses_with_its_maths_intact():
    from course_factory.tutor import proposal_json
    # from a real chat answer (Optimisation, 2026-11-15): \min is not a JSON escape, \frac and \nabla would read as form feed and newline
    raw = r'''{"component":"quiz","data":{"questions":[{"prompt":"Pour $\min_{x\in\mathbb{R}^n} J(x)$, quelle combinaison ?","options":["$X^* = \frac{1}{2}A^{-1}b$","$X^* = A^{-1}b$"],"correct":[1],"explanation":"Le CNO1 donne $\nabla J(X) = AX - b = 0$."}]}},"citations":[{"source":"chap1/c.pdf","page":16}],"origin":"from_source","tests":["coercivité"]}'''
    b = proposal_json(raw)
    q = b["data"]["questions"][0]
    assert q["prompt"].startswith(r"Pour $\min_{x\in\mathbb{R}^n}") and q["options"][0] == r"$X^* = \frac{1}{2}A^{-1}b$"
    assert q["explanation"] == r"Le CNO1 donne $\nabla J(X) = AX - b = 0$." and b["citations"][0]["page"] == 16


def test_a_proposal_with_bare_quotes_in_code_or_its_last_brace_missing_parses():
    from course_factory.tutor import proposal_json
    # from real Section tutor proposals (Advanced BD, 2026-11-14) that the learner had to send back
    quotes = '{"changes": [{"action": "add", "block": {"component": "code", "data": {"code": "rdd2 = rdd.filter(lambda x: "ERROR" in x)"}}}]}'
    assert proposal_json(quotes)["changes"][0]["block"]["data"]["code"] == 'rdd2 = rdd.filter(lambda x: "ERROR" in x)'
    unclosed = '{"changes": [\n  {"action": "remove", "block_id": 1120}\n]'
    assert proposal_json(unclosed) == {"changes": [{"action": "remove", "block_id": 1120}]}


def test_regenerate_rewrites_a_chat_block_with_the_learners_note_and_refuses_a_saved_one(client, material, model):
    cid, sections = published(client, material, model)
    chat_with(model, QUIZ)
    done = done_of(say(client, cid, "quiz"))
    url = f"/api/courses/{cid}/chat/messages/{done['message_id']}/parts/1"
    seen = {}
    harder = QUIZ | {"data": {"questions": [QUIZ["data"]["questions"][0] | {"prompt": "Plus dur ?"}]}}
    model.handlers["repair_block"] = lambda prompt, files: seen.update(prompt=prompt) or {"block": harder}
    r = client.post(url + "/regenerate", json={"note": "plus difficile"})
    assert r.status_code == 200 and r.json()["block"]["data"]["questions"][0]["prompt"] == "Plus dur ?" and "plus difficile" in seen["prompt"]
    assert client.get(f"/api/courses/{cid}/chat/{done['conversation_id']}").json()["messages"][1]["parts"][1]["block"]["data"]["questions"][0]["prompt"] == "Plus dur ?"
    assert client.post(url + "/regenerate", json={}).status_code == 200 and "different take" in seen["prompt"]  # no note: another take
    gradient = next(s for s in sections if s["title"] == "Gradient")
    assert client.post(url + "/save", json={"section_id": gradient["id"]}).status_code == 200
    assert client.post(url + "/regenerate", json={}).status_code == 409


def test_rewrite_changes_the_selected_passage_of_an_answers_text(client, material, model):
    cid, _ = published(client, material, model)
    chat_with(model, QUIZ)
    done = done_of(say(client, cid, "quiz"))
    url = f"/api/courses/{cid}/chat/messages/{done['message_id']}/parts/0"
    seen = {}
    model.handlers["rewrite_text"] = lambda prompt, files: seen.update(prompt=prompt) or {"text": "Essaie donc."}
    r = client.post(url + "/rewrite", json={"selection": "Essaie", "note": "plus poli"})
    assert r.status_code == 200 and r.json()["text"] == "Essaie donc." and "plus poli" in seen["prompt"] and "SELECTION:Essaie" in seen["prompt"]
    msg = client.get(f"/api/courses/{cid}/chat/{done['conversation_id']}").json()["messages"][1]
    assert msg["parts"][0]["text"] == "Essaie donc." and msg["text"] == "Essaie donc."
    assert client.post(url[:-1] + "1/rewrite", json={"selection": "x"}).status_code == 404  # a Block, not text


def test_answer_text_unwraps_a_nested_answer_object_and_heals_twice_escaped_latex():
    from course_factory.chat import answer_text
    nested = '{"text": "The recurrence $w_{k+1}-w^\\\\star = (1-\\\\rho L)(w_k-w^\\\\star)$ and $\\\\\\\\rho$."}'  # a real local-model rewrite
    assert answer_text(nested) == "The recurrence $w_{k+1}-w^\\star = (1-\\rho L)(w_k-w^\\star)$ and $\\rho$."
    assert answer_text("$a \\\\ b$, {not json") == "$a \\\\ b$, {not json"  # a real line break and a brace stay


def test_an_answer_with_an_id_is_written_on_after_the_page_drops_and_the_page_can_find_it(client, material, model):
    import threading
    import time
    cid, _ = published(client, material, model)
    gate, chat = threading.Event(), model.handlers["chat"]
    model.handlers["chat"] = lambda prompt, files: (gate.wait(5), chat(prompt, files))[1]
    with client.stream("POST", f"/api/courses/{cid}/chat", json={"question": "c'est quoi le gradient ?", "answer": "dropped-1"}) as r:
        assert r.status_code == 200  # the page goes away before the model answers
    assert client.get(f"/api/courses/{cid}/answers/dropped-1").json() == {"done": False, "conversation_id": None, "error": None}
    gate.set()
    for _ in range(100):
        if (state := client.get(f"/api/courses/{cid}/answers/dropped-1").json())["done"]:
            break
        time.sleep(0.05)
    assert state["done"] and state["error"] is None
    texts = [m["text"] for m in client.get(f"/api/courses/{cid}/chat/{state['conversation_id']}").json()["messages"]]
    assert "Voici l'idée" in texts[-1]  # saved, so reopening the conversation shows it
    assert client.get(f"/api/courses/{cid}/answers/unknown-1").status_code == 404
    assert client.post(f"/api/courses/{cid}/answers/unknown-1/stop").status_code == 204
    assert client.post(f"/api/courses/{cid}/chat", json={"question": "?", "answer": "../bad"}).status_code == 422
