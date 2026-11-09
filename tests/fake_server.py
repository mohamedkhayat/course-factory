"""The app on the fake model, seeded with one generated, published Course: for UI work and the Playwright smoke tests.

    uv run python tests/fake_server.py [port] [data dir] [--slow]

--slow: after seeding, reading a page takes ~8 s and streams thinking and output, to see the Run screen at work.
"""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import uvicorn  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from conftest import FakeModel, FakeSearch, make_pdf  # noqa: E402
from course_factory.app import create_app  # noqa: E402
from course_factory.kernels import LocalLauncher  # noqa: E402
from course_factory.pi_step import report  # noqa: E402
from test_chapters import generate  # noqa: E402
from test_components import GOOD, PROPOSAL  # noqa: E402


def seed(client, model, root: Path) -> int:
    folder = root / "optimisation"
    folder.mkdir()
    for name, pages in [("cours.pdf", 2), ("TD1.pdf", 1), ("TD1_corrige.pdf", 1), ("examen_2024.pdf", 2),
                        ("examen_2024_corrige.pdf", 1), ("TP1.pdf", 1)]:
        make_pdf(folder / name, pages)
    (folder / "data.csv").write_text("x,y\n1,2\n")
    write = model.handlers["write_section"]
    model.handlers["write_section"] = lambda prompt, files: {
        **write(prompt, files), "proposals": [PROPOSAL],
        "blocks": write(prompt, files)["blocks"] + [{"component": "saddle_point", "data": {"title": "Point selle"}, "origin": "model_added"}]}
    model.handlers["build_component"] = lambda prompt, files: {"code": GOOD}
    cid = generate(client, folder, model)
    for ch in client.get(f"/api/courses/{cid}/outline").json()["chapters"]:
        client.post(f"/api/courses/{cid}/chapters/{ch['id']}/publish")
    return cid


def slow_reading(prompt, files):
    for word in ("La page commence par la Définition 2.1 (fonction convexe). ", "Je transcris l'énoncé en LaTeX, ",
                 "puis l'exemple $f(x) = \\|x\\|^2$ et la figure des lignes de niveau. ") * 3:
        report("thinking", word)
        time.sleep(0.4)
    text = "**Définition 2.1** Une fonction $f$ est convexe si $f(\\lambda x + (1-\\lambda) y) \\le \\lambda f(x) + (1-\\lambda) f(y)$."
    for i in range(0, len(text), 12):
        report("output", text[i:i + 12])
        time.sleep(0.15)
    return {"text": text, "readable": True}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--slow"]
    port = int(args[0]) if args else 8766
    root = Path(args[1]) if len(args) > 1 else Path(tempfile.mkdtemp(prefix="cf-fake-"))
    model = FakeModel()
    app = create_app(root / "data", model, FakeSearch(), labs_launcher=lambda cid: LocalLauncher())
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1)) as c:
        print("seeded course", seed(c, model, root), "in", root, flush=True)
    if "--slow" in sys.argv:
        model.handlers["read_page"] = slow_reading
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
