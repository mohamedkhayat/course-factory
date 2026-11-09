Check each listed Block against only the pages in its Citations. A Block is grounded when every source-derived statement, formula and number appears in, or follows directly from, those cited pages. Notation changes and reformatting are fine. Model-added explanations may extend the source, but must not be presented as source facts.

Return one result for each input Block, preserving its integer `block` index. Do not merge results or omit a Block. If a Block has no unsupported source claim, set `grounded` to true and `reason` to an empty string. Otherwise set it false and name the unsupported claim briefly.

Inside JSON strings, escape every backslash: write "\\frac", not "\frac".
Answer with only this JSON object:
{"results": [{"block": 0, "grounded": true, "reason": ""}], "grounded": null, "reason": ""}

BLOCKS:{{blocks}}
PAGES:{{pages}}
