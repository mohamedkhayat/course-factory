# course-factory

<p>
  <img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white">
  <img alt="LangGraph" src="https://img.shields.io/badge/pipeline-LangGraph-1C3C3C">
  <img alt="React 19" src="https://img.shields.io/badge/UI-React%2019-61DAFB?logo=react&logoColor=black">
  <img alt="Local models" src="https://img.shields.io/badge/models-local%20(llama--swap)-6f42c1">
</p>

**Turns a folder of university material (lecture notes, exercise sheets, labs, past exams) into an interactive course, written by local models on your own GPU.** Every Block of the course cites the page it came from, every model output is checked by plain code before you see it, and the course is built around how the exam actually asks its questions.

## How a Generation Run flows

```mermaid
flowchart LR
    A["Folder of PDFs"] --> B["Read every page<br/>text, formulas, figures"]
    B --> C["Propose Roles<br/>notes · exercises · labs · past exams"]
    C --> G1{{"Gate: check<br/>what was found"}}
    G1 --> D["Propose the outline<br/>Chapters · Sections · Concepts"]
    D --> G2{{"Gate: fix<br/>the outline"}}
    G2 --> E["Rebuild past papers<br/>sort Questions into types"]
    E --> F["Plan each Chapter<br/>then write its Sections"]
    F --> H["Check · repair · judge grounding"]
    H --> I["Mock exams · Labs"]
    I --> G3{{"Gate: review<br/>the Chapters"}}
```

The Run is a LangGraph graph with one thread per Course; the three Approval Gates are interrupts, so a Run survives a restart and resumes from its last finished step. Every model call goes through one seam (`pi_step.run_pi_step`): prompt from the Harness, structured output validated against a schema, and a Trace written with inputs, output, checks, model and duration. See [ADR 0001](docs/adr/0001-langgraph-outside-pi-inside.md).

## What a course is made of

A Section is an ordered list of **Blocks**, each one a typed Component with its own schema, checks and React renderer:

| Kind | Components |
|---|---|
| Explaining | `prose`, `intuition`, `theorem_box`, `key_formula`, `algorithm`, `callout`, `misconception`, `recap` |
| Showing | `worked_example`, `derivation`, `diagram`, `kind_diagram`, `step_diagram`, `table`, `figure`, `plot`, `surface_plot`, `explorer`, `iteration_table`, `optimizer_animation`, `stepped_animation`, `video`, `code`, `terminal` |
| Practising | `quiz`, `fill_blanks`, `exercise`, `code_exercise`, `explain_back` |

A `kind_diagram` is given as plain data that code draws, and a `video` Block is a template filled with parameters: the model never writes Manim code. The model can also propose a new Component (schema, samples, a React implementation) when none fits; it is gated before it joins the Catalogue.

## Learning design, enforced by code

The rules come from the evidence summarised in [docs/research/learning-design.md](docs/research/learning-design.md) and [docs/research/sequencing.md](docs/research/sequencing.md), and are held by plain Python rather than by trusting the prompt:

- **Taught before asked.** Each Section declares the Concepts it teaches, each Concept in exactly one Section. A practice Block may test only Concepts already taught; one that names a later Concept is flagged.
- **Overview, then detail.** A Chapter plan opens with the big picture and what each Section adds. A Section opens by orienting the learner, and a formal statement comes after a concrete case.
- **A practice ramp.** Objectives carry a level (remember, understand, apply, analyse) and go from low to high; practice goes worked example, faded, independent, exam-style.
- **Explanation outweighs practice.** A plan with more practice than its objectives need is rejected, and a Section that asks more than it explains is reported.
- **Nothing skipped.** Readable course-notes pages cited by no Section are attached to the nearest one.
- **Visuals that carry information.** A visual is planned only for a relation that has a shape (process, hierarchy, comparison, cycle, state, quantity) and its type must match; trivial and overloaded diagrams are caught.
- **Grounded.** A Block marked `from_source` must cite real pages and is judged against them; maths claims (derivatives, gradients, Hessians, equalities) are verified with sympy; Mermaid and KaTeX are rendered in a check before a Block is accepted.

A Block that fails goes to a repair step; what still fails is flagged for review instead of stalling the Run.

## Studying with it

- **Read**: the course, with a Chapter map, citations that open the professor's page, and a flag on every Block. The left rail lists what is in the open Section; search (`/`), keyboard shortcuts (`?`), text size, a warm-up recall of the previous Section, your own note under any Block, and a confidence rating at the end of each Section.
- **Practice**: one exercise at a time, chosen from your own results. Every quiz, gap text, code exercise and Written answer is recorded per Block; what you missed comes back first, then Blocks on weak Concepts, then what you got right once its gap (1, 3, 7, 14, 30 days) has passed, then what you have not tried. Sections are interleaved.
- **Progress**: Sections read and rated, practice tried and missed per Section, Concepts weakest first, what to work on next, and your notes.
- **Tutor**: answers from the Section's pages with citations, and can propose a new or replacement Block. "Explain differently" on any teaching Block asks for a simpler version, an example, an analogy or more depth.
- **Chat**: the tutor at Course level. Answers can contain Blocks (checked like generated ones), and a shell tool searches the Course's sources in a throwaway container with no network.
- **Listen and Videos**: a Section read aloud by a local Voice, maths turned into words by code; `video` Blocks narrated and rendered with Manim. Both run on one low-priority media lane you can pause; Voices and Manim install only from Settings.
- **Memory**: one-line facts about how you learn (your preferences, patterns found in your results), read by the tutors and by Section writing.
- **Written answers and Explain back**: write, type or photograph an answer and have it graded step by step against a marking scheme, or self-mark when no model is available. Photos are cleaned before grading: SAM 3 finds the sheet, which is cropped, flattened, evened out and turned upright. SAM 3 is loaded for each photo and freed right after, on the GPU when it has room, else on the CPU. Several pages can go in one answer, and a page sent from the phone shows on the desktop.
- **Cram**: past papers rebuilt into Questions and sorted into Question Types, a plan up to the exam date, exam technique per type, Mock exams (sat timed, continued on another device, answers kept if the connection drops), and a printable Cheat Sheet.
- **Cards**: spaced repetition (FSRS).
- **Labs**: lab sheets turned into step-by-step notebooks that run in Docker kernels, with a coach that sees your code and outputs.
- **Tablet**: pair a second device with a six-digit code. Open devices see Block changes as they happen.

## Changing a Course

- **Refresh**: after files in the Course folder change, only changed pages are read again and only the Sections citing them are rewritten. New files become Sources.
- **Regenerate a Chapter**: rewrites its Sections with the current prompts. With `?replan=true` (API only for now), it first plans its Sections again from its Sources and the files added to its folder since (slides that came later). Sections are rewritten in place, so Cards keep their history.
- **From MIT OpenCourseWare**: search OCW and import a course's files as a new Course.

## Quickstart

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node, the `pi` coding-agent CLI, and an OpenAI-compatible model server (developed against [llama-swap](https://github.com/mostlygeek/llama-swap)). Docker is only needed for Labs.

```bash
(cd web && npm ci && npm run build)
```

```bash
uv run course-factory
```

The app serves on `127.0.0.1:8765` and keeps its data in `~/.local/share/course-factory`.

### Configuration

| Variable | Meaning |
|---|---|
| `CF_MODEL` | Model for every step without its own (default `llama-swap/ninfer-qwen3.8-27b:medium`) |
| `CF_MODEL_<STEP>` | Model for one step, e.g. `CF_MODEL_JUDGE_GROUNDING` |
| `CF_FALLBACK_MODEL` | One extra attempt on this model after the retries |
| `CF_MODEL_CONCURRENCY` | Model calls at once (default 2); raise it only for a server configured for more |
| `CF_DATA`, `CF_PORT` | Data directory (default `~/.local/share/course-factory`) and port (default 8765) |
| `CF_HOST` | addresses to listen on, comma-separated: `127.0.0.1,$(tailscale ip -4)` to reach the app over Tailscale: any device on the tailnet gets in without pairing (not as the host) |

Per-step models can also be set in Settings. The model server's API key is read from the environment and is never stored in the repository.

### On a tablet

The app installs as a home-screen app (a PWA) once it is served over HTTPS. Tailscale gives it HTTPS with its own certificate:

```bash
tailscale serve --bg --https=8443 8765
```

(`--https=8443` leaves the root URL free for other apps; drop it if nothing else is served.) Open `https://<this-pc>.<tailnet>.ts.net:8443` in Chrome on the tablet, then choose Install app (or Add to Home screen) from the menu. It opens full screen. The app works without `CF_HOST` this way, because `tailscale serve` proxies to `127.0.0.1`. A plain `http://100.x.y.z:8765` link still works in a browser tab, but browsers won't install it.

The pen works in these places:
- **Notes beside the course**: the pen button in the reader opens a notebook for each Section. The tutor sees it when you ask.
- **Ink on Blocks**: write over the text. Your finger still scrolls.
- **Handwritten answers** for Exercises and Mock exams. On an Exercise, **Check as I write** marks each line ✓ or ✗ with a hint (never the answer) a few seconds after the pen stops.
- **Handwritten questions** to the tutor, attached as a page or, with **Type it up**, read into editable Markdown and LaTeX.
- **Circle to ask**: the lasso in the pen toolbar sends what you went round (words, formulas as LaTeX, or a figure) to the tutor. On a cited page, drag a box over a part to ask about it.
- **Blank-page recall**: hide the Section, write what you remember, and the tutor compares it with the Section.

### Tests

```bash
uv run pytest
```

```bash
uv run pytest -m slow
```

```bash
(cd web && npm run smoke)
```

The fast tests and the Playwright smoke tests run on a fake model, so they need no GPU; `-m slow` runs Lab kernels in real Docker. For UI work, `uv run python tests/fake_server.py` serves a seeded course on the fake model at `127.0.0.1:8766`.

### Comparing models

```bash
uv run python scripts/eval_models.py --course 1 --sections 6 llama-swap/<model-a> llama-swap/<model-b>
```

Writes the same Sections with each model on a copy of the database and prints time, failed calls, Blocks flagged, grounding verdicts and the split between teaching and practice.

## Project layout

```
src/course_factory/   the pipeline and the API
  generation.py       the Run as a LangGraph graph
  pi_step.py          the one seam every model call goes through
  outline.py          Chapters, Sections, Concepts
  lesson_plan.py      the Chapter plan and its rules
  chapters.py         writing, checking, repairing, judging Sections
  checks.py           per-Component checks
  cram.py, exams.py   Question Types, past papers, Mock exams
  refresh.py          redo only what changed in the Course folder
  tutor.py, chat.py, grading.py, labs.py, learner.py, memory.py
  scan.py             cleaning a photo of a written page (SAM 3)
  listen.py, voices.py, videos.py, media.py, media_queue.py
                      read-aloud, Voices, Videos and the media lane
harness/              one prompt per model step
web/                  the React UI (Vite, Tailwind, KaTeX, Mermaid, Plotly)
tests/                pytest on a fake model, plus the fake server
docs/                 ADRs, research, the vision after v1
CONTEXT.md            the domain vocabulary used in code and prompts
```

## Status

A single-user tool under active development. What comes after v1 is described in [docs/VISION.md](docs/VISION.md).
