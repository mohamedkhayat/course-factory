You are turning a university TP (practical session) into a guided coding Lab in Python, run in a Jupyter kernel with numpy, pandas, matplotlib, scipy, sympy and scikit-learn, offline. Data files are in the folder data/.

Language: {{language}}

Split the TP into small ordered Steps. Each Step has:
- statement: what to do (Markdown, $LaTeX$), in the TP's words;
- starter: code the learner starts from (names to fill in, `pass` or `None` placeholders);
- solution: a correct reference solution that runs after the previous Steps' solutions;
- check: hidden Python `assert` statements, run after the learner's code in the same namespace, each with a helpful message (assert cond, "message"). Check values and behaviour, never plots, never printed output;
- hints: 1 to 3 hints, from gentle to specific, in English;
- wrong: 1 to 3 plausible wrong versions of the solution (typical student mistakes). The check must reject each of them, and the starter too.

Inside JSON strings, escape every backslash: write "\\frac", not "\frac".
Answer with only this JSON object:
{"title": "...", "intro": "...", "chapters": ["<chapter title>"], "steps": [{"statement": "...", "starter": "...", "solution": "...", "check": "...", "hints": ["..."], "wrong": ["..."]}]}

Course Chapters: {{chapters}}
Data files: {{data_files}}

The TP:
LAB SOURCE:{{lab_source}}
