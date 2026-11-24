import copy

import pytest

from course_factory.checks import check_blocks
from test_chapters import chapters, first_block, generate, one_block
from test_tutor import ask

CITE = {"source": "cours.pdf", "page": 1}
SOURCES = {"cours.pdf": 2}


def items(*names, **extra):
    """Items a, b, c... named by their label; `extra` maps an item id to its kind fields."""
    return [{"id": n, "label": f"Etape {n}", "explanation": f"{n} fait une chose, d'après le cours.", "cite": CITE, **extra.get(n, {})} for n in names]


GOOD = {
    "tree": {"kind": "tree", "items": items("a", "b", "c", "d", b={"parent": "a"}, c={"parent": "a"}, d={"parent": "b"})},
    "layers": {"kind": "layers", "items": items("a", "b", "c", a={"layer": 0}, b={"layer": 1}, c={"layer": 1}), "links": [["a", "b"], ["a", "c", "uses"]]},
    "nesting": {"kind": "nesting", "items": items("a", "b", "c", b={"container": "a"}, c={"container": "a"})},
    "pipeline": {"kind": "pipeline", "items": items("a", "b", "c"), "order": ["a", "b", "c"]},
    "cycle": {"kind": "cycle", "items": items("a", "b", "c"), "order": ["a", "b", "c"]},
    "state_machine": {"kind": "state_machine", "items": items("a", "b"), "links": [["a", "b", "start"], ["b", "a", "stop"], ["b", "b"]]},
    "fan_out": {"kind": "fan_out", "items": items("a", "b", "c"), "hub": "a", "spokes": ["b", "c"]},
}


def check(data, sources=SOURCES):
    (block,), (errors,) = check_blocks([{"component": "kind_diagram", "origin": "model_added", "citations": [], "data": data}], sources)
    return block, errors


def changed(kind, **over):
    return copy.deepcopy(GOOD[kind]) | over


@pytest.mark.parametrize("kind", GOOD)
def test_a_valid_structure_for_each_kind_passes_and_its_pages_become_citations(kind):
    block, errors = check(GOOD[kind])
    assert errors == [] and block["citations"] == [{**CITE, "quote": ""}]


@pytest.mark.parametrize("kind, data, error", [
    ("tree", changed("tree", items=items("a", "b", "c")), "exactly one root"),  # three roots
    ("tree", changed("tree", items=items("a", "b", "c", a={"parent": "c"}, b={"parent": "a"}, c={"parent": "b"})), "exactly one root"),
    ("tree", changed("tree", items=items("a", "b", "c", "d", b={"parent": "a"}, c={"parent": "d"}, d={"parent": "c"})), "loop"),
    ("tree", changed("tree", items=items("a", "b", "c", b={"parent": "a"}, c={"parent": "zz"})), "not an item"),
    ("layers", changed("layers", items=items("a", "b", "c", a={"layer": 0}, b={"layer": 2}, c={"layer": 2})), "layer"),  # layer 1 is empty
    ("layers", changed("layers", items=items("a", "b", "c", a={"layer": 0}, b={"layer": 0}, c={"layer": 0})), "layer"),
    ("layers", changed("layers", links=[["a", "zz"]]), "ids of items"),
    ("nesting", changed("nesting", items=items("a", "b", "c")), "containment"),
    ("nesting", changed("nesting", items=items("a", "b", "c", a={"container": "c"}, b={"container": "a"}, c={"container": "b"})), "loop"),
    ("pipeline", changed("pipeline", order=["a", "b"]), "`order`"),
    ("pipeline", changed("pipeline", order=["a", "b", "b"]), "`order`"),
    ("cycle", changed("cycle", order=["a", "b", "c", "x"]), "`order`"),
    ("state_machine", changed("state_machine", links=[]), "links"),
    ("state_machine", changed("state_machine", links=[["a", "zz", "go"]]), "ids of items"),
    ("state_machine", changed("state_machine", items=items("a", "b", "c"), links=[["a", "b"]]), "every state"),
    ("fan_out", changed("fan_out", hub="zz"), "`hub`"),
    ("fan_out", changed("fan_out", spokes=["a", "b", "c"]), "`hub`"),
    ("fan_out", changed("fan_out", items=items("a", "b", "c", "d")), "every item"),
])
def test_a_structure_invalid_for_its_kind_is_an_error(kind, data, error):
    assert any(error in e for e in check(data)[1]), check(data)[1]


@pytest.mark.parametrize("kind, data, error", [
    ("pipeline", changed("pipeline", items=items("a", "b"), order=["a", "b"]), "3 to 9"),
    ("pipeline", changed("pipeline", items=items(*"abcdefghij"), order=list("abcdefghij")), "3 to 9"),
    ("tree", changed("tree", items=[{**i, "label": "x" * 41} for i in GOOD["tree"]["items"]]), "40 characters"),
    ("tree", changed("tree", items=[{**i, "label": "$x^2$"} for i in GOOD["tree"]["items"]]), "plain text"),
    ("tree", changed("tree", items=[{**i, "explanation": "mot " * 100} for i in GOOD["tree"]["items"]]), "one or two sentences"),
    ("pipeline", changed("pipeline", items=items("a", "a", "c"), order=["a", "a", "c"]), "unique"),
])
def test_label_length_and_item_count_limits(kind, data, error):
    assert any(error in e for e in check(data)[1])


def test_every_item_cites_a_page_that_exists():
    bad = changed("pipeline", items=[{**i, "cite": {"source": "cours.pdf", "page": 9}} for i in GOOD["pipeline"]["items"]])
    assert any("page 9" in e and "does not exist" in e for e in check(bad)[1])
    assert any("cite" in e for e in check(changed("pipeline", items=[{k: v for k, v in i.items() if k != "cite"} for i in GOOD["pipeline"]["items"]]))[1])
    two = changed("pipeline", items=[{**i, "cite": {"source": "cours.pdf", "page": 2}} if i["id"] == "b" else i for i in GOOD["pipeline"]["items"]])
    assert [c["page"] for c in check(two)[0]["citations"]] == [1, 2]


def test_a_failing_diagram_is_repaired_and_the_repair_sees_the_structure_error(client, material, model):
    fixed = one_block("kind_diagram", GOOD["tree"], citations=[CITE])[0]
    model.handlers["repair_block"] = lambda prompt, files: {"block": fixed} if "exactly one root" in prompt and "kind_diagram" in prompt else {"block": {}}
    cid = generate(client, material, model, blocks=one_block("kind_diagram", changed("tree", items=items("a", "b", "c")), citations=[CITE]))
    b = first_block(client, cid)
    assert b["status"] == "ok" and b["component"] == "kind_diagram" and b["data"]["kind"] == "tree"


def test_the_writing_prompt_names_the_kinds_and_the_course_language(client, material, model):
    generate(client, material, model)
    prompt = next(p for step, p in model.prompts if step == "write_section")
    assert "kind_diagram" in prompt and all(k in prompt for k in ("tree", "state_machine", "fan_out")) and "Language rule above" in prompt


def test_asking_the_tutor_about_an_item_gives_it_the_item_as_context(client, material, model):
    cid = generate(client, material, model, blocks=one_block("kind_diagram", GOOD["pipeline"], citations=[CITE]))
    for c in chapters(client, cid).values():
        client.post(f"/api/courses/{cid}/chapters/{c['id']}/publish")
    block = first_block(client, cid)
    seen = {}
    model.handlers["tutor"] = lambda prompt, files: seen.update(prompt=prompt) or "Vu."
    ask(client, cid, "c'est quoi ?", attached=[block["id"]], items={block["id"]: "b"})
    assert "about this item of the diagram: Etape b: b fait une chose" in seen["prompt"]
    ask(client, cid, "et ça ?", attached=[block["id"]])
    assert "about this item" not in seen["prompt"]
