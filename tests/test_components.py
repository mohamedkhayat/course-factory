import json
from pathlib import Path

import pytest

from course_factory import components
from test_chapters import generate

FIXTURES = Path(__file__).parent / "components"
GOOD = (FIXTURES / "good.tsx").read_text()
SAMPLES = json.loads((FIXTURES / "samples.json").read_text())


@pytest.mark.parametrize("fixture, failed_gate, reason", [
    ("type_error", "tsc", "toFixed"),
    ("forbidden_import", "imports", "react-dom/server"),
    ("network", "render", "network access"),
    ("crash", "render", "crash: boom"),
])
def test_gate_rejects_each_kind_of_broken_file(tmp_path, fixture, failed_gate, reason):
    result = components.gate((FIXTURES / f"{fixture}.tsx").read_text(), SAMPLES, tmp_path)
    last = result["gates"][-1]
    assert not result["ok"] and last["gate"] == failed_gate and reason in " ".join(last["errors"])


def test_gate_passes_a_good_file_with_bundle_and_screenshot(tmp_path):
    result = components.gate(GOOD, SAMPLES, tmp_path)
    assert result["ok"] and [g["gate"] for g in result["gates"]] == ["tsc", "imports", "bundle", "render"]
    assert (tmp_path / "component.js").stat().st_size > 1000 and (tmp_path / "screenshot.png").exists()


PROPOSAL = {"name": "saddle_point", "description": "A saddle point with its title.", "why": "no Component shows saddles",
            "schema": {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]},
            "samples": [{"title": "Lagrange"}, {"title": 3}]}  # the second doesn't fit the schema: dropped


@pytest.fixture
def proposing(model):
    model.handlers["write_section"] = lambda prompt, files: {
        "blocks": [{"component": "saddle_point", "data": {"title": "Point selle"}, "origin": "model_added"}],
        "proposals": [PROPOSAL]}
    builds = iter([(FIXTURES / "type_error.tsx").read_text()])
    model.handlers["build_component"] = lambda prompt, files: {"code": next(builds, GOOD)}
    return model


def custom_blocks(client, cid):
    out = []
    for ch in client.get(f"/api/courses/{cid}/outline").json()["chapters"]:
        for s in client.get(f"/api/courses/{cid}/chapters/{ch['id']}").json()["sections"]:
            out += [b for b in s["blocks"] if b["component"] == "saddle_point"]
    return out


def test_proposed_component_is_gated_previewed_approved_and_reviewed(client, material, proposing, data_dir):
    cid = generate(client, material, proposing)
    [c] = client.get("/api/components").json()
    assert c["status"] == "preview" and c["made_by_local_model"] and not c["reviewed"] and c["has_screenshot"]
    retry = [p for step, p in proposing.prompts if step == "build_component"][1]
    assert "toFixed" in retry.split("ERRORS:", 1)[1]  # the second build was told why the first failed
    blocks = custom_blocks(client, cid)
    assert blocks and all(b["status"] == "ok" and "awaits your preview" in b["flags"][0] for b in blocks)
    assert "Point selle" in blocks[0]["fallback_markdown"]
    preview = client.get(f"/api/components/{c['id']}").json()
    assert preview["samples"] == [{"title": "Lagrange"}] and len(preview["blocks"]) == len(blocks)
    assert client.get(f"/api/components/{c['id']}/screenshot").status_code == 200
    assert client.get(f"/api/components/{c['id']}/bundle.js").status_code == 200

    assert client.post(f"/api/components/{c['id']}/approve").json()["status"] == "approved"
    item = json.loads((data_dir / "registry" / "saddle_point.json").read_text())
    assert item["meta"]["provenance"] == "local-model" and item["meta"]["reviewed"] is False and item["files"][0]["content"] == GOOD
    assert all(b["flags"] == [] for b in custom_blocks(client, cid))
    assert client.post(f"/api/components/{c['id']}/approve").status_code == 409
    assert any(step == "component_preview_gate" for step in [t["step"] for t in client.get(f"/api/courses/{cid}/traces").json()])

    # Claude Code works the Review Queue from outside: a stricter schema re-validates the Blocks
    [queued] = client.get("/api/review-components").json()
    assert queued["code"] == GOOD and queued["blocks"]
    strict = {**PROPOSAL["schema"], "properties": {"title": {"type": "string", "pattern": "^L"}}}
    client.put(f"/api/components/{c['id']}", json={"schema": strict})
    assert all(b["status"] == "flagged" and b["flags"][0].startswith("schema:") for b in custom_blocks(client, cid))
    bad = client.put(f"/api/components/{c['id']}", json={"code": (FIXTURES / "network.tsx").read_text()})
    assert bad.status_code == 422 and bad.json()["detail"]["gates"][-1]["gate"] == "render"
    assert client.get(f"/api/components/{c['id']}").json()["code"] == GOOD  # a failing fix is not kept
    client.put(f"/api/components/{c['id']}", json={"reviewed": True, "notes": "fine"})
    assert client.get("/api/review-components").json() == []
    assert json.loads((data_dir / "registry" / "saddle_point.json").read_text())["meta"]["reviewed"] is True


def test_rejected_component_falls_back_to_markdown_and_regenerates_with_note(client, material, proposing, data_dir):
    cid = generate(client, material, proposing)
    [c] = client.get("/api/components").json()
    client.post(f"/api/components/{c['id']}/reject")
    blocks = custom_blocks(client, cid)
    assert all(b["status"] == "flagged" and "shown as Markdown" in b["flags"][0] and b["fallback_markdown"] for b in blocks)
    assert not (data_dir / "registry" / "saddle_point.json").exists()
    assert client.post(f"/api/components/{c['id']}/regenerate", json={"note": "bigger title"}).json()["status"] == "preview"
    assert "bigger title" in [p for step, p in proposing.prompts if step == "build_component"][-1]
    assert all(b["status"] == "ok" for b in custom_blocks(client, cid))
