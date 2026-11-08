# Atlas porting research — what to copy from ML Mastery Atlas

Scope: read-only study of `~/uni` (the ML Mastery Atlas Learning Application, strictly
untouched) to decide which pieces course-factory should copy, reuse as prior art, or skip.
Source material: `~/uni/app` (12 Python modules, ~2,900 lines), `~/uni/app/tests/test_phase1.py`
(17 tests), `~/uni/docs/adr/` (31 ADRs), `~/uni/docs/LEARNING-APPLICATION-SPEC.md`,
`~/uni/CONTEXT.md` (glossary), `~/uni/IMPLEMENTATION-STATUS.md`, and
`/home/mohamed/scripts/ocr.py` (946-line standalone OCR CLI, env-driven).

No secrets were read or are printed here. The llama-swap configuration file was not opened;
all facts about llama-swap come from Atlas's HTTP client code and its spec.

## TL;DR

Atlas is an implementation of a well-reasoned spec (spec + 17 ADRs + full glossary). Its
**HTTP/SQLite boundary, pairing, vault mechanics, inference-coordinator contract, and
page-bounded extraction** are production-quality, tested, and cleanly separable. Its
**OCW course discovery** is tightly bound to MIT OCW's package layout and course-factory's
source model (books, blogs, forums, YouTube) does not match. Its **retrieval layer is ADRs,
not code** — port the decisions, not the (nonexistent) implementation.

## Verdict table

| # | Candidate | What it does | Test coverage | Coupling to Atlas | Verdict |
|---|-----------|--------------|---------------|-------------------|---------|
| 1 | **llama-swap adapter** (`app/inference.py::LlamaSwapAdapter` + `config.py` fields) | Server-side HTTP client for llama-swap ops endpoints (`/health`, `/running`, `/v1/models`, `POST /api/models/unload[/<model>]`, optional explicit-load hook). Per-profile model-alias map; honest lazy-load reporting (`verified=False` when no explicit load endpoint exists, instead of faking residency); credentials and endpoint paths stay server-side, browser receives reachability + model IDs only. | Unit-tested with an injected fake `opener`: lazy-load honesty, response-shape normalization (`_ids` handles dict/list payloads), health aggregation. No test against a live llama-swap. | **Near zero.** Pure function of `(settings, opener)`; imports no Atlas domain. Only the default alias values name the owner's local models. | **Port code.** ~180 lines, self-contained, and it is exactly what course-factory needs for pi/Qwen 3.8 via llama-swap. Rebrand the `ML_MASTERY_*` settings names and alias map. |
| 2 | **Inference coordinator** (`InferenceCoordinator` + `InferenceWorker` + `job_records`/`inference_runtime`) | Durable priority queue of GPU jobs over four mutually exclusive Inference Profiles (Assistance / Extraction / Retrieval / Speech). Persistent transition records, visible cooperative transitions, interactive-Assistance confirmation rule (`PermissionError` without `confirm`), return-profile support, page/batch checkpoints, cancel/retry, one running job at a time. Workers are handler-registered by design; the default worker refuses to pretend a model ran. | Unit-tested with fakes: profile exclusivity, confirmation rule, return-profile restore, worker lifecycle evidence, no-registered-handler error. Real GPU handlers are intentionally not implemented in Atlas. | **Low–medium.** Mechanism is generic; depends only on two tables (migrations 1+4) and `Settings`. Profile names reflect Atlas workloads. | **Port code.** One GPU must serve chat (Assistance), OCR, and RAG embedding/reranking; this is the coordination design VISION.md §1 raises and the ADRs (0021, 0024) pin down. Reuse the confirmation + visible-transition rules verbatim. |
| 3 | **Page extraction / OCR** (`app/extraction.py`, migration 3, plus `/home/mohamed/scripts/ocr.py`) | One durable `page_extractions` row per PDF page. Native-first: `pdftotext` (≥40 visible chars ⇒ done, no model call); image-heavy pages rendered with `pdftoppm` (180 dpi, 64 MiB cap), then vision OCR by dynamically importing `ocr.py` and calling `document_to_markdown(..., pages_per_request=1)` with a content-hash cache. Resumable (first failed/incomplete page), per-page error isolation, additive human corrections that never replace originals. `ocr.py` itself: standalone Unlimited-OCR CLI (OpenAI-compatible endpoint, SQLite hash cache, native-text hybrid, CLI args). | Native path unit-tested with mocks (two-page resume, statuses, completion). The vision-OCR branch is **not** unit-tested (it needs the real script + model). `ocr.py` has no tests in any repo. | **Medium.** The service is a clean seam `(settings, connection, vault)` but is wired to `note_revisions`, `job_records`, and the Extraction profile. `ocr.py` is fully standalone (env-driven). | **Port code** for the service pattern (page-bounded durable extraction, native-first, resume) — course-factory's v2 book/PDF ingestion needs exactly this. **Do not copy `ocr.py`**: it is a shared machine tool; call it through the same importlib seam Atlas uses. |
| 4 | **Vault / uploads** (`app/vault.py` + migration 2 note tables + `/api/notes/*`) | App-managed imports directory; streaming chunked copy with SHA-256 + 256 MiB cap; content-addressed vault storage (`notes/<2>/<sha>/<safe-name>`); exact-duplicate suppression; title-overlap **proposals** requiring human confirmation (Notes Inbox); accept/reject with curriculum association; path confinement (import root, vault root) so arbitrary host paths never leak over HTTP. | Solid: streaming, dedup, inbox review (accept requires a primary association), outside-root rejection, managed-import retention, plus the extraction-resume test exercises the vault. | **Medium.** Tables and the `samsung-pdf`/`markdown` kinds are Atlas-domain; association fields reference Atlas milestone/quest/concept IDs. The mechanics (confinement, streaming, dedup, content addressing, inbox-with-proposals) are generic. | **Port code** for the mechanics; **port the idea** for the inbox/proposal pattern, retargeted at course-factory entities (uploaded handwritten answers/photos → inbox → associate to course/lesson). Skip Samsung-specific bits. |
| 5 | **OCW course discovery / transcripts** (`app/courses.py` + migration 5 + `/courses/` bridge) | Discovers local MIT OCW packages by layout markers (`static_resources/` + `sitemap.xml`), parses `<video>/<track>` identity from page HTML, hashes files incrementally, writes only metadata rows (packages stay immutable). Batched (32/call) **WebVTT parsing** with warning capture, bounded semantic cue segments, exact-terms transcript search returning local `?t=` URLs + remote fallback, and a runtime **bridge** injected into served vendor HTML that seeks the existing player, highlights the cue, and adds a return link. | Good: VTT timing/segments, discovery/prepare/search/bridge on a fixture package, package-immutability assertion, malformed-source resilience. | **High** for discovery (MIT OCW package layout, course roots); **low** for `parse_vtt`/`semantic_segments`/cue-segment tables and the bridge idea. | **Split.** Port code for `parse_vtt` + `semantic_segments` + cue/segment schema (YouTube transcripts are VTT/SRT — directly reusable). **Skip** the OCW discovery and the OCW-specific bridge: course-factory's sources are books/blogs/forums/YouTube (YouTube supports `?t=` natively; a bridge only matters for self-hosted media packages, a v2+ concern). |
| 6 | **Retrieval ADRs** (0019, 0020, 0022, 0023, 0025, 0026, 0027, 0028, 0029) | The decision set for local RAG: retrieval-first assistance (elicits an attempt before answering); page/section as the citation-able **Retrieval Unit**; FTS5 lexical + exact batched vector search over rebuildable storage + rerank (no vector DB until profiling proves the need); transparent contextual boosts with explanations; official timed tracks preferred over generated ASR; incremental preparation (no eager whole-library indexing); visible separation of retrieved evidence from model knowledge. | **None — no retrieval code exists in Atlas yet.** This candidate is nine ADRs and one spec section, not code. | Zero code coupling; some boost/filter details name Atlas's Lane/Quest/Milestone. | **Port idea.** These are precisely the architectural decisions course-factory's RAG + tutor + citation-first design needs, and the non-goals (no whole-document prompting, no unbounded context, no premature ANN service) are cheap insurance. |
| 7 | **Pairing for tablet access** (`app/pairing.py` + migration 2 pairing tables + `server.py` auth) | Six-digit one-time code (SHA-256 stored, 10-min TTL) → single-use claim issues a bearer token (SHA-256 stored); last-seen tracking; revocation. Non-loopback requests require the paired cookie/bearer; loopback is the trusted host; health stays public for diagnostics. | Unit-tested (single-use code, revocation, claim flow). Socket-level LAN smoke was deferred in Atlas (sandbox had no loopback). | **Low.** 70 lines + two tables + a `_require_auth` middleware pattern; coupling is the cookie name and server wiring. | **Port code.** VISION.md §8 already proposes "the tablet pairs with the host machine the way Atlas pairs devices." Small, tested, generic; rebrand the cookie name and run one real-LAN smoke after porting. |
| 8 | **Migrations / DB layer** (`app/database.py`, plus `server.py::Application` state handling) | `connect()` (foreign keys on, busy timeout, `Row` factory, cross-thread flag with documented rationale); ordered versioned `MIGRATIONS` tuple applied inside `BEGIN IMMEDIATE` and recorded in `schema_migrations`; `transaction()` contextmanager; seeded single-row `learner_state` snapshot with **revision-conflict** updates and preview/apply import. Pure stdlib, no ORM. | Idempotent-migration test (all 5 migrations, count check); every service test exercises the schema. | **Mechanism: zero. Table contents: high** — the 5 migrations encode Atlas's domain (learner state, notes, extractions, inference runtime, courses). | **Port code** for the mechanism (~80 lines of `migrate`/`transaction`/`connect`); **skip** the Atlas tables and `state.py`'s domain (it validates against Atlas quest IDs and carries Atlas's XP/badge/gate model). Keep the idea: versioned snapshot + revision conflicts + preview/apply import. |

### Cross-cutting notes

- **Server framework.** The spec proposed FastAPI; the Phase-1 spike shipped a dependency-light
  stdlib `ThreadingHTTPServer` (~590 lines, one `RLock` serializing mutations). course-factory
  is planned on FastAPI — port the *route responsibilities* (spec §14 API seams) and auth
  middleware pattern, not the handler boilerplate.
- **Learner state (`state.py`, `learner_state`).** Tightly coupled to Atlas's gamified state
  contract (XP, quests, gates, badges, `focusLane` default, `ml-mastery-state` format). Not a
  candidate for porting beyond the revision-conflict/preview-apply pattern above.
- **What Atlas has NOT built** (per `IMPLEMENTATION-STATUS.md`): multimodal retrieval, grounded
  assistance, ASR/timestamp-map generation, media download management, backups. Those are
  spec + ADR only — course-factory is not inheriting a gap, only an untested design.

## Glossary

From `~/uni/CONTEXT.md` (a 90-term glossary with explicit "Avoid" lists). For course-factory:

**Adopt** (the concepts are what course-factory is also building, and the terms are free):

| Term | Why |
|------|-----|
| **Inference Profile** / **Inference Coordinator** | One GPU, mutually exclusive model sets, visible cooperative transitions — course-factory runs chat + OCR + RAG on the same GPU (VISION §1). |
| **Grounded Assistance** | Tutor answers must separate retrieved, cited claims from model knowledge. Core to the citation-first design. |
| **Retrieval Unit** | The smallest citable item (page / headed section / timed cue group). Matches "citations back to an exact place" (VISION §2). |
| **Page Extraction Record** / **OCR Provider (contract)** | Page-bounded, provenance-preserving extraction — needed for book PDFs. |
| **Resource Preparation** | The discover → download → extract → index → verify pipeline vocabulary, resumable per resource. |
| **Timed Transcript Track** / **Video Citation** / **Timestamp Map** | YouTube source handling in v2 needs official-timing-first, method+confidence provenance, and time-deep-links. |
| **Paired Client** | VISION §8 proposes exactly this for tablet access. |
| **Private Learning Vault** | Private originals (handwritten answers, photos) vs shareable course content — same boundary course-factory will need, especially post-multi-user. |
| **Source Citation** + the four provenance labels (Your Notes / Course Material / Generated / Model Knowledge) | Adopt the labels; they make "made by local model" tagging (VISION §5) precise. |
| **Recovery Manifest** / lean backups | Adopt when multi-user/backup arrives (VISION §1); keep routine backups free of rebuildable bulk data. |

**Avoid / rename** (Atlas-owned or colliding with course-factory's own vocabulary):

| Atlas term | Collision | Recommendation |
|------------|-----------|----------------|
| **Course** | The biggest one. In Atlas it means a *downloaded external course package* (`course_sources`, `CoursePreparationService`, `/courses/`); in course-factory it is the *generated* product entity. | Keep `Course` for course-factory's generated entity. When porting any course-package code, rename to **Source Package** / **Media Package** (tables `media_sources`, `media_resources`). |
| **Application Lab** | Atlas: bounded coding *quest* inside a math course (ADR 0007/0013). course-factory v1 already has its own "labs" (math/science plots; later ML labs). | Keep course-factory's **Lab**. Never import "Application Lab" as a second meaning of lab. |
| **Quest** / **XP** / **Mastery Gate** / **Mastery Badge** / **Repair Quest** | Atlas's gamified work unit and reward model (ADR 0010: no pace pressure). course-factory has its own lesson/exercise/quiz/grading model. | Do not adopt the gamification vocabulary; it would overload course-factory's own terms. |
| **Milestone** / **Lane** / **Milestone Page** / **Lane Page** | Atlas curriculum topology (3 Lanes, 17 Milestones) referenced throughout the note-association schema. | Use course-factory's own structure terms (modules/sections); reserve Milestone/Lane for Atlas. |
| **Study Note** / **Note Source** / **Note Revision** / **Notes Inbox** / **Study Timer** / **Study Session** / **Open Study Session** | Atlas's learner-state and timer domain (`state.py`, schema v2). | Port the *inbox-with-proposals* idea under a course-factory name (e.g., Upload Inbox); don't drag the study-timer/timer-reconciliation machine in. |
| **Learning Application** | Atlas's product name (CONTEXT.md, spec §1). | course-factory stays course-factory. |
| **Static Export** | Atlas's optional generated-site artifact. | course-factory's UI is not a static export; avoid reusing the term. |
| **Prepared-Library Search** | Atlas's search product (filters by Lane/Course/Milestone). | Port the ranking idea (lexical + semantic + explained contextual boosts), rename the surface to fit course-factory (e.g., course-aware search). |
| **Course Page Bridge** | OCW-specific runtime injection into vendor HTML. | Skip the term and mechanism unless course-factory self-hosts media packages (v2+); YouTube needs native `?t=` only. |

## Suggested porting order (if/when executed)

1. `database.py` mechanism + `pairing.py` (+ tables) — small, tested, unblocks everything.
2. `LlamaSwapAdapter` + coordinator contract (profiles/queue/transitions) — the GPU boundary.
3. Vault mechanics + upload routes; retarget inbox proposals at course-factory entities.
4. Extraction service (page-bounded, native-first) wired to the shared `ocr.py`.
5. `parse_vtt`/`semantic_segments` + cue/segment schema for YouTube transcripts.
6. Retrieval ADRs as the design charter for the RAG + tutor work (code written fresh in FastAPI).
