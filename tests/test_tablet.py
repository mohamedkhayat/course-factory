import pytest
from fastapi.testclient import TestClient

from conftest import make_pdf
from test_chapters import generate

LAN = "http://192.168.1.10:8765"


@pytest.fixture
def tablet(client):
    """The same app, reached from another device on the home network."""
    with TestClient(client.app, base_url=LAN, client=("192.168.1.42", 40000)) as t:
        yield t


def pair(client, tablet):
    code = client.post("/api/pairing/start").json()["code"]
    res = tablet.post("/api/pairing/claim", json={"code": code, "label": "Galaxy Tab"})
    assert res.status_code == 200 and "cf_session" in res.cookies
    return res.json()


def test_tablet_needs_pairing_with_a_one_time_code(client, tablet):
    assert tablet.get("/api/components").status_code == 401
    assert tablet.post("/api/pairing/start").status_code == 401  # codes are started on the host only
    code = client.post("/api/pairing/start").json()["code"]
    assert tablet.post("/api/pairing/claim", json={"code": "000000" if code != "000000" else "111111"}).status_code == 400
    device = tablet.post("/api/pairing/claim", json={"code": code, "label": "Galaxy Tab"}).json()
    assert tablet.get("/api/components").status_code == 200 and tablet.get("/api/pairing/me").json()["label"] == "Galaxy Tab"
    assert tablet.post("/api/pairing/claim", json={"code": code}).status_code == 400  # one-time
    assert tablet.get("/api/pairing/devices").status_code == 403
    assert [c["label"] for c in client.get("/api/pairing/devices").json()] == ["Galaxy Tab"]
    client.post(f"/api/pairing/devices/{device['device_id']}/revoke")
    assert tablet.get("/api/components").status_code == 401


def test_guessing_revokes_the_code(client, tablet):
    code = client.post("/api/pairing/start").json()["code"]
    wrong = [f"{n:06d}" for n in range(6) if f"{n:06d}" != code][:5]
    for w in wrong:
        tablet.post("/api/pairing/claim", json={"code": w})
    assert tablet.post("/api/pairing/claim", json={"code": code}).status_code == 400


def test_cross_site_and_rebound_hosts_are_refused(client):
    assert client.post("/api/pairing/start", headers={"origin": "http://evil.example"}).status_code == 403
    with TestClient(client.app, base_url="http://evil.example:8765", client=("127.0.0.1", 1)) as rebound:
        assert rebound.get("/api/components").status_code == 403


def test_tablet_uploads_notes_as_a_new_source(client, tablet, material, model, tmp_path):
    cid = generate(client, material, model)
    pair(client, tablet)
    make_pdf(tmp_path / "mes notes.pdf", 2)
    res = tablet.post(f"/api/courses/{cid}/sources", files={"file": ("mes notes.pdf", (tmp_path / "mes notes.pdf").read_bytes(), "application/pdf")})
    assert res.status_code == 201 and res.json()["role"] == "personal notes" and res.json()["pages"] == 2
    name = res.json()["name"]
    assert name.startswith("notes/mes_notes-")
    read = [p for step, p in model.prompts if step == "read_page" and name in p]
    assert len(read) == 2  # both pages read by vision, then indexed
    assert tablet.post(f"/api/courses/{cid}/sources", files={"file": ("x.pdf", b"not a pdf", "application/pdf")}).status_code == 422
