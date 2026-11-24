"""Course-first study (#30): the subject setting, Step answers anchored to the quoted course page, Challenge only on demand."""
import json

import pytest

from test_chat import done_of, say
from test_learner import published
from test_tutor import events

P1 = "Définition ensemble convexe : une partie C est convexe lorsque pour tous points x et y de C le segment qui les joint reste dans C."
P2 = "Méthode du gradient à pas fixe : on part d'un point initial et on avance dans la direction opposée au gradient avec un pas constant."


@pytest.fixture
def long_pages(model):
    texts = {"cours.pdf, page 1": P1, "cours.pdf, page 2": P2, "TD1.pdf, page 1": "exercice", "TD1_corrige.pdf, page 1": "corrigé"}
    model.handlers["read_page"] = lambda prompt, files: {
        "text": next(v for k, v in texts.items() if f"SOURCE: {k}" in prompt), "readable": True}


def theoretical(client, cid):
    r = client.patch(f"/api/courses/{cid}", json={"goal": "deep", "subject": "theoretical"})
    assert r.status_code == 200 and r.json()["subject"] == "theoretical"


def chat_prompt(model):
    return [p for s, p in model.prompts if s == "chat"][-1]


def test_the_subject_can_be_set_and_other_settings_leave_it(client, material, model):
    cid, _ = published(client, material, model)
    theoretical(client, cid)
    r = client.patch(f"/api/courses/{cid}", json={"goal": "deep", "language": "fr"})
    assert r.json()["subject"] == "theoretical" and r.json()["language"] == "fr"
    assert client.patch(f"/api/courses/{cid}", json={"goal": "deep", "subject": "physics"}).status_code == 422


def test_a_quoted_line_on_a_theoretical_course_gets_a_step_answer_from_its_page_and_the_ones_before(client, material, model, long_pages):
    cid, _ = published(client, material, model)
    theoretical(client, cid)
    model.handlers["chat"] = lambda prompt, files: "On fixe le pas, puis on recule le long du gradient [cours.pdf p.1]."
    done = done_of(say(client, cid, "« une partie C est convexe lorsque pour tous points x et y de C le segment » comment on obtient ça ?"))
    assert done["mode"] == "step" and done["anchor"] == {"source": "cours.pdf", "page": 1}
    assert done["activity"] == [{"kind": "read", "label": "Found it on cours.pdf p.1", "source": "cours.pdf", "page": 1}]
    prompt = chat_prompt(model)
    assert "Mode: Step" in prompt and "(cours.pdf p.1)" in prompt and "Cite that page as [cours.pdf p.1]" in prompt
    assert "segment qui les joint" in prompt and "direction opposée au gradient" not in prompt  # never a page after the quoted one
    assert "ensemble convexe" in prompt.split("The Course's Concepts")[1] and "Gradient: gradient" not in prompt  # known so far only
    m = client.get(f"/api/courses/{cid}/chat/{done['conversation_id']}").json()["messages"][-1]
    assert m["mode"] == "step" and m["anchor"] == {"source": "cours.pdf", "page": 1}


def test_a_question_that_quotes_nothing_or_a_non_theoretical_course_is_explained(client, material, model, long_pages):
    cid, _ = published(client, material, model)
    quote = "une partie C est convexe lorsque pour tous points x et y de C le segment qui les joint, pourquoi ?"
    assert done_of(say(client, cid, quote))["mode"] == "explain"  # mixed subject: Explain, as before
    theoretical(client, cid)
    assert done_of(say(client, cid, "c'est quoi le gradient ?"))["mode"] == "explain"  # no quote
    assert "Mode: Explain" in chat_prompt(model) and "no question for the learner" in chat_prompt(model)
    done = done_of(say(client, cid, quote, mode="test"))  # the learner's choice wins
    assert done["mode"] == "test" and done["anchor"] is None and "Mode: Test me" in chat_prompt(model)
    assert "Challenge, only in Test me mode" in chat_prompt(model)


def test_beyond_the_course_and_more_detail_are_modes_the_learner_asks_for(client, material, model, long_pages):
    cid, _ = published(client, material, model)
    theoretical(client, cid)
    assert done_of(say(client, cid, "Beyond the course", mode="beyond"))["mode"] == "beyond"
    assert "Mode: Beyond the course" in chat_prompt(model) and "not from the course" in chat_prompt(model)


def test_a_step_answer_over_its_budget_is_shown_and_recorded_as_a_failure_class(client, material, model, long_pages):
    cid, _ = published(client, material, model)
    theoretical(client, cid)
    long = " ".join(["mot"] * 200) + "\n\n$$x_{k+1} = x_k - \\rho \\nabla J(x_k)$$"
    model.handlers["chat"] = lambda prompt, files: long
    done = done_of(say(client, cid, "une partie C est convexe lorsque pour tous points x et y de C le segment, comment ?"))
    assert done["mode"] == "step" and "mot mot" in done["parts"][0]["text"]
    long_class = next(c for c in client.get("/api/failures", params={"course": cid}).json() if c["class"] == "long-step-answer")
    assert long_class["count"] == 1 and "200 words" in long_class["examples"][0]
    model.handlers["chat"] = lambda prompt, files: "Court [cours.pdf p.1]."
    say(client, cid, "une partie C est convexe lorsque pour tous points x et y de C le segment, et là ?")
    assert next(c for c in client.get("/api/failures", params={"course": cid}).json() if c["class"] == "long-step-answer")["count"] == 1


def test_the_section_tutor_anchors_too_and_explain_differently_stays_as_it_was(client, material, model, long_pages):
    cid, sections = published(client, material, model)
    theoretical(client, cid)
    seen = {}
    model.handlers["tutor"] = lambda prompt, files: seen.update(prompt=prompt) or "Le pas est fixé [cours.pdf p.2]."
    url = f"/api/courses/{cid}/tutor"
    evs = events(client.post(url, json={"question": "on avance dans la direction opposée au gradient avec un pas constant : pourquoi ?",
                                        "section_id": sections[0]["id"]}))
    done = evs[-1][1]
    assert done["mode"] == "step" and done["anchor"] == {"source": "cours.pdf", "page": 2} and "Mode: Step" in seen["prompt"]
    assert json.loads(json.dumps(client.get(f"{url}/{done['conversation_id']}").json()[-1]["anchor"])) == {"source": "cours.pdf", "page": 2}


def test_explain_this_step_on_a_selection_anchors_to_the_blocks_page_and_a_made_up_page_is_ignored(client, material, model, long_pages):
    cid, sections = published(client, material, model)
    theoretical(client, cid)
    url = f"/api/courses/{cid}/tutor"
    ask = {"question": "« $x_{k+1} = x_k - \\rho d_k$ »\n\nExplain this step.", "section_id": sections[0]["id"], "mode": "step"}
    done = events(client.post(url, json=ask | {"anchor": {"source": "cours.pdf", "page": 2}}))[-1][1]
    assert done["mode"] == "step" and done["anchor"] == {"source": "cours.pdf", "page": 2}  # a formula alone: the page says where
    done = events(client.post(url, json=ask | {"anchor": {"source": "secret.pdf", "page": 1}}))[-1][1]
    assert done["anchor"] is None  # not a page of this Course: anchored by its words, here none


def test_a_step_answers_bare_page_citation_is_a_page_of_the_anchored_source(client, material, model, long_pages):
    cid, sections = published(client, material, model)
    theoretical(client, cid)
    model.handlers["chat"] = lambda prompt, files: "Le segment reste dans C [p.1]."
    done = done_of(say(client, cid, "« une partie C est convexe lorsque pour tous points x et y de C le segment » comment ?"))
    assert done["citations"] == [{"source": "cours.pdf", "page": 1}] and "[cours.pdf p.1]" in done["parts"][0]["text"]
    model.handlers["tutor"] = lambda prompt, files: "Le pas est fixé [p.2]."
    q = {"question": "on avance dans la direction opposée au gradient avec un pas constant : pourquoi ?", "section_id": sections[0]["id"]}
    done = events(client.post(f"/api/courses/{cid}/tutor", json=q))[-1][1]
    assert done["citations"] == [{"source": "cours.pdf", "page": 2}]
