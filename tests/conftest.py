import json
import os

os.environ.setdefault("CF_MODEL_CONCURRENCY", "1")  # serial model calls keep the fake model's call order deterministic
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from course_factory.app import create_app
from course_factory.kernels import LocalLauncher


def make_pdf(path: Path, pages: int) -> None:
    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(595, 842)
    pdf.save(str(path))


LAB = {"title": "TP1 : descente de gradient", "intro": "On implémente la descente de gradient.", "chapters": ["Méthodes de descente"],
       "steps": [
           {"statement": "Définir $f(x)=x^2$.", "starter": "def f(x):\n    pass", "solution": "def f(x):\n    return x**2",
            "check": "assert f(3) == 9, 'f(3) should be 9'", "hints": ["Use **.", "return x**2"], "wrong": ["def f(x):\n    return 2*x"]},
           {"statement": "Lire data/data.csv et poser y = somme des x + 2.", "starter": "y = None",
            "solution": "import csv\ny = sum(int(r['x']) for r in csv.DictReader(open('data/data.csv'))) + 2",
            "check": "assert True", "hints": [], "wrong": ["y = 2"]},  # too weak: repaired
           {"statement": "Impossible.", "starter": "z = None", "solution": "z = 1/0", "check": "assert z == 1", "hints": [],
            "wrong": ["z = 2"]},  # the Solution itself fails: left out
           {"statement": "Doubler y.", "starter": "w = None", "solution": "w = 2 * y", "check": "assert w == 2 * y",
            "hints": [], "wrong": ["w = y"]}]}  # proven after the dropped Step: its broken Solution must not run first


class FakeModel:
    """Stands in for pi + Qwen behind run_pi_step: answers per step name from canned handlers."""

    def __init__(self):
        self.calls: list[tuple[str, list[Path]]] = []
        self.prompts: list[tuple[str, str]] = []
        self.sandboxes: list[str | None] = []  # the files container each stream was given
        self.handlers = {
            "read_page": lambda prompt, files: {"text": f"page text of {files[0].name}", "readable": True},
            "propose_roles": self._roles,
            "propose_outline": lambda prompt, files: {"chapters": [
                {"title": "Convexité", "sections": [
                    {"title": "Ensembles convexes", "pages": [{"source": "cours.pdf", "page": 1}, {"source": "nope.pdf", "page": 1}],
                     "teaches": ["ensemble convexe"]}]},
                {"title": "Méthodes de descente", "sections": [
                    {"title": "Gradient", "pages": [{"source": "cours.pdf", "page": 2}, {"source": "cours.pdf", "page": 99}],
                     "teaches": ["gradient"]},
                    {"title": "Exercices", "pages": [{"source": "TD1.pdf", "page": 1}]}]}]},
            "write_section": self._section,
            "plan_chapter": self._plan,
            "repair_block": lambda prompt, files: {"block": json.loads(prompt.split("BLOCK:", 1)[1])},  # echoes: fixes nothing
            "lab_tutor": lambda prompt, files: f"Look at what `f` returns. ({len(files)} plots seen)",
            "tutor": lambda prompt, files: "Une fonction est « convexe » si... [cours.pdf p.1] [made_up.pdf p.2]",
            "chat": self._chat,
            "derive_scheme": lambda prompt, files: {"scheme": [{"step": "Poser le pas", "points": 1}, {"step": "Calculer", "points": 1}]},
            "read_ink": lambda prompt, files: {"text": f"$x^2$ écrit ({len(files)} image)"},
            "check_working": lambda prompt, files: {"lines": [{"text": "$x=1$", "ok": True, "hint": ""}, {"text": "$y=3$", "ok": False, "hint": "regarde le signe"}]},
            "transcribe_copy": lambda prompt, files: {"text": f"écrit à la main ({len(files)} images)"},
            "grade_answer": self._grade,
            "build_lab": lambda prompt, files: LAB,
            "build_component": lambda prompt, files: {"code": (Path(__file__).parent / "components" / "good.tsx").read_text()},
            "repair_lab_step": lambda prompt, files: {"step": {**json.loads(prompt.split("STEP:", 1)[1]),
                                                               "check": "assert y == 3, 'y should be 3'"}},
            "grade_code": lambda prompt, files: {"correct": True, "feedback": "Works.", "hint": ""},
            "judge_grounding": lambda prompt, files: {"grounded": True, "reason": ""},
            "rebuild_past_paper": lambda prompt, files: {
                "title": "Examen 2024", "duration_min": 120, "chapters": ["Convexité", "Inconnu"], "questions": [
                    {"statement": "Montrer que $f$ est convexe.", "points": 6, "model_answer": "Hessienne positive.", "chapter": "Convexité",
                     "scheme": [{"step": "Hessienne", "points": 4}, {"step": "Conclusion", "points": 2}]},
                    {"statement": "Calculer $x_1$.", "points": 14, "model_answer": "$x_1 = 0.5$", "scheme": None,
                     "chapter": "Méthodes de descente"}]},
            "classify_questions": self._classify,
            "write_mock_exam": lambda prompt, files: {
                "title": "Examen blanc " + prompt.split("Mock exam number ", 1)[1].split(" ", 1)[0], "duration_min": 90,
                "chapters": ["Méthodes de descente"], "questions": [
                    {"statement": "Appliquer le gradient.", "points": 20, "model_answer": "...", "chapter": "Méthodes de descente",
                     "scheme": [{"step": "Direction", "points": 10}, {"step": "Pas", "points": 10}]}]},
        }

    @staticmethod
    def section_of(prompt: str) -> str:
        return prompt.rsplit("SECTION: ", 1)[1].split("\n", 1)[0].strip()

    @staticmethod
    def pages_of(prompt: str) -> list[dict]:
        return json.loads(prompt.split("PAGES:", 1)[1].rsplit("\nSECTION: ", 1)[0])

    @staticmethod
    def _grade(prompt, files):
        """Full marks on the first step (claimed too high, to test clamping), nothing on the others."""
        scheme = json.loads(prompt.split("Marking scheme:\n", 1)[1].split("\n\nThe student's answer:", 1)[0])
        return {"steps": [{"step": s["step"], "awarded": 99 if i == 0 else 0, "comment": "ok" if i == 0 else "missing"}
                          for i, s in enumerate(scheme)]}

    def _section(self, prompt, files):
        page = self.pages_of(prompt)[0]
        teaches = json.loads(prompt.split("This Section teaches: ", 1)[1].split("\n", 1)[0])
        return {"blocks": [
            {"component": "prose", "origin": "model_added", "data": {"markdown": f"Cette Section présente {', '.join(teaches)}, par exemple sur $x^2$."}},
            {"component": "theorem_box", "origin": "from_source", "citations": [{"source": page["source"], "page": page["page"]}],
             "data": {"kind": "definition", "title": self.section_of(prompt), "statement": "Un ensemble est convexe si..."}},
            {"component": "quiz", "origin": "model_added", "data": {"questions": [
                {"prompt": "Convexe ?", "options": ["oui", "non"], "correct": [0], "explanation": "Par définition."}]}}]}

    @staticmethod
    def _chat(prompt, files):
        """A short answer with one cited Block on the Concept "gradient", between two paragraphs."""
        block = {"component": "theorem_box", "origin": "from_source", "citations": [{"source": "cours.pdf", "page": 2}], "tests": ["gradient"],
                 "data": {"kind": "definition", "title": "Gradient", "statement": "Le gradient pointe vers la plus forte croissance."}}
        return f"Voici l'idée [cours.pdf p.2].\n\n```block\n{json.dumps(block)}\n```\n\nEt la suite.\n"

    @staticmethod
    def _plan(prompt, files):
        """One remember objective per Section, practised by a quiz, tagged with every Question Type."""
        types = json.loads(prompt.split("(exact names): ", 1)[1].split("\n", 1)[0] or "[]")
        sections = json.loads(prompt.split("SECTIONS:", 1)[1].split("\n", 1)[0])
        return {"overview": "Ce chapitre part d'une idée simple et complète, puis chaque Section y ajoute une pièce : "
                            + ", puis ".join(s["title"] for s in sections) + ".",
                "sections": [{"title": s["title"], "objectives": [{"id": "o1", "level": "remember", "text": "State it.",
                                                                   "concepts": [], "exam_types": types}],
                              "misconceptions": [{"id": "m1", "text": "Confuses it with its converse."}],
                              "practice": [{"objective": "o1", "kind": "retrieval", "component": "quiz"}]} for s in sections]}

    @staticmethod
    def _classify(prompt, files):
        """One Question Type per Chapter named in the questions."""
        qs = json.loads(prompt.split("QUESTIONS:", 1)[1])
        types: dict = {}
        for q in qs:
            types.setdefault(q["chapter"], []).append(q["id"])
        return {"types": [{"name": f"Type {ch}", "trigger": f"asks about {ch}", "chapter": ch, "template": "1. Poser\n2. Conclure",
                           "questions": ids} for ch, ids in types.items()]}

    def _roles(self, prompt, files):
        roles = {"TD1.pdf": ("exercise sheet", "TD1_corrige.pdf"), "TD1_corrige.pdf": ("correction", None),
                 "examen_2024.pdf": ("past exam", "examen_2024_corrige.pdf"), "examen_2024_corrige.pdf": ("correction", None),
                 "TP1.pdf": ("lab", None), "TP2.ipynb": ("lab", None), "data.csv": ("data", None)}
        names = json.loads(prompt.split("SOURCES:", 1)[1])
        return {"sources": [{"name": s["name"], "role": roles.get(s["name"], ("course notes", None))[0],
                             "paired_with": roles.get(s["name"], (None, None))[1]} for s in names]}

    def __call__(self, step, prompt, files, workdir):
        self.calls.append((step, files))
        self.prompts.append((step, prompt))
        out = self.handlers[step](prompt, files)
        return out if isinstance(out, str) else json.dumps(out)


    @staticmethod
    def models():
        return [{"id": "llama-swap/big", "thinking": True}, {"id": "llama-swap/small", "thinking": False}]

    def stream(self, step, prompt, files, workdir, stop=None, sandbox=None, on_tool=None):
        self.sandboxes.append(sandbox)
        if sandbox and on_tool:  # a model with the Course files shell runs one command before it answers
            on_tool({"command": "ls -R /course/text"})
            yield ""
        text = self(step, prompt, files, workdir)
        for i in range(0, len(text), 12):
            yield text[i : i + 12]


class FakeMedia:
    """Stands in for the local engines: Voices speak silence as long as the words, Dictation hears a canned sentence. Nothing downloads."""

    def __init__(self):
        self.gpu = False
        self.have = {"kokoro"}
        self.spoken: list[tuple[str, str, str, str | None]] = []  # (text, language, voice, speaker) of every speak call
        self.heard: list[tuple[Path, list[str], bool]] = []  # (recording, languages, file existed) of every transcribe call
        self.transcript = "bonjour, la convexité"
        self.installs: list[str] = []
        self.video = False  # video rendering (Manim) installed
        self.renders: list[tuple[dict, int, Path]] = []  # (scene spec, narration WAV (channels, sample width, rate), output file) of every render call
        self.render_error: str | None = None
        self.retimes: list[tuple] = []  # (picture, old scene lengths, new ones, output) of every picture fitted to another Voice

    def speak(self, text, language, voice, speaker=None):
        import io
        import wave
        from course_factory.media import Speech
        self.spoken.append((text, language, voice, speaker))
        d = max(0.4, 0.15 * len(text.split()))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\0\0" * int(8000 * d))
        return Speech(buf.getvalue(), d, [(0.0, d)])

    def transcribe(self, audio, languages):
        self.heard.append((audio, languages, audio.exists()))
        return self.transcript

    def installed(self):
        return set(self.have)

    def install(self, voice, log):
        self.installs.append(voice)
        log("fake install")
        self.have.add(voice)

    def remove(self, voice):
        self.have.discard(voice)

    def video_installed(self):
        return self.video

    def install_video(self, log):
        log("fake install")
        self.video = True

    def remove_video(self):
        self.video = False

    def render(self, spec, audio, out):
        import wave
        with wave.open(str(audio)) as w:
            self.renders.append((spec, w.getparams()[:3], out))
        if self.render_error:
            raise RuntimeError(self.render_error)
        out.write_bytes(b"fake mp4")
        out.with_suffix(".png").write_bytes(b"fake png")
        out.with_suffix(".picture").write_bytes(b"fake picture")
        out.with_suffix(".holds.json").write_text(json.dumps([sum(spec["durations"][:i]) + 1.0 for i in range(len(spec["durations"]))]))

    def retime(self, picture, old, new, audio, out):
        self.retimes.append((picture, old, new, out))
        out.write_bytes(b"fake mp4")
        out.with_suffix(".png").write_bytes(b"fake png")


class FakeSearch:
    """Bag-of-words hashing embedder and word-overlap reranker: deterministic, no model download."""

    dim = 32

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for w in t.lower().split():
                v[hash(w) % self.dim] += 1.0
            n = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([x / n for x in v])
        return out

    def rerank(self, query, texts):
        q = set(query.lower().split())
        return [float(len(q & set(t.lower().split()))) for t in texts]


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


@pytest.fixture(autouse=True)
def stub_sections(monkeypatch):
    """Test Sections are a Block or two of stub text; the placeholder guard has its own test."""
    from course_factory import chapters
    monkeypatch.setattr(chapters, "MIN_SECTION_WORDS", 0)


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def media():
    return FakeMedia()


@pytest.fixture
def client(data_dir, model, media):
    with TestClient(create_app(data_dir, model, FakeSearch(), labs_launcher=lambda cid: LocalLauncher(), media=media),
                    base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000)) as c:
        yield c
