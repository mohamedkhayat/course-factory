# Generative components: how other tools let a model make UI safely

Research ticket #4 for course-factory. Question: when a course needs a component the library does not have, how can a local model build it, the owner preview it, and the owner approve it into the library?

## Method and confidence

Fetched this session (primary sources):
- Vercel AI SDK generative UI guide (ai-sdk.dev)
- json-render (github.com/vercel-labs/json-render)
- A2UI (a2ui.org)
- shadcn registry-item JSON reference (ui.shadcn.com)
- Sandpack getting-started docs (only partly useful)

Not verified this session. These come from memory and are marked **(memory)** below:
- CopilotKit docs (the fetch failed, DNS error)
- Claude artifacts help article (the fetch returned 404)
- Sandpack internals, esbuild-wasm, and the shadcn `shadcn add <url>` CLI behaviour

The Claude artifacts CSP note in the Section 2 table comes from the artifact runtime rules in this environment, not from the help article.

## 1. Survey

| System | How the model's output is constrained | Where code runs | Lesson for us |
|---|---|---|---|
| Vercel AI SDK generative UI | The model only calls tools. Each tool has a Zod `inputSchema`. Tool results are rendered by components written in advance (`output-available` maps to `<Weather {...output}/>`). | Components are app code, written by a developer. | The model never writes UI code, so this is the safest pattern. It does not validate outputs at runtime, which we would need to add ourselves. |
| json-render | A catalog lists each allowed component with its props schema and description. The catalog also generates the system prompt. The model emits a flat JSON spec (root id plus `elements` map). A registry maps each type to a real implementation. Dynamic values use declarative expressions (`$state`, `$cond`, `$template`). Custom functions must be registered. Output can stream through a SpecStream compiler. | Renderer in the app. | Closest match to our "content is JSON, components are code" split. The catalog is the contract the model sees. Unknown types can be rejected before rendering. |
| A2UI (Google, Apache 2.0) | Agents send declarative JSON. Clients render it with native widgets from a pre-approved catalog. The format is flat and streams well from LLMs. | Client renderer per platform (Angular, Flutter, Lit, Markdown and others). | Same idea as json-render. Its security argument is simple: data cannot inject code. Useful as a vocabulary for the "catalog" and for progressive rendering. |
| CopilotKit **(memory)** | Components are registered for agent tool calls (render-tool-call, state-driven UI) over the AG-UI protocol. | App code. | Confirms the pattern: pre-registered React renderers, model picks by name. Does not solve generating new components. |
| Claude artifacts **(memory, plus the runtime CSP in this environment)** | Generated code runs in a sandboxed iframe on a separate origin. External scripts come only from an allowlist of CDN hosts. | Browser iframe. | Sandboxing and a host allowlist are the baseline for previewing model code. The artifact runtime here already enforces this for pages we publish. |
| shadcn registry | A registry item is JSON: `name`, `type` (`registry:ui`, `registry:component`, `registry:block`, and others), `files` (each with `path` and `type`, `target` only for pages and files), `registryDependencies` (names, URLs, or GitHub refs), `dependencies` (npm, optionally pinned), `cssVars`. A URL in `registryDependencies` points to another item JSON. | Copied into the project's source tree. | Best target format for approved components. Items are plain files, so they can be reviewed in git. Fetched docs did not show a `content` field on files; the hosted build step that inlines source is something to check. |
| Sandpack **(memory)** | Bundles files in the browser, previews in an iframe, resolves npm deps through a CDN. The fetched page only covered configuration (`customSetup`, entry file, `externalResources`). | Browser. | Good preview engine, but it pulls in npm at runtime. We want a fixed set of imports, so this is more than we need. |
| esbuild-wasm **(memory)** | Transpiles and bundles TSX in the browser or in Node. | Browser or server. | Use it on the server (build step) to produce one JS bundle per candidate. The browser then only loads that bundle. |
| Props schemas | Zod (used by AI SDK tool inputs and json-render catalogs). JSON Schema can be derived from Zod for prompts and validation. **(memory)** Zod 4 ships a JSON Schema export. | n/a | One schema per component serves three roles: prompt text for the model, runtime validation of content JSON, and a test fixture. |

Common pattern across all of them: the model picks from a catalog or writes data, and code that already exists renders it. Free-form code generation only shows up in the artifact-style sandboxes, and those rely on iframe isolation plus a CSP.

## 2. What helps a ~27B local model write working React + shadcn

These are standard practices from experience **(memory, not measured here)**. Validate them on our own model before relying on them.

- **Narrow task.** Ask for one file with a fixed skeleton (imports, props type, export) and fill-in-the-middle, not "design a component". Small models do better on constrained edits.
- **Schema first.** Write the Zod props schema before the JSON. Tests and the prompt both use it.
- **Few-shot from the library.** Give 2 or 3 existing components of similar shape as examples. Pick them by the schema's shape, not by name.
- **Import allowlist.** Only the library's primitives and the shadcn components already in the repo. No new npm packages, no `fetch`, no `dangerouslySetInnerHTML`, no `window`/`document`.
- **Feedback loop.** Run `tsc --noEmit` (strict) and ESLint with restricted imports. Feed the first errors back, capped at about 3 rounds. Most failures are missing imports and wrong prop names, and the compiler messages fix those well.
- **Size cap.** For example 200 lines per component, one component per file. Reject anything larger before running the model's output through the other checks.
- **Render and look.** Render the component with its example data in a headless browser and take a screenshot. A vision model or the owner judges it. Catches blank output and overflow that the type checker misses.
- **Crash test.** Render with a few schema-generated or edge-case inputs (empty arrays, long strings) inside an error boundary.

## 3. Recommended shape

Tier 0 comes first. Before generating code, check whether the existing library can already express the need as a JSON spec. Most requests should stop here. Codegen runs only when nothing fits.

```
request (need + example data)
  -> spec: name, purpose, props Zod schema, example.json
  -> build: local model writes component.tsx from the template
       (one file, import allowlist, size cap)
  -> gate 1, automatic: parse, import allowlist, tsc strict, eslint,
       retry with errors up to 3 rounds
  -> gate 2, automatic: esbuild a single bundle on the server,
       load in a sandboxed iframe (sandbox="allow-scripts", no same-origin,
       CSP default-src 'none'), render example + crash inputs, screenshot
  -> preview to owner: rendered output, code diff, gate report, screenshot
       buttons: approve / reject / regenerate with note
  -> approve: write registry item (shadcn-format JSON + files) to the
       local library, with provenance = "local-model", reviewed = false,
       spec and gate results attached
  -> later review: Claude Code works through the queue
       provenance = local-model AND reviewed = false
       checklist: props schema matches content JSON, no network or
       unsafe APIs, accessible markup, library style, tests pass
       then set reviewed = true with reviewer and commit id
```

Specific choices:

- **Tag location.** Keep the provenance tag in course-factory's own library manifest (for example `library/manifest.json`), not only inside the shadcn-format JSON. The manifest is ours to query. The label shown in the UI is "made by local model".
- **Approved code is trusted code.** The sandboxed iframe only protects the preview. Once approved, the component is part of the app and runs without isolation. That is why the gates and the later review matter, and why the review queue is a filter on the manifest rather than a separate system.
- **Sandbox details.** The preview iframe uses an opaque origin (no `allow-same-origin`), a strict CSP, and no network access. Its only input is the bundle plus the example data via `postMessage` or `srcdoc`.
- **Build in Node, not the browser.** Use esbuild on the server to produce the candidate bundle. This keeps the browser free of npm resolution and avoids depending on a CDN.
- **Prefer a registry-item shape.** Each approved component is a folder: `registry/<name>.json`, `component.tsx`, `schema.ts`, `example.json`. This matches shadcn so the library can be reused by other tools later.

## 4. Trade-offs

- **Data-only (json-render, A2UI, AI SDK tools)** is safe and cheap, but it can only express what the catalog covers. Good as tier 0 and for most lessons.
- **Codegen (artifacts, our tier 2)** covers any component, but needs gates, a sandbox, and human review. Expensive in review time, and quality depends on the model.
- **Runtime npm (Sandpack)** is convenient but adds network and supply-chain risk. Reject for this project.
- **Sandbox only, no approval** would be faster but puts model code into the library unreviewed. Reject.

## 5. Open questions and next steps

1. Measure Qwen 3.8 27B on 10 realistic component requests (pass rate after 3 gate rounds, median lines, time). Decide the size cap from data.
2. Confirm the shadcn `content` field and whether the local registry needs a build step (`shadcn build`) before `shadcn add <url>` works.
3. Check the CopilotKit and Claude artifacts sources directly when someone has time. Those two claims are from memory.
4. Decide how the review queue is shown in the app (a list filter is enough to start).
