# Research #2: driving Qwen 3.8 on llama-swap through pi as a pipeline worker

Sources (all local, read on 2026-11-08):

- pi CLI help (`pi --help`), installed package `@earendil-works/pi-coding-agent` v1.5.0 at `/home/mohamed/.local/lib/node_modules/@earendil-works/pi-coding-agent`, docs in its `docs/` folder: `cli.md`, `cli-integration.md`, `json.md`, `rpc.md`, `sdk.md`, `security.md`, `settings.md`, `models-configuration.md`, `custom-provider.md`, `extensions.md`, `skills.md`.
- Local pi config: `~/.pi/agent/models.json` (provider `llama-swap`, secrets not printed).
- llama-swap: `~/Apps/llama-swap` (`config.yaml`, `docs/config.example.yaml`, `docs/kb/guides/routing/capacity-and-queues.md`, `internal/router/scheduler/fifo.go`).
- ninfer (the engine behind `ninfer-qwen3.8-27b`): `~/Apps/ninfer` (`src/runtime/engine/engine_core.h`, `src/serve/serve_options.cpp`, `README.md`), and the launch script `~/scripts/start_ninfer_qwen3.8-27b.sh`.
- One live test: `pi -p --mode json --no-session --model llama-swap/ninfer-qwen3.8-27b:low "reply with the word ok"` from `/tmp`. Exit 0, about 23 s wall time, empty stderr.

Not checked: the upstream GitHub repo (the local package docs were treated as the source of truth), and llama-swap's live logs for the earlier admission failure.

## 1. Modes

| Mode | Use for the pipeline? |
|---|---|
| `pi -p "<prompt>"` (print) | Only the final text on stdout. No events. Non-zero exit on an error or abort. Good for a one-shot step if you only need the answer. |
| `pi --mode json` | One invocation: a session header, then JSONL events, then exit. Best fit for a per-step worker that must stream progress. |
| `pi --mode rpc --no-session` | Long-lived child, JSON commands on stdin, responses and events on stdout. Use it if one worker should serve many steps without restarting pi. `RpcClient` (exported by the package) wraps it for Node/TS. There is no official Python client. |
| SDK (`createAgentSession`, `session.prompt()`) | In-process TypeScript only. Not usable from a Python backend without a Node bridge. |

Recommendation: `--mode json` as a subprocess per generation step. It is stateless, easy to time out and kill, and the exit code is meaningful. Switch to RPC only if process start-up cost matters.

### JSON event stream, as a Python worker needs it

- Framing: strict JSONL. Split on LF only, strip a trailing CR, and decode UTF-8 as bytes. Do not use `str.splitlines()`, which also splits on Unicode separators.
- stdout is reserved for JSONL. Diagnostics go to stderr. Read stdout continuously or the pipe can stall pi.
- Record 1 is `{"type":"session","version":3,"id":...,"cwd":...}`. RPC mode has no such header.
- Event sequence for one run: `agent_start`, `turn_start`, `message_start/end` (user), then for the assistant `message_start`, many `message_update`, `message_end`, then `turn_end`, `agent_end`, `agent_settled`.
- Live text: concatenate `assistantMessageEvent.delta` for `text_delta` (and `thinking_delta` for reasoning, which Qwen emits by default). Replace with the authoritative content on `text_end`, and with `message_end.message` when it arrives. `message_update` carries deltas only.
- Tool calls: `toolcall_start`/`toolcall_delta`/`toolcall_end` (inside `message_update`), then `tool_execution_start`, `tool_execution_update`, `tool_execution_end` (`toolCallId`, `toolName`, `result`, `isError`, `durationMs`).
- Completion: `agent_settled` means no automatic work remains (retries, compaction, queued messages). Use it, not `agent_end`, as the done signal. `agent_end.willRetry` tells you a retry is coming.
- Errors: a failed or aborted assistant message appears as an event with `stopReason` error or aborted and does not by itself give a non-zero exit. Check `message_end.message.stopReason` and `errorMessage`, plus the exit code.

Minimal driver:

```python
import json, subprocess

def run_pi_step(prompt, workdir, tools="read,grep,find,ls", thinking="low", timeout=900):
    cmd = ["pi", "-p", "--mode", "json", "--no-session", "--no-extensions", "--no-skills",
           "--no-context-files", "--tools", tools, "--thinking", thinking,
           "--model", "llama-swap/ninfer-qwen3.8-27b", "--", prompt]
    proc = subprocess.Popen(cmd, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    text, done = [], None
    for raw in proc.stdout:                      # binary, split on \n
        line = raw.rstrip(b"\r\n")
        if not line:
            continue
        ev = json.loads(line.decode("utf-8"))
        if ev["type"] == "message_update":
            d = ev["assistantMessageEvent"]
            if d["type"] == "text_delta":
                text.append(d["delta"])          # live display; replace on message_end
        elif ev["type"] == "message_end" and ev["message"]["role"] == "assistant":
            done = ev["message"]                 # authoritative
        elif ev["type"] == "agent_settled":
            break
    rc = proc.wait(timeout=timeout)
    stderr = proc.stderr.read().decode("utf-8", "replace")
    return done, rc, stderr
```

Caveats: the loop above has no timeout while reading stdout. Put it in a thread or use a watchdog that kills the process. Also, `--thinking low` still produced reasoning tokens in the live test; `--thinking off` is cheaper if the step does not need it.

## 2. Model configuration

`~/.pi/agent/models.json` defines provider `llama-swap` with `baseUrl` `http://172.17.0.1:8080/v1` (the docker bridge address; `127.0.0.1:8080` works too), `api: openai-completions`, `apiKey` (a literal key or `"$NAME"` env interpolation, or `"!command"`), and `compat` with `maxTokensField: max_tokens`, `supportsDeveloperRole: false`, `supportsStore: false`. The `ninfer-qwen3.8-27b` entry has `contextWindow: 240000` and `maxTokens: 131072`.

Environment-variable key: `apiKey: "$LLAMASWAP_API_KEY"` or `--api-key` is supported (`models-configuration.md`, `providers.md`). Keep the key out of argv (`ps` shows it); prefer the env var.

Model name for the CLI: `--model llama-swap/ninfer-qwen3.8-27b:<thinking>`, where the suffix is `off|minimal|low|medium|high|xhigh|max`.

## 3. Tool calling and structured output

- Tool calling works through the OpenAI-compatible API. ninfer returns parsed tool calls to the client and does not execute them (`ninfer/README.md`); pi executes them. The live test did not exercise tools, so reliability with Qwen 3.8 here is not measured.
- pi has no `response_format` / JSON-schema output flag. Output is free text. Two options:
  1. Ask for JSON in the prompt, then validate with `jsonschema` in Python and retry on failure. Simple, weakest guarantee.
  2. Register a custom tool whose parameters are your JSON schema (a `submit_result` tool, via an extension). The model calls it with arguments that are already structured, and pi returns them as `tool_execution_start.args`. Stronger than free text. It needs one small TypeScript extension. Note `supportsStrictMode: false` in our compat settings, so strict schema enforcement is off.

## 4. Extensions, skills, custom tools

- Extensions are TypeScript modules in `~/.pi/agent/extensions/` or `.pi/extensions/`, or `pi -e <path>` for a single run. They can `pi.registerTool()` custom tools, add commands and handle events. They run with the full permissions of the pi process.
- Skills follow the Agent Skills spec (`--skill <path>`, `--no-skills` to disable discovery).
- For a worker, disable discovery: `--no-extensions --no-skills --no-context-files --no-prompt-templates`. Unless you pass `-e`, nothing project-local runs. Project trust (`.pi/` folders in the workdir) is ignored in print/JSON mode unless `defaultProjectTrust` is `always`.

## 5. Restricting filesystem and shell

- Tool allowlist: `--tools read,grep,find,ls` (no `bash`, `edit`, `write`). `--no-builtin-tools` drops the built-ins but keeps extension tools. `--no-tools` drops everything. Built-in tools are `read`, `bash`, `edit`, `write` by default (per `pi --help`).
- pi does not sandbox paths. `read` can open any file the process user can read, and `bash` can do anything. The docs say the working folder controls discovery and default paths, not access.
- So for "no shell, read only" use the allowlist. For "no access outside the job dir" you need an OS boundary: a container (Docker, `docs/containerization.md`) or a dedicated low-privilege user with no access to the repo, `~/.pi`, or secrets. Pass the API key in env, not in a file the job can read.
- `docs/security.md`: pi does not ask before tool calls. Treat model output as untrusted.

## 6. Session handling

- `--no-session` for ephemeral jobs (course generation steps should use this). `--session-dir <dir>` to store sessions elsewhere. `--session <id|path>` or `--continue` to resume. `--fork` to branch.
- A pipeline step is usually a fresh prompt with explicit inputs, so `--no-session` is the right default. Keep the step's state in course-factory's database, not in pi sessions.

## 7. Concurrency and the "expired while waiting for admission" error

The admission chain has three layers. Each has its own limit.

1. pi: none. Each pi process is independent and sends its own requests.
2. llama-swap (`config.yaml`, `groups`): the ninfer model is in an exclusive, swapping group. Loading it unloads other models in that group. The FIFO scheduler serialises swaps and queues requests while a model loads (`capacity-and-queues.md`). Per-model `concurrencyLimit` defaults to 10 here. Requests beyond that get HTTP 429 immediately, not queued. `globalConcurrencyLimit` is 0 (off). Turning it on also returns 429, so it is not a queue.
3. ninfer (`ninfer-serve`, started by `start_ninfer_qwen3.8-27b.sh`): `--max-concurrency 2`, which gives 2 active generation lanes. Other requests wait in a pending queue. Each pending request has a deadline of `submitted + pending_timeout` (default `--pending-timeout-ms 30000`, not set in our script). When the deadline passes while the request is still pending, ninfer fails it with `QueueTimeout`, whose message is "inference request expired while waiting for admission" (`engine_core.h`, the pending-queue loop).

What this means for the failure: a generation with thinking can keep a lane busy for minutes (`max_tokens` 131072). Any request that waits more than 30 s behind busy lanes, or behind a model load (llama-swap `ttl: 300` unloads after 5 min idle, and reload takes roughly 30 to 60 s by the config's own comment), expires. Two pi jobs on one model fill both lanes. A third request, or a job that sends a second request while the first is still running, or any request that waits through a reload, times out. I did not reproduce the earlier run and did not inspect its logs, so this is the most likely mechanism from the code, not a confirmed diagnosis.

How to avoid it:

- Bound the pipeline. Run at most 2 pi jobs on `ninfer-qwen3.8-27b` at once. Simplest is one global semaphore in course-factory's worker, sized to `--max-concurrency` (2), and never more.
- Do not run other llama-swap models (flash-next, gemma, kat-coder) concurrently with the 27B. Loading them evicts it and restarts the wait.
- Raise the queue deadline if you keep parallel jobs: add `--pending-timeout-ms 600000` to `start_ninfer_qwen3.8-27b.sh`. That is a config change in `~/scripts`, so it is the user's call.
- Retry on `QueueTimeout` with backoff rather than failing the course. Note that pi's own retry (`retry.enabled`, `maxRetries` 3, `baseDelayMs` 2000 in `settings.md`) may or may not classify this error as transient. Check it with a test before relying on it. Retrying at the worker level is more predictable.
- Use `--thinking off` or `low` for structured steps to shorten lane occupancy.
- Keep the 5-minute `ttl` in mind: long gaps between steps cost a reload. Batch steps or raise `ttl` if pipelines idle.

## 8. Context window

- Per-sequence logical limit: `--max-context 240000` (ninfer). Shared KV pool: `--kv-capacity 240000`, shared across active requests and cached prefixes. The per-sequence limit is the one that matters for one prompt.
- pi's view: `contextWindow: 240000`, `maxTokens: 131072` for `ninfer-qwen3.8-27b` in `models.json`. Consistent with the server.
- `qwen3.8-flash-next` launches with `max_tokens` and `reasoning_budget_tokens` 131072. Its context size in the launch script was not read. `models.json` has a 262144 entry for some model; I did not verify which one.

## 9. Recommended integration seam

Put the seam at the generation call site, as one function in course-factory's backend, e.g. `run_pi_step(prompt, inputs, schema, workdir) -> StepResult`:

- It spawns `pi -p --mode json --no-session --no-extensions --no-skills --no-context-files --tools <allowlist> --thinking <level> --model llama-swap/ninfer-qwen3.8-27b -- <prompt>` in a fresh per-job directory, with `LLAMASWAP_API_KEY` in its environment, and runs it under a container or a low-privilege user.
- It reads stdout as LF-split JSONL, assembles the text from `message_end`, and stops at `agent_settled`. It returns `(text_or_structured_result, usage, tool events, exit code, stderr)`.
- It enforces the admission rule itself: an asyncio/threading semaphore of 2 (matching ninfer `--max-concurrency 2`) around the subprocess, plus a retry with backoff on `QueueTimeout`.
- It validates the output against the step's JSON schema and retries on failure. For strong structure, add a `submit_result` tool via a small extension and read its arguments from `tool_execution_start`.

Everything else (course model, job queue, UI) only sees `run_pi_step`. Replacing pi later means changing one function.

## Open items

- Test tool calling and the `submit_result` pattern with Qwen 3.8 on this server.
- Reproduce a `QueueTimeout` deliberately (three parallel jobs, `--pending-timeout-ms` unchanged) to confirm the mechanism in section 7.
- Confirm which llama-swap model entry owns the 262144 context in `models.json`, and the flash-next context size.
