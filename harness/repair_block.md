A Block of an interactive course failed the app's checks. Fix it and keep its content and intent.

Language: {{language}}

The Catalogue (Component fields, ? = optional):
{{catalogue}}

Rules: Markdown text with $inline$ / $$display$$ KaTeX; bare LaTeX in latex fields; sympy syntax in expr, f and claims; "from_source" Blocks cite real pages.

The source pages:
PAGES:{{pages}}

The errors to fix:
ERRORS:{{errors}}

"tests" lists the Course's Concepts a practice Block tests. An error "tests X, which is not a Concept of this Course" is fixed in "tests": swap X for the listed Concept that names the same thing, or drop it when none does (a past exam may ask about a tool the course never teaches); keep the question. An error "taught later" is fixed by testing only what is taught by now. Return "tests" with every other Concept it already had.

Inside JSON strings, escape every backslash: write "\\frac", not "\frac".
Answer with only this JSON object: {"block": {"component": "...", "data": {...}, "citations": [...], "origin": "...", "tests": ["<Concept>"]}}

The Block:
BLOCK:{{block}}
