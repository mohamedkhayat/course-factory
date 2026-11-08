import json

import pytest
from pydantic import BaseModel

from course_factory import db as dbm
from course_factory.pi_step import StepFailed, assistant_text, run_pi_step


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
