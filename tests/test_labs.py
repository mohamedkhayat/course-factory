import json

import pytest

from conftest import make_pdf
from test_chapters import generate


@pytest.fixture
def with_tp(material):
    make_pdf(material / "TP1.pdf", 1)
    return material


@pytest.fixture
def lab(client, with_tp, model):
    cid = generate(client, with_tp, model)
    assert client.get(f"/api/courses/{cid}/run").json()["status"] == "done"
    [summary] = client.get(f"/api/courses/{cid}/labs").json()
    return cid, client.get(f"/api/courses/{cid}/labs/{summary['id']}").json()


def run(client, cid, lab_id, code):
    with client.websocket_connect(f"ws://127.0.0.1:8765/api/courses/{cid}/labs/{lab_id}/run") as ws:
        ws.send_json({"code": code})
        outputs = []
        while "done" not in (m := ws.receive_json()):
            outputs.append(m["output"])
        return outputs, m["error"]


def test_checks_are_proven_repaired_or_left_out(lab, model):
    cid, l = lab
    assert l["title"].startswith("TP1") and [s["statement"][:8] for s in l["steps"]] == ["Définir ", "Lire dat"]
    assert all(s["solution"] is None and s["hints"] == [] for s in l["steps"])  # locked until passed or given up
    [flag] = l["flags"]  # the Step whose Solution fails its own Check is dropped and noted
    assert flag["step"] == 3 and any("fails the Solution" in e for e in flag["errors"])
    repairs = [p for step, p in model.prompts if step == "repair_lab_step"]
    assert any("passes wrong version 1" in p for p in repairs)  # the weak 'assert True' Check was sent back


def test_hints_give_up_and_check_in_learner_kernel(client, lab):
    cid, l = lab
    first, second = l["steps"]
    base = f"/api/courses/{cid}/labs/{l['id']}/steps"
    assert client.post(f"{base}/{first['id']}/hint").json()["hints"] == ["Use **."]
    assert client.post(f"{base}/{first['id']}/hint").json()["hints_left"] == 0
    assert client.post(f"{base}/{first['id']}/hint").status_code == 409

    outputs, err = run(client, cid, l["id"], "def f(x):\n    return 2*x\nprint('hi')")
    assert err is None and outputs[0]["text"] == "hi\n"
    res = client.post(f"{base}/{first['id']}/check").json()
    assert not res["passed"] and res["message"] == "f(3) should be 9" and res["step"]["solution"] is None
    run(client, cid, l["id"], "def f(x):\n    return x**2")
    res = client.post(f"{base}/{first['id']}/check").json()
    assert res["passed"] and res["step"]["solution"] == "def f(x):\n    return x**2"
    assert client.get(f"/api/stats?course_id={cid}").status_code == 200

    assert client.post(f"{base}/{second['id']}/give-up").json()["solution"].startswith("import csv")
    _, err = run(client, cid, l["id"], "1/0")
    assert err["ename"] == "ZeroDivisionError"
    assert client.get(f"/api/courses/{cid}/labs").json()[0]["passed"] == 1
    client.post(f"/api/courses/{cid}/labs/{l['id']}/kernel/stop")
    assert not client.get(f"/api/courses/{cid}/labs/{l['id']}").json()["kernel_running"]


def test_notebook_round_trip(client, lab):
    cid, l = lab
    url = f"/api/courses/{cid}/labs/{l['id']}/notebook"
    nb = json.loads(client.get(url).text)
    assert nb["nbformat"] == 4 and "".join(nb["cells"][2]["source"]) == "def f(x):\n    pass"
    nb["cells"][2]["source"] = "def f(x):\n    return x**2"
    assert client.put(url, json={"notebook": nb}).status_code == 200
    assert "".join(json.loads(client.get(url).text)["cells"][2]["source"]) == "def f(x):\n    return x**2"
    assert client.put(url, json={"notebook": {"cells": "nope"}}).status_code == 422


def test_notebook_tp_is_read_from_its_cells(client, material, model):
    import nbformat
    nb = nbformat.v4.new_notebook(cells=[nbformat.v4.new_markdown_cell("Exercice : gradient à pas fixe"),
                                         nbformat.v4.new_code_cell("x0 = 1.0")])
    nbformat.write(nb, material / "TP2.ipynb")
    cid = generate(client, material, model)
    assert client.get(f"/api/courses/{cid}/run").json()["status"] == "done"
    tp = next(p for step, p in model.prompts if step == "build_lab").split("TP:", 1)[1]
    assert "gradient à pas fixe" in tp and "x0 = 1.0" in tp
    assert len(client.get(f"/api/courses/{cid}/labs").json()) == 1
