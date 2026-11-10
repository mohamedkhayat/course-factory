# Progress — 2026-11-10

## Done
- #20 work (Components, per-step models in the UI, cram mode, Question Types, refresh, Failure classes/harden loop, one-file HTML export) is in this commit; `uv run pytest -q` passes (204).
- Fixes this session:
  - `delete_course` also deletes `question_types` (it failed with a FOREIGN KEY error before). Test in `tests/test_cram.py`.
  - The model sometimes sends array/object arguments to `cf_return_result` as JSON strings. `prepareArguments` in `pi_step.py` now parses them. Test in `tests/test_pi_step.py`; the class is logged in `harness/failures.yaml`.
- Course 5 (Advanced BD, cram mode, the correct 3 exams) is generated, reviewed by hand (about 80 Block fixes in chapters 17–21), rendered clean and published. Its run is `done`.
- The mlops course is exported to `~/Downloads/mlops.html`.

## Left
- Course 5's exam date is the placeholder 2026-12-08. The user must set the real date.
- About 21% of exam points (Hadoop, MongoDB, Hive/Sqoop, HBase, Big Data impact) have no source notes, so they have no Chapters.
- Course 2 is still waiting at the `chapter_review` gate. It was not touched.
- The self-check tool was skipped (cost).
- The Block fixes were checked by reading, not by running PySpark.
- Point values for the same exam question differ between some Blocks (e.g. 1.5 vs 3 pts for the SQL question).
- Many Block fixes were the same failure classes: a DataFrame `.map`, `filter("x" > n)`, `textFileStream` said to read existing files, a wrong window-multiple rule, made-up format names. None of these are hardened into Checks yet.

## Next step
Run `/harden` on the recurring Spark failure classes listed above, starting with "PySpark DataFrame has no `.map`" (a Check that flags `\b\w+\.map\(` on a DataFrame read via `spark.read`). Add a regression test from Block 1276's original text.
