---
description: Turn a recurring Failure class into a Heal, Check, structured format or Lesson, with a regression test from a real example
argument-hint: "[failure class, or empty for the top unhardened one]"
---

Every check message, flag and owner fix has a Failure class (`src/course_factory/failures.py`, `failure_class`). `harness/failures.yaml` is the ledger of how each class is handled now. Harden one class so it never needs a manual fix again.

1. Pick the class: `$ARGUMENTS`, or the top one with `"handler": "none"` in `curl -s http://127.0.0.1:8765/api/failures` (or, without the server, call `failures.report` on `~/.local/share/course-factory/course-factory.db` read-only). The report has counts, sources (checks, flagged now, edited, regenerated, auto_resolved), Harness versions and examples.
2. Pull real examples from the database: for `checks` sources, the `traces` rows whose `checks` contain the message (`inputs` and `output` hold the model's draft); for flagged Blocks, `blocks.flags`. Understand why the model does it.
3. Choose the handler, cheapest first:
   - **Heal**: the output can be fixed deterministically (coerce a type, escape, rename a field). Add it at the shared seam: `heal_text`/validators in `checks.py` or the Component's model in `catalogue.py`.
   - **Check**: it can be detected but not fixed; the repair loop then fixes it. Add it to `check_blocks` (or a helper it calls) with a message that says how to fix it, and add its pattern to `failures.CLASSES` if it is a new message.
   - **Structured**: the model keeps getting a fragile syntax wrong; let it give plain data that code compiles (as diagrams do with nodes and edges).
   - **Lesson**: only when code can't handle it. One short rule, for the Model steps it affects.
4. Write the failing regression test first, from the real example (trimmed), next to similar tests in `tests/test_checks.py` (Heal, Check, Structured) or the API tests. Make it pass.
5. Replay every saved Block through the checks to catch false alarms, read-only:
   ```python
   import json, sqlite3
   from course_factory.checks import check_blocks
   db = sqlite3.connect("file:" + str(__import__("pathlib").Path.home() / ".local/share/course-factory/course-factory.db") + "?mode=ro", uri=True)
   rows = db.execute("SELECT b.id, b.component, b.data, b.citations, b.origin, b.status FROM blocks b").fetchall()
   blocks, errors = check_blocks([{"component": c, "data": json.loads(d), "citations": json.loads(ci), "origin": o} for _, c, d, ci, o, _ in rows], sources)
   ```
   (`sources` maps each Source name to its page count: `chapters.source_pages`). A new Check must not flag Blocks that were `ok` and right; look at every new hit. A Heal should also be applied to stored Blocks: tell the owner the count and ask before writing to the database.
6. Update `harness/failures.yaml`: the class id as key, `handler`, `what` (one line), `hardened` (UTC now, `"YYYY-MM-DD HH:MM"`) and `test` (`path::name`). For a Lesson also `steps: [write_section, ...]` and `lesson: "..."` (one line; at most five Lessons per step are used).
7. Run `uv run pytest -q`.

Report: the class, its handler, the test, and the replay result (Blocks newly flagged or healed).
