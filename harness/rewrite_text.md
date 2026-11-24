The learner selected a passage of a tutor's answer in the Course chat and asked for it to be rewritten.

Language: answer in the language of the text. {{language}}

The text the passage comes from (Markdown, $inline$ and $$display$$ LaTeX, citations as [<source> p.<page>]):
TEXT:{{text}}

The passage the learner selected, as it shows on screen (rendered math reads as plain symbols, so find the matching part of the text):
SELECTION:{{selection}}

Their instructions: {{note}}

The pages the answer cites, to stay grounded in:
PAGES:{{pages}}

Rewrite only that passage, following the instructions; keep every other part of the text exactly as it is. Keep the Markdown, the LaTeX and the citations' form; cite only the pages above. Write LaTeX inside $...$ with single backslashes in the text itself ($w^\star$, not $w^\\star$).

Inside JSON strings, escape every backslash: write "\\frac", not "\frac".
Answer with only this JSON object: {"text": "<the whole text, with the passage rewritten>"}
