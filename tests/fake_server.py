"""The app on the fake model, seeded with one generated, published Course: for UI work and the Playwright smoke tests.

    uv run python tests/fake_server.py [port] [data dir]
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import uvicorn  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from conftest import FakeModel, FakeSearch, make_pdf  # noqa: E402
from course_factory.app import create_app  # noqa: E402
from course_factory.kernels import LocalLauncher  # noqa: E402
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


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(tempfile.mkdtemp(prefix="cf-fake-"))
    model = FakeModel()
    app = create_app(root / "data", model, FakeSearch(), labs_launcher=lambda cid: LocalLauncher())
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1)) as c:
        print("seeded course", seed(c, model, root), "in", root, flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
