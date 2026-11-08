import json
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from course_factory.app import create_app


def make_pdf(path: Path, pages: int) -> None:
    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(595, 842)
    pdf.save(str(path))


class FakeModel:
    """Stands in for pi + Qwen behind run_pi_step: answers per step name from canned handlers."""

    def __init__(self):
        self.calls: list[tuple[str, list[Path]]] = []
        self.handlers = {
            "read_page": lambda prompt, files: {"text": f"page text of {files[0].name}", "readable": True},
            "propose_roles": self._roles,
        }

    def _roles(self, prompt, files):
        roles = {"TD1.pdf": ("exercise sheet", "TD1_corrige.pdf"), "TD1_corrige.pdf": ("correction", None)}
        names = json.loads(prompt.split("SOURCES:", 1)[1])
        return {"sources": [{"name": s["name"], "role": roles.get(s["name"], ("course notes", None))[0],
                             "paired_with": roles.get(s["name"], (None, None))[1]} for s in names]}

    def __call__(self, step, prompt, files, workdir):
        self.calls.append((step, files))
        out = self.handlers[step](prompt, files)
        return out if isinstance(out, str) else json.dumps(out)


@pytest.fixture
def material(tmp_path):
    folder = tmp_path / "optimisation"
    folder.mkdir()
    make_pdf(folder / "cours.pdf", 2)
    make_pdf(folder / "TD1.pdf", 1)
    make_pdf(folder / "TD1_corrige.pdf", 1)
    (folder / "data.csv").write_text("x,y\n1,2\n")
    return folder


@pytest.fixture
def model():
    return FakeModel()


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def client(data_dir, model):
    with TestClient(create_app(data_dir, model)) as c:
        yield c
