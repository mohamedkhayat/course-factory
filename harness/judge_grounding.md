Check each listed Block against only the pages in its Citations. A Block is grounded when every statement, formula and number in it appears in, or follows directly from, those cited pages. Notation changes, reformatting and translation are fine.

Return one result for each input Block, preserving its integer `block` index. Do not merge results or omit a Block.
- Grounded: `grounded` true, `contradicts` false, `reason` empty.
- Goes beyond the pages (adds examples, applications, methods or remarks the pages do not give) but agrees with them: `grounded` false, `contradicts` false, `reason` names what was added.
- Contradicts the pages or contains a wrong formula, number or computation: `grounded` false, `contradicts` true, `reason` names the error and the correct value from the pages.
- The Block is right and the cited page itself has a slip (a typo or sign error in a correction, shown wrong by the page's own computation or definitions): `grounded` false, `contradicts` false, `source_error` true, `reason` names the slip and the correct value, in the material's language. Use this only when the page contradicts itself; when in doubt, use `contradicts`.

Inside JSON strings, escape every backslash: write "\\frac", not "\frac".
Answer with only this JSON object:
{"results": [{"block": 0, "grounded": true, "contradicts": false, "source_error": false, "reason": ""}]}

BLOCKS:{{blocks}}
PAGES:{{pages}}
