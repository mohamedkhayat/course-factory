import json

import pytest
from pydantic import BaseModel

from course_factory import db as dbm
from course_factory.pi_step import StepFailed, assistant_text, current_model, run_pi_step


class Reading(BaseModel):
    text: str
    readable: bool


def answers(*outs):
    it = iter(outs)
    return lambda step, prompt, files, workdir: next(it)


def traces(conn):
    return [dict(r) for r in conn.execute("SELECT step, output, error FROM traces ORDER BY id")]


@pytest.fixture
def conn(tmp_path):
    return dbm.connect(tmp_path / "t.db")


def test_bad_output_is_retried_then_accepted(conn, tmp_path):
    r = run_pi_step(conn, answers("not json", 'Sure! {"text": "x", "readable": true} done'), "read_page",
                    {"source": "a.pdf", "page": "1"}, Reading, tmp_path)
    assert r == Reading(text="x", readable=True)
    t = traces(conn)
    assert [x["error"] is None for x in t] == [False, True]


def test_gives_up_after_three_attempts_and_traces_each(conn, tmp_path):
    with pytest.raises(StepFailed):
        run_pi_step(conn, answers("{}", "{}", "{}"), "read_page", {"source": "a.pdf", "page": "1"}, Reading, tmp_path)
    assert len(traces(conn)) == 3 and all(t["error"] for t in traces(conn))


def test_prompt_comes_from_harness_with_inputs_filled(conn, tmp_path):
    seen = {}

    def backend(step, prompt, files, workdir):
        seen["prompt"] = prompt
        return '{"text": "", "readable": false}'

    run_pi_step(conn, backend, "read_page", {"source": "TD1.pdf", "page": "3"}, Reading, tmp_path)
    assert "SOURCE: TD1.pdf, page 3" in seen["prompt"] and "{{" not in seen["prompt"]


def test_assistant_text_reads_pi_json_events():
    events = [
        {"type": "message_end", "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}},
        {"type": "message_end", "message": {"role": "assistant",
                                            "content": [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": '{"ok": true}'}]}},
        {"type": "agent_settled"},
    ]
    assert assistant_text("\n".join(map(json.dumps, events))) == '{"ok": true}'


def test_backend_failure_is_traced_and_retried(conn, tmp_path):
    calls = []

    def backend(step, prompt, files, workdir):
        calls.append(1)
        if len(calls) == 1:
            raise StepFailed("pi exited 1")
        return '{"text": "x", "readable": true}'

    run_pi_step(conn, backend, "read_page", {"source": "a.pdf", "page": "1"}, Reading, tmp_path)
    assert [t["error"] for t in traces(conn)][0] == "pi exited 1"


def test_latex_backslashes_the_model_forgot_to_escape_survive(conn, tmp_path):
    raw = r'{"text": "$\frac{a}{b} + \sum x_i + \nabla f \cdot \theta \\alpha$\nNext\tcol \u00e9", "readable": true}'
    r = run_pi_step(conn, answers(raw), "read_page", {"source": "a.pdf", "page": "1"}, Reading, tmp_path)
    assert r.text == "$\\frac{a}{b} + \\sum x_i + \\nabla f \\cdot \\theta \\alpha$\nNext\tcol é"


def test_unescaped_latex_symbols_survive_too(conn, tmp_path):
    raw = r'{"text": "$\|Xw - y\|^2$, $\{1, 3\}$, a\,b \"q\" \/", "readable": true}'
    r = run_pi_step(conn, answers(raw), "read_page", {"source": "a.pdf", "page": "1"}, Reading, tmp_path)
    assert r.text == '$\\|Xw - y\\|^2$, $\\{1, 3\\}$, a\\,b "q" /'


def test_pi_backend_streams_thinking_and_output_and_returns_the_answer(tmp_path, monkeypatch):
    from course_factory import pi_step
    from course_factory.pi_step import PiBackend
    events = [{"type": "message_update", "assistantMessageEvent": {"type": "thinking_delta", "delta": "hmm"}},
              {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "{\"a\""}},
              {"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "{\"a\": 1}"}]}}]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "pi").write_text("#!/bin/sh\ncat <<'X'\n" + "\n".join(json.dumps(e) for e in events) + "\nX\n")
    (bin_dir / "pi").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    seen = []
    monkeypatch.setattr(pi_step, "report", lambda kind, delta: seen.append((kind, delta)))
    assert PiBackend()("read_page", "p", [], tmp_path) == '{"a": 1}'
    assert seen == [("thinking", "hmm"), ("output", '{"a"')]


def test_a_prompt_too_big_for_the_command_line_reaches_pi_whole(tmp_path, monkeypatch):
    from course_factory.pi_step import PiBackend
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    end = {"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}
    (bin_dir / "pi").write_text("#!/bin/sh\nwc -c > \"$0.got\"\necho '" + json.dumps(end) + "'\n")
    (bin_dir / "pi").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    prompt = "x" * 3_000_000  # Linux refuses a single argument over 128 KB
    assert PiBackend()("propose_roles", prompt, [], tmp_path) == "ok"
    assert (bin_dir / "pi.got").read_text().strip() == str(len(prompt))


def test_pi_backend_is_killed_after_its_timeout(tmp_path, monkeypatch):
    from course_factory.pi_step import PiBackend
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "pi").write_text("#!/bin/sh\nexec sleep 30\n")
    (bin_dir / "pi").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    with pytest.raises(StepFailed):
        PiBackend(timeout=1)("read_page", "p", [], tmp_path)


@pytest.mark.parametrize("raw, want", [
    ('{"a": 1} trailing words {"b": 2}', {"a": 1}),  # "Extra data" after the object
    ('```json\n{"a": [1, 2,],}\n```', {"a": [1, 2]}),
    ('{"a": "line one\nline two"}', {"a": "line one\nline two"}),  # a raw newline inside a string
    ('{"a": 1 "b": 2}', {"a": 1, "b": 2}),
    ('{a: 1}', {"a": 1}),
])
def test_model_json_is_healed_without_a_retry(raw, want):
    from course_factory.pi_step import parse_json
    assert parse_json(raw) == want


def test_each_step_runs_on_its_configured_model_and_the_trace_records_it(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("CF_MODEL_READ_PAGE", "llama-swap/nemotron3.5-bolt")
    seen = []

    def backend(step, prompt, files, workdir):
        seen.append(current_model())
        return '{"text": "x", "readable": true}'
    run_pi_step(conn, backend, "read_page", {"source": "a.pdf", "page": "1"}, Reading, tmp_path)
    assert seen == ["llama-swap/nemotron3.5-bolt"]
    assert conn.execute("SELECT model FROM traces").fetchone()[0] == "llama-swap/nemotron3.5-bolt"


def test_a_step_that_exhausts_its_retries_runs_once_more_on_the_fallback_model(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("CF_MODEL_READ_PAGE", "fast")
    monkeypatch.setenv("CF_FALLBACK_MODEL", "strong")
    run_pi_step(conn, answers("{}", "{}", "{}", '{"text": "x", "readable": true}'), "read_page", {"source": "a.pdf", "page": "1"}, Reading, tmp_path)
    assert [r[0] for r in conn.execute("SELECT model FROM traces ORDER BY id")] == ["fast", "fast", "fast", "strong"]


def test_without_a_fallback_model_a_step_gets_its_usual_attempts(conn, tmp_path):
    with pytest.raises(StepFailed):
        run_pi_step(conn, answers("{}", "{}", "{}", '{"text": "x", "readable": true}'), "read_page", {"source": "a.pdf", "page": "1"}, Reading, tmp_path)
    assert conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0] == 3
