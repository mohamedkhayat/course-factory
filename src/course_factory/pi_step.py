"""The one seam every model call goes through (ADR 0001): prompt from the Harness, validate, write a Trace."""

import errno
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ValidationError

HARNESS_DIR = Path(os.environ.get("CF_HARNESS", Path(__file__).resolve().parents[2] / "harness"))
ATTEMPTS = 3
DEFAULT_MODEL = "llama-swap/ninfer-qwen3.8-27b:medium"
MODEL_LANES = max(1, int(os.environ.get("CF_MODEL_CONCURRENCY", "2")))


class Backend(Protocol):
    def __call__(self, step: str, prompt: str, files: list[Path], workdir: Path) -> str: ...


class StepFailed(Exception):
    pass


class QueueTimeout(Exception):
    pass


QUEUE_WAIT = 600.0  # seconds a step waits for a lane before it retries
QUEUE_RETRIES = 6


class Gatekeeper:
    """Bound model concurrency; live work takes a free lane ahead of waiting generation."""

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


GATE = Gatekeeper(MODEL_LANES)


def call_backend(backend: Backend, step: str, prompt: str, files: list[Path], workdir: Path, live: bool,
                 output_schema: dict | None = None) -> str:
    for _ in range(QUEUE_RETRIES):
        try:
            with GATE.lane(live):
                structured = getattr(backend, "structured", None)
                if output_schema is not None and structured is not None:
                    return structured(step, prompt, files, workdir, output_schema)
                return backend(step, prompt, files, workdir)
        except QueueTimeout:
            continue
    raise StepFailed(f"{step}: no lane after {QUEUE_RETRIES} waits")


def model_for(step: str, attempt: int = 1) -> str:
    """The model a step runs on: CF_MODEL_<STEP>, else CF_MODEL; one extra attempt after the retries goes to CF_FALLBACK_MODEL."""
    if attempt > ATTEMPTS and os.environ.get("CF_FALLBACK_MODEL"):
        return os.environ["CF_FALLBACK_MODEL"]
    return os.environ.get(f"CF_MODEL_{step.upper()}") or os.environ.get("CF_MODEL") or DEFAULT_MODEL


def current_model() -> str | None:
    """The model run_pi_step picked for this thread's running attempt."""
    return getattr(_now, "model", None)


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
    return re.sub(r"\{\{\w+\}\}", "", prompt)  # an optional input left out renders empty


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


def _extract_json(text: str) -> str:
    """Return the first balanced JSON object/array, ignoring braces in strings."""
    in_string = escaped = False
    start = None
    stack: list[str] = []
    pairs = {"}": "{", "]": "["}
    for i, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"' and start is not None:
            in_string = True
        elif char in "{[":
            if start is None:
                start = i
            stack.append(char)
        elif char in "}]" and stack:
            if stack[-1] != pairs[char]:
                continue
            stack.pop()
            if not stack and start is not None:
                return text[start : i + 1]
    return text[start:] if start is not None else text


def _escape_controls_in_strings(text: str) -> str:
    out, in_string, escaped = [], False, False
    for char in text:
        if in_string and ord(char) < 0x20:
            out.append({"\n": r"\n", "\r": r"\r", "\t": r"\t"}.get(char, f"\\u{ord(char):04x}"))
            continue
        out.append(char)
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
    return "".join(out)


def _remove_trailing_commas(text: str) -> str:
    out, in_string, escaped = [], False, False
    for i, char in enumerate(text):
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            out.append(char)
        elif char == ",":
            j = i + 1
            while j < len(text) and text[j].isspace():
                j += 1
            next_non_space = text[j] if j < len(text) else ""
            if next_non_space not in "}]":
                out.append(char)
        else:
            out.append(char)
    return "".join(out)


def _insert_missing_comma(text: str, error: json.JSONDecodeError) -> str | None:
    if error.msg != "Expecting ',' delimiter" or error.pos >= len(text):
        return None
    before = text[: error.pos].rstrip()
    after = text[error.pos :].lstrip()
    if not before or not after or after[0] not in '"{[-0123456789tfn':
        return None
    if before[-1] not in '"}]0123456789eE':
        return None
    return before + ", " + after


def _quote_unquoted_key(text: str, error: json.JSONDecodeError) -> str | None:
    if error.msg != "Expecting property name enclosed in double quotes":
        return None
    match = re.match(r"[A-Za-z_][A-Za-z0-9_-]*", text[error.pos :])
    if not match:
        return None
    end = error.pos + match.end()
    colon = end
    while colon < len(text) and text[colon].isspace():
        colon += 1
    if colon == len(text) or text[colon] != ":":
        return None
    return text[: error.pos] + json.dumps(match.group()) + text[end:]


def parse_json(text: str) -> object:
    """Parse model JSON, applying only syntax repairs that preserve its data."""
    text = escape_latex(text).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I).strip()
    candidate = _extract_json(text)
    candidate = _remove_trailing_commas(_escape_controls_in_strings(candidate))
    last_error = json.JSONDecodeError("unrepairable", candidate, 0)
    for _ in range(4):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as error:
            last_error = error
            fixed = _insert_missing_comma(candidate, error) or _quote_unquoted_key(candidate, error)
            if fixed is None or fixed == candidate:
                raise error
            candidate = fixed
    raise last_error


def run_pi_step[T: BaseModel](
    db: sqlite3.Connection, backend: Backend, step: str, inputs: dict, schema: type[T],
    workdir: Path, files: tuple[Path, ...] = (), course_id: int | None = None, live: bool = False,
) -> T:
    version, base_prompt = harness_version(), render_prompt(step, inputs)
    prompt, output_schema = base_prompt, schema.model_json_schema()
    error = "no attempt"
    watched = None if live else course_id  # background generation shows on the Run screen
    activity_id = uuid4().hex
    try:
        for attempt in range(1, ATTEMPTS + 1 + bool(os.environ.get("CF_FALLBACK_MODEL"))):
            raw, start = None, time.monotonic()
            _now.model = model_for(step, attempt)
            if watched is not None:
                with _activity_lock:
                    ACTIVITY.setdefault(watched, {})[activity_id] = {
                        "id": activity_id, "step": step, "attempt": attempt, "started": time.time(),
                        "thinking": "", "output": "",
                        "inputs": {k: v for k, v in inputs.items() if isinstance(v, str) and len(v) <= 200},
                    }
                _now.course_id = watched
                _now.activity_id = activity_id
            try:
                raw = call_backend(backend, step, prompt, list(files), workdir, live, output_schema)
                result = schema.model_validate(parse_json(raw))
            except (ValidationError, json.JSONDecodeError, StepFailed, subprocess.TimeoutExpired, OSError) as e:
                error = str(e)[:2000]
                _trace(db, course_id, step, version, inputs, files, raw, error, start)
                if isinstance(e, OSError) and e.errno == errno.E2BIG:
                    break
                excerpt = (raw or "")[-3000:]
                prompt = (base_prompt + "\n\nRETRY FEEDBACK: Your previous response was rejected. "
                          f"Fix this error: {error}\nReturn the complete corrected result.\n"
                          f"Previous response ending (for reference):\n{excerpt}")
                continue
            _trace(db, course_id, step, version, inputs, files, result.model_dump_json(), None, start)
            return result
        raise StepFailed(f"{step}: {error}")
    finally:
        if watched is not None:
            with _activity_lock:
                entries = ACTIVITY.get(watched, {})
                entries.pop(activity_id, None)
                if not entries:
                    ACTIVITY.pop(watched, None)
            _now.course_id = None
            _now.activity_id = None
        _now.model = None


ACTIVITY: dict[int, dict[str, dict]] = {}  # course id -> concurrent background model steps
ACTIVITY_TAIL = 6000
_now = threading.local()
_activity_lock = threading.Lock()


def activity(course_id: int) -> dict | None:
    """The newest active model step for the Run screen."""
    with _activity_lock:
        entries = ACTIVITY.get(course_id, {})
        current = max(entries.values(), key=lambda a: a["started"], default=None)
        return dict(current) if current else None


def report(kind: str, delta: str) -> None:
    """A backend streams what the model is thinking ("thinking") or writing ("output") into this thread's step."""
    cid = getattr(_now, "course_id", None)
    activity_id = getattr(_now, "activity_id", None)
    with _activity_lock:
        a = ACTIVITY.get(cid, {}).get(activity_id) if cid is not None and activity_id else None
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
        "INSERT INTO traces (course_id, step, harness_version, inputs, output, error, duration_ms, model) VALUES (?,?,?,?,?,?,?,?)",
        (course_id, step, version, json.dumps({**inputs, "files": [str(f) for f in files]}, ensure_ascii=False), output, error,
         int((time.monotonic() - start) * 1000), current_model()),
    ).lastrowid


class PiBackend:
    """Runs one `pi -p --mode json` subprocess per step on llama-swap, on the model run_pi_step picked (model_for)."""

    def __init__(self, timeout: int = 900):
        self.timeout = timeout

    def _cmd(self, model, files, extension: Path | None = None):
        cmd = ["pi", "-p", "--mode", "json", "--no-session", "--no-skills", "--no-context-files",
               "--model", model]
        if extension:
            cmd += ["--no-extensions", "--no-builtin-tools", "--no-mcp", "--extension", str(extension),
                    "--tools", "cf_return_result"]
        else:
            cmd += ["--no-extensions", "--no-tools"]
        return [*cmd, "--", *[f"@{f}" for f in files]]

    def __call__(self, step, prompt, files, workdir):
        lines = []
        for line, d in self._events(step, prompt, files, workdir):  # streamed, so the Run screen can watch the model think
            lines.append(line)
            if d.get("type") in ("thinking_delta", "text_delta"):
                report("thinking" if d["type"] == "thinking_delta" else "output", d.get("delta", ""))
        return assistant_text("".join(lines))

    def structured(self, step, prompt, files, workdir, schema):
        lines = []
        for line, event in self._events(step, prompt, files, workdir, schema):
            lines.append(line)
            if event.get("type") in ("thinking_delta", "text_delta"):
                report("thinking" if event["type"] == "thinking_delta" else "output", event.get("delta", ""))
        return assistant_text("".join(lines))

    def stream(self, step, prompt, files, workdir) -> Iterator[str]:
        for _, d in self._events(step, prompt, files, workdir):
            if d.get("type") == "text_delta":
                yield d.get("delta", "")

    def _events(self, step, prompt, files, workdir, output_schema: dict | None = None) -> Iterator[tuple[str, dict]]:
        """pi's JSON event lines, each with its assistant message event ({} for other events). Killed after the timeout."""
        workdir.mkdir(parents=True, exist_ok=True)
        model = current_model() or model_for(step)  # live streams (tutor) don't go through run_pi_step
        temp = tempfile.TemporaryDirectory(prefix="course-factory-pi-") if output_schema else None
        try:
            env = os.environ.copy()
            extension = None
            if output_schema and temp:
                root = Path(temp.name)
                agent_dir = root / "agent"
                agent_dir.mkdir()
                self._strict_model_config(model, agent_dir)
                schema_path = root / "schema.json"
                schema_path.write_text(json.dumps(output_schema, ensure_ascii=False))
                extension = root / "structured-output.mjs"
                extension.write_text(STRUCTURED_OUTPUT_EXTENSION)
                env["PI_CODING_AGENT_DIR"] = str(agent_dir)
                env["CF_OUTPUT_SCHEMA"] = str(schema_path)
            stdin = tempfile.TemporaryFile("w+")  # on stdin, not argv: Linux caps one argument at 128 KB
            stdin.write(prompt)
            stdin.seek(0)
            with stdin, subprocess.Popen(self._cmd(model, files, extension), cwd=workdir, stdin=stdin,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env) as proc:
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
        finally:
            if temp:
                temp.cleanup()

    def _strict_model_config(self, model: str, agent_dir: Path) -> None:
        """Give the confirmed Qwen endpoint's strict tool support to this Pi subprocess only."""
        source_dir = Path(os.environ.get("PI_CODING_AGENT_DIR", Path.home() / ".pi" / "agent"))
        source = source_dir / "models.json"
        config = json.loads(source.read_text()) if source.exists() else {"providers": {}}
        if "qwen3.8-27b" in model.lower():
            provider_id, model_id = model.split("/", 1)
            model_id = model_id.split(":", 1)[0]
            provider = config.get("providers", {}).get(provider_id)
            if provider:
                provider.setdefault("compat", {})["supportsStrictMode"] = True
                for entry in provider.get("models", []):
                    if entry.get("id") == model_id:
                        entry.setdefault("compat", {})["supportsStrictMode"] = True
        (agent_dir / "models.json").write_text(json.dumps(config, ensure_ascii=False))


def assistant_text(jsonl: str) -> str:
    text = ""
    for line in jsonl.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = ev.get("message") or {}
        if ev.get("type") == "message_end" and msg.get("role") == "assistant":
            content = msg.get("content", [])
            calls = [p for p in content if p.get("type") == "toolCall" and p.get("name") == "cf_return_result"]
            if calls:
                text = json.dumps(calls[-1].get("arguments", {}), ensure_ascii=False)
            else:
                text = "".join(p.get("text", "") for p in content if p.get("type") == "text")
    return text


STRUCTURED_OUTPUT_EXTENSION = '''
import { readFileSync } from "node:fs";

export default function (pi) {
  const schema = JSON.parse(readFileSync(process.env.CF_OUTPUT_SCHEMA, "utf8"));
  pi.registerTool({
    name: "cf_return_result",
    label: "Return structured result",
    description: "Return the complete result matching the supplied schema. Call once as the final action.",
    promptSnippet: "Return the requested result through cf_return_result",
    promptGuidelines: ["Call cf_return_result exactly once with the complete result; do not answer in prose."],
    parameters: schema,
    // Use strict sampling where this schema fits Pi's strict subset. Generic Block data
    // falls back to normal function arguments, which are still returned as JSON.
    constrainedSampling: { type: "json_schema", strict: "prefer" },
    async execute(_id, params) {
      return { content: [{ type: "text", text: "Result accepted." }], details: {}, terminate: true };
    },
  });
}
'''
