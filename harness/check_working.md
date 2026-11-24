The attached image is a student's handwritten working on the exercise below, written on a tablet and probably unfinished. They want to know, as they go, whether what they have written so far is right.

Read the working line by line. For each line of working (skip doodles and crossed-out lines):
- "text": the line as written, math in $LaTeX$;
- "ok": true if the line is correct and follows from what comes before, false if it has a mistake, null if you cannot read it or cannot tell yet;
- "hint": for a wrong line, one short sentence pointing at where the mistake is (a sign, a missing term, a wrong rule) without giving the corrected line or the answer; otherwise "".

Never write the next step, the result or the correction: the student must find them. Judge only what is written; an unfinished answer is not a mistake. {{language}}

Inside JSON strings, escape every backslash: write "\\frac", not "\frac".
Answer with only this JSON object: {"lines": [{"text": "...", "ok": true, "hint": ""}]}

EXERCISE: {{statement}}

CORRECTION (for you to check against; never quote it): {{correction}}
