---
description: Fix the flagged Blocks the local model couldn't auto-resolve (the Review Queue), then harden their Failure class
---

course-factory must be running (`uv run course-factory`, on http://127.0.0.1:8765). The app never calls Claude; you work its Review Queue from outside.

1. `curl -s http://127.0.0.1:8765/api/review-blocks` lists the queued Blocks: `id`, `course_id`, `chapter`, `section`, `component`, `data`, `citations`, `flags` (why it is flagged), `classes` (their Failure classes), `previous` (the Block before auto-resolve, if it ran) and `pages` (the text of the Section's source pages).
2. For each Block, read the flags and the cited pages, then fix the Block's data so it is right and grounded in its pages. `src/course_factory/catalogue.py` has each Component's fields; math is LaTeX inside `$…$`.
3. Send the fix. It goes through the same checks as generation and is kept only if it passes; a 422 reply lists the errors:
   `curl -s -X PUT http://127.0.0.1:8765/api/courses/<course_id>/blocks/<id> -H 'content-type: application/json' -d @fix.json`
   with `fix.json` like `{"data": {...}}`. A fixed Block leaves the queue.
   - If the flag is wrong (the Block is fine), use `curl -s -X POST .../blocks/<id>/approve` instead.
   - If the source page itself has a typo, keep the right content and say so in the data (a `callout` or the field's text) rather than copying the typo.
4. Then make the fix permanent. Group the Blocks you fixed by Failure class and run `/harden <class>` for any class you saw more than once, or that code could clearly catch.

Report one line per Block (what you changed, or why it was fine) and the classes you hardened.
