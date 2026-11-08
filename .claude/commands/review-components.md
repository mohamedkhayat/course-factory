---
description: Review the Components the local model made (the Review Queue), fix them, mark them reviewed
---

course-factory must be running (`uv run course-factory`, on http://127.0.0.1:8765). The app never calls Claude; you work its Review Queue from outside.

1. `curl -s http://127.0.0.1:8765/api/review-components` lists live, unreviewed model-made Components: name, description, JSON `schema` of the Block data, `samples`, `code` (one .tsx file built from `harness/component_template.tsx`), gate results, and the real `blocks` that use it.
2. For each one, review it like a PR:
   - Does it render the data well and accessibly (semantic elements, labels, contrast, keyboard)? Does it fit the Catalogue's look?
   - Is the schema right for the Blocks that use it? Would an existing Catalogue Component (`src/course_factory/catalogue.py`) do the job instead?
   - Only `react` may be imported; no network, storage or globals.
3. To fix it, send a reviewer edit. New code is re-gated (strict tsc, import allowlist, esbuild, sandboxed render) and kept only if it passes. A new schema must fit the samples and re-validates every Block, flagging the ones that no longer fit:
   `curl -s -X PUT http://127.0.0.1:8765/api/components/<id> -H 'content-type: application/json' -d @edit.json`
   with `edit.json` like `{"code": "<whole file>", "schema": {...}, "notes": "what you changed and why"}`. A 422 reply carries the gate errors.
4. When it's good, mark it: `{"reviewed": true, "notes": "..."}`. This also updates its shadcn registry item (`<data dir>/registry/<name>.json`, `meta.reviewed`).
5. If it should not exist, tell the owner. Rejecting it is their call, made from the app.

Report one line per Component: what you changed, or why it's fine.
