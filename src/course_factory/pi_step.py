"""The one seam every model call goes through (ADR 0001): prompt from the Harness, validate, write a Trace."""

import hashlib
import json
import os
import sqlite3
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ValidationError

HARNESS_DIR = Path(os.environ.get("CF_HARNESS", Path(__file__).resolve().parents[2] / "harness"))
ATTEMPTS = 3


class Backend(Protocol):
    def __call__(self, step: str, prompt: str, files: list[Path], workdir: Path) -> str: ...


class StepFailed(Exception):
    pass


class QueueTimeout(Exception):
    pass


QUEUE_WAIT = 600.0  # seconds a step waits for a lane before it retries
QUEUE_RETRIES = 6


class Gatekeeper:
    """The 2 GPU lanes. Live work takes any free lane, ahead of waiting generation. Generation uses one lane
    and borrows the second only while no Live work is running or waiting."""

    def __init__(self, lanes: int = 2):
        self.lanes, self.gen, self.live, self.live_waiting = lanes, 0, 0, 0
        self.cond = threading.Condition()

    def _free(self, live: bool) -> bool:
        if self.gen + self.live >= self.lanes:
            return False
        return live or (self.live_waiting == 0 and (self.gen == 0 or self.live == 0))

    @contextmanager
    def lane(self, live: bool, wait: float | None = None):
        with self.cond:
            self.live_waiting += live
            try:
                if not self.cond.wait_for(lambda: self._free(live), timeout=QUEUE_WAIT if wait is None else wait):
                    raise QueueTimeout("no free lane")
            finally:
                self.live_waiting -= live
            if live:
                self.live += 1
            else:
                self.gen += 1
        try:
            yield
        finally:
            with self.cond:
                if live:
                    self.live -= 1
                else:
                    self.gen -= 1
                self.cond.notify_all()


GATE = Gatekeeper()


def call_backend(backend: Backend, step: str, prompt: str, files: list[Path], workdir: Path, live: bool) -> str:
    for _ in range(QUEUE_RETRIES):
        try:
            with GATE.lane(live):
                return backend(step, prompt, files, workdir)
        except QueueTimeout:
            continue
    raise StepFailed(f"{step}: no lane after {QUEUE_RETRIES} waits")


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
    workdir: Path, files: tuple[Path, ...] = (), course_id: int | None = None, live: bool = False,
) -> T:
    version, prompt = harness_version(), render_prompt(step, inputs)
    error = "no attempt"
    for _ in range(ATTEMPTS):
        raw, start = None, time.monotonic()
        try:
            raw = call_backend(backend, step, prompt, list(files), workdir, live)
            result = schema.model_validate(parse_json(raw))
        except (ValidationError, json.JSONDecodeError, StepFailed, subprocess.TimeoutExpired, OSError) as e:
            error = str(e)[:2000]
            _trace(db, course_id, step, version, inputs, files, raw, error, start)
            continue
        _trace(db, course_id, step, version, inputs, files, result.model_dump_json(), None, start)
        return result
    raise StepFailed(f"{step}: {error}")


def stream_pi_step(db: sqlite3.Connection, backend: Backend, step: str, inputs: dict, workdir: Path,
                   files: tuple[Path, ...] = (), course_id: int | None = None) -> Iterator[str]:
    """Live work with a free-text answer: yields text chunks as they arrive, then writes one Trace."""
    version, prompt, chunks, start = harness_version(), render_prompt(step, inputs), [], time.monotonic()
    stream = getattr(backend, "stream", None)
    try:
        for _ in range(QUEUE_RETRIES):
            try:
                with GATE.lane(live=True):
                    for chunk in (stream(step, prompt, list(files), workdir) if stream else [backend(step, prompt, list(files), workdir)]):
                        chunks.append(chunk)
                        yield chunk
                break
            except QueueTimeout:
                continue
        else:
            raise StepFailed(f"{step}: no lane after {QUEUE_RETRIES} waits")
    except Exception as e:
        _trace(db, course_id, step, version, inputs, files, "".join(chunks) or None, str(e)[:2000], start)
        raise
    _trace(db, course_id, step, version, inputs, files, "".join(chunks), None, start)


def record_owner_action(db: sqlite3.Connection, course_id: int, gate: str, decision: dict, action: str) -> None:
    """A Trace for what the owner did at an Approval Gate."""
    db.execute("INSERT INTO traces (course_id, step, harness_version, inputs, owner_action) VALUES (?,?,?,?,?)",
               (course_id, f"{gate}_gate", harness_version(), json.dumps(decision, ensure_ascii=False), action))


_last = threading.local()


def last_trace_id() -> int | None:
    """The Trace this thread's last model step wrote, to attach its check results to."""
    return getattr(_last, "id", None)


def attach_checks(db: sqlite3.Connection, trace_id: int | None, checks) -> None:
    """Stores what the checks found in a step's output (errors, warnings, proofs) on its Trace."""
    if trace_id is not None:
        db.execute("UPDATE traces SET checks=? WHERE id=?", (json.dumps(checks, ensure_ascii=False), trace_id))


def _trace(db, course_id, step, version, inputs, files, output, error, start):
    _last.id = db.execute(
        "INSERT INTO traces (course_id, step, harness_version, inputs, output, error, duration_ms) VALUES (?,?,?,?,?,?,?)",
        (course_id, step, version, json.dumps({**inputs, "files": [str(f) for f in files]}, ensure_ascii=False), output, error,
         int((time.monotonic() - start) * 1000)),
    ).lastrowid


class PiBackend:
    """Runs one `pi -p --mode json` subprocess per step against Qwen on llama-swap."""

    def __init__(self, model: str = "llama-swap/ninfer-qwen3.8-27b:low", timeout: int = 900):
        self.model, self.timeout = model, timeout

    def _cmd(self, prompt, files):
        return ["pi", "-p", "--mode", "json", "--no-session", "--no-extensions", "--no-skills",
                "--no-context-files", "--no-tools", "--model", self.model, "--", *[f"@{f}" for f in files], prompt]

    def __call__(self, step, prompt, files, workdir):
        out = subprocess.run(self._cmd(prompt, files), cwd=workdir, capture_output=True, text=True, timeout=self.timeout)
        if out.returncode != 0:
            raise StepFailed(f"pi exited {out.returncode}: {out.stderr[-500:]}")
        return assistant_text(out.stdout)

    def stream(self, step, prompt, files, workdir) -> Iterator[str]:
        workdir.mkdir(parents=True, exist_ok=True)
        with subprocess.Popen(self._cmd(prompt, files), cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
            assert proc.stdout is not None
            for line in proc.stdout:
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                d = ev.get("assistantMessageEvent") or {}
                if ev.get("type") == "message_update" and d.get("type") == "text_delta":
                    yield d.get("delta", "")
            if proc.wait(timeout=self.timeout) != 0:
                raise StepFailed(f"pi exited {proc.returncode}: {proc.stderr.read()[-500:] if proc.stderr else ''}")


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
