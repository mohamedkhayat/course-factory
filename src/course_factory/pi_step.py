"""The one seam every model call goes through (ADR 0001): prompt from the Harness, validate, write a Trace."""

import hashlib
import json
import re
import os
import sqlite3
import subprocess
import tempfile
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


# LaTeX commands starting with a JSON escape letter (b f n r t u): an unescaped \frac would silently read as form feed + "rac"
LATEX_WORDS = set("""backslash bar begin beta big bigcap bigcup bigg bigl bigr binom bmatrix boldsymbol bot bullet
    forall frac frown nabla ne neg neq newline ngeq nleq nmid nolimits not notin nu
    rangle rbrace rceil rfloor rho right rightarrow rm rvert tan tanh tau text textbf textit textrm tfrac theta therefore
    tilde times to top triangle underbrace underline uparrow upsilon""".split())
LATEX_RE = re.compile(r"(?<!\\)((?:\\\\)*)\\(?!u[0-9a-fA-F]{4})([A-Za-z]+)")


def escape_latex(text: str) -> str:
    """Doubles the backslash of LaTeX commands the model left unescaped inside JSON strings; real escapes stay."""
    def fix(m: re.Match) -> str:
        pairs, word = m.group(1), m.group(2)
        latex = word[0] not in "bfnrtu" or word in LATEX_WORDS
        return f"{pairs}\\\\{word}" if latex else m.group(0)
    return BAD_ESCAPE_RE.sub(r"\1\\\\", LATEX_RE.sub(fix, text))


# a lone backslash before anything JSON cannot escape (\| \{ \, in LaTeX) is always a forgotten double backslash
BAD_ESCAPE_RE = re.compile(r'(?<!\\)((?:\\\\)*)\\(?=[^"\\/bfnrtu])')


def parse_json(text: str) -> object:
    text = escape_latex(text)
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
    watched = None if live else course_id  # background generation shows on the Run screen
    try:
        for attempt in range(1, ATTEMPTS + 1):
            raw, start = None, time.monotonic()
            if watched is not None:
                ACTIVITY[watched] = {"step": step, "attempt": attempt, "started": time.time(), "thinking": "", "output": "",
                                       "inputs": {k: v for k, v in inputs.items() if isinstance(v, str) and len(v) <= 200}}
                _now.course_id = watched
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
    finally:
        if watched is not None:
            ACTIVITY.pop(watched, None)
            _now.course_id = None


ACTIVITY: dict[int, dict] = {}  # course id -> the background model step running now, with the tail of its thinking and output
ACTIVITY_TAIL = 6000
_now = threading.local()


def report(kind: str, delta: str) -> None:
    """A backend streams what the model is thinking ("thinking") or writing ("output") into this thread's step."""
    cid = getattr(_now, "course_id", None)
    a = ACTIVITY.get(cid) if cid is not None else None
    if a is not None:
        a[kind] = (a[kind] + delta)[-ACTIVITY_TAIL:]


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

    def __init__(self, model: str = os.environ.get("CF_MODEL", "llama-swap/ninfer-qwen3.8-27b:medium"), timeout: int = 900):
        self.model, self.timeout = model, timeout

    def _cmd(self, prompt, files):
        return ["pi", "-p", "--mode", "json", "--no-session", "--no-extensions", "--no-skills",
                "--no-context-files", "--no-tools", "--model", self.model, "--", *[f"@{f}" for f in files]]

    def __call__(self, step, prompt, files, workdir):
        lines = []
        for line, d in self._events(prompt, files, workdir):  # streamed, so the Run screen can watch the model think
            lines.append(line)
            if d.get("type") in ("thinking_delta", "text_delta"):
                report("thinking" if d["type"] == "thinking_delta" else "output", d.get("delta", ""))
        return assistant_text("".join(lines))

    def stream(self, step, prompt, files, workdir) -> Iterator[str]:
        for _, d in self._events(prompt, files, workdir):
            if d.get("type") == "text_delta":
                yield d.get("delta", "")

    def _events(self, prompt, files, workdir) -> Iterator[tuple[str, dict]]:
        """pi's JSON event lines, each with its assistant message event ({} for other events). Killed after the timeout."""
        workdir.mkdir(parents=True, exist_ok=True)
        stdin = tempfile.TemporaryFile("w+")  # on stdin, not argv: Linux caps one argument at 128 KB
        stdin.write(prompt)
        stdin.seek(0)
        with stdin, subprocess.Popen(self._cmd(prompt, files), cwd=workdir, stdin=stdin, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True) as proc:
            timer = threading.Timer(self.timeout, proc.kill)
            timer.start()
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    yield line, (ev.get("assistantMessageEvent") or {}) if ev.get("type") == "message_update" else {}
                code = proc.wait()
            finally:
                timer.cancel()
            if code != 0:
                raise StepFailed(f"pi exited {code}: {proc.stderr.read()[-500:] if proc.stderr else ''}")


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
