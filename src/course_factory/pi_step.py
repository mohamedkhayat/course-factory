"""The one seam every model call goes through (ADR 0001): prompt from the Harness, validate, write a Trace."""

import hashlib
import json
import os
import sqlite3
import subprocess
import threading
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ValidationError

HARNESS_DIR = Path(os.environ.get("CF_HARNESS", Path(__file__).resolve().parents[2] / "harness"))
ATTEMPTS = 3


class Backend(Protocol):
    def __call__(self, step: str, prompt: str, files: list[Path], workdir: Path) -> str: ...


class StepFailed(Exception):
    pass


def harness_version() -> str:
    h = hashlib.sha256()
    for f in sorted(HARNESS_DIR.rglob("*")):
        if f.is_file():
            h.update(f.relative_to(HARNESS_DIR).as_posix().encode() + b"\0" + f.read_bytes())
    return h.hexdigest()[:12]


def render_prompt(step: str, inputs: dict) -> str:
    prompt = (HARNESS_DIR / f"{step}.md").read_text()
    for key, value in inputs.items():
        prompt = prompt.replace("{{" + key + "}}", value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
    return prompt


def parse_json(text: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end < start:
            raise
        return json.loads(text[start : end + 1])


def run_pi_step[T: BaseModel](
    db: sqlite3.Connection, backend: Backend, step: str, inputs: dict, schema: type[T],
    workdir: Path, files: list[Path] = [], course_id: int | None = None,
) -> T:
    version, prompt = harness_version(), render_prompt(step, inputs)
    error = "no attempt"
    for _ in range(ATTEMPTS):
        raw = None
        try:
            raw = backend(step, prompt, files, workdir)
            result = schema.model_validate(parse_json(raw))
        except (ValidationError, json.JSONDecodeError) as e:
            error = str(e)[:2000]
            _trace(db, course_id, step, version, inputs, files, raw, error)
            continue
        _trace(db, course_id, step, version, inputs, files, result.model_dump_json(), None)
        return result
    raise StepFailed(f"{step}: {error}")


def _trace(db, course_id, step, version, inputs, files, output, error):
    db.execute(
        "INSERT INTO traces (course_id, step, harness_version, inputs, output, error) VALUES (?,?,?,?,?,?)",
        (course_id, step, version, json.dumps({**inputs, "files": [str(f) for f in files]}, ensure_ascii=False), output, error),
    )


class PiBackend:
    """Runs one `pi -p --mode json` subprocess per step against Qwen on llama-swap."""

    def __init__(self, model: str = "llama-swap/ninfer-qwen3.8-27b:low", lanes: int = 2, timeout: int = 900):
        self.model, self.timeout = model, timeout
        self.lanes = threading.Semaphore(lanes)

    def __call__(self, step, prompt, files, workdir):
        cmd = ["pi", "-p", "--mode", "json", "--no-session", "--no-extensions", "--no-skills",
               "--no-context-files", "--no-tools", "--model", self.model, "--", *[f"@{f}" for f in files], prompt]
        # shortcut: no QueueTimeout retry or Live-work priority yet; add when tutor/grading land.
        with self.lanes:
            out = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=self.timeout)
        if out.returncode != 0:
            raise StepFailed(f"pi exited {out.returncode}: {out.stderr[-500:]}")
        return assistant_text(out.stdout)


def assistant_text(jsonl: str) -> str:
    text = ""
    for line in jsonl.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = ev.get("message") or {}
        if ev.get("type") == "message_end" and msg.get("role") == "assistant":
            text = "".join(p.get("text", "") for p in msg.get("content", []) if p.get("type") == "text")
    return text
