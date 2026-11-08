You are writing one Section of an interactive course, built from the professor's own pages.

Goal: {{goal}} ("cram": exam-focused, dense, worked examples and exam-style exercises first; "deep": build understanding step by step).
Chapter priority: {{priority}} ("focus": thorough, more exercises; "light": short summary).
Language: {{language}}

Write the Section as an ordered list of Blocks. Each Block uses exactly one Component from this Catalogue, with data matching its fields (? = optional):
{{catalogue}}

Rules:
- Text fields are Markdown with $inline$ and $$display$$ LaTeX (KaTeX). Fields named latex are bare LaTeX.
- Mermaid diagrams must be valid Mermaid syntax.
- Expressions in expr, f and claims use sympy syntax: x**2, exp(x), sqrt(x), x1*x2.
- Add claims to Worked Examples, Exercises and Key Formulas whenever a derivative, gradient, Hessian or equality can be checked. The app verifies them.
- For an Iteration Table give only the method, f, vars, x0, step and iterations. The app computes the rows.
- origin is "from_source" when the Block restates the pages; it then needs citations [{"source","page","quote"?}] to the pages below. Use "model_added" for your own explanations, intuitions and extra exercises.
- Use prose only when no other Component fits.

Answer with only this JSON object:
{"blocks": [{"component": "<name>", "data": {...}, "citations": [{"source": "...", "page": 1, "quote": "..."}], "origin": "from_source"}]}

Chapter: {{chapter}}
The source pages for this Section:
PAGES:{{pages}}
SECTION: {{section}}
