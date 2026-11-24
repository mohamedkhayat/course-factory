import copy

import pytest

from course_factory.checks import check_blocks
from test_chapters import first_block, generate, one_block
from test_kind_diagram import CITE, SOURCES, items


def parts(*names):  # labelled apart from the tree diagram of the same page
    return [i | {"label": f"Partition {i['id']}"} for i in items(*names)]


GOOD = {
    "kind": "pipeline", "items": parts("a", "b", "c", "d"), "order": ["a", "b", "c", "d"],
    "steps": [
        {"caption": "Les enregistrements arrivent dans la partition a.", "cite": CITE, "highlight": ["a"]},
        {"caption": "Un enregistrement passe de a à b.", "cite": CITE, "move": ["a", "b"], "links": [["a", "b"]]},
        {"caption": "La partition d apparaît pour le shuffle.", "cite": CITE, "add": ["d"], "labels": {"c": "Partition c bis"}},
        {"caption": "Le jeton continue vers c.", "cite": CITE, "move": ["b", "c"], "highlight": ["c"], "remove": ["a"]},
    ],
}


def check(data, sources=SOURCES):
    (block,), (errors,) = check_blocks([{"component": "stepped_animation", "origin": "model_added", "citations": [], "data": data}], sources)
    return block, errors


def changed(**over):
    return copy.deepcopy(GOOD) | over


def step(n, **over):
    steps = copy.deepcopy(GOOD["steps"])
    steps[n] = steps[n] | over
    return steps


def test_a_valid_animation_passes_and_its_pages_become_citations():
    block, errors = check(GOOD)
    assert errors == [] and block["citations"] == [{**CITE, "quote": ""}]


@pytest.mark.parametrize("data, error", [
    (changed(steps=GOOD["steps"][:2]), "Field required|at least 2|3 to 12"),
    (changed(steps=GOOD["steps"] * 4), "3 to 12"),
    (changed(steps=step(0, highlight=["zz"])), "not items"),
    (changed(steps=step(1, move=["a", "c"])), "not a link"),
    (changed(steps=step(1, links=[["a", "d"]])), "not a link"),
    (changed(steps=step(0, highlight=[], add=[])), "changes nothing"),
    (changed(steps=step(0, caption="  ")), "caption"),
    (changed(steps=step(0, caption="mot " * 100)), "caption"),
    (changed(steps=step(0, highlight=["d"])), "not there yet"),  # d is added in step 3
    (changed(steps=step(1, move=["c", "d"], links=[])), "not there yet"),
    (changed(steps=step(0, cite={"source": "cours.pdf", "page": 9})), "does not exist"),
])
def test_an_animation_that_breaks_the_rules_is_an_error(data, error):
    assert any(any(w in e for w in error.split("|")) for e in check(data)[1]), check(data)[1]


def test_a_step_without_a_cite_is_an_error():
    bad = changed(steps=[{k: v for k, v in st.items() if k != "cite"} for st in GOOD["steps"]])
    assert any("cite" in e for e in check(bad)[1])


def test_a_failing_animation_is_repaired_and_the_repair_sees_the_step_error(client, material, model):
    fixed = one_block("stepped_animation", GOOD, citations=[CITE])[0]
    model.handlers["repair_block"] = lambda prompt, files: {"block": fixed} if "not a link" in prompt and "stepped_animation" in prompt else {"block": {}}
    cid = generate(client, material, model, blocks=one_block("stepped_animation", changed(steps=step(1, move=["a", "c"])), citations=[CITE]))
    b = first_block(client, cid)
    assert b["status"] == "ok" and b["component"] == "stepped_animation" and len(b["data"]["steps"]) == 4


def test_the_writing_prompt_and_catalogue_name_the_animation(client, material, model):
    generate(client, material, model)
    prompt = next(p for step, p in model.prompts if step == "write_section")
    assert "stepped_animation" in prompt and "shuffle" in prompt
