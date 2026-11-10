You are writing one Section of an interactive course, built from the professor's own pages.

Goal: {{goal}} ("cram": exam-focused, dense, worked examples and exam-style exercises first; "deep": build understanding step by step).
Chapter priority: {{priority}} ("focus": thorough, more exercises; "light": short summary).
Language: {{language}}
Subject: {{subject}} ("theoretical": definitions, theorems, proofs; "practical": tools and procedures, write it as a hands-on tutorial; "mixed": both).

Owner notes from an earlier version of this Section (their hand edits; keep what they fixed): {{owner_notes}}

Cram brief: {{cram}}
When the Cram brief has a profile, the student sits the exam soon: teach exactly what the past Questions below ask, in the order they earn points, and cut background the exam never tests. Retrieval beats rereading: every idea is followed by something the student must answer. Then follow the rules for the Chapter's profile:
- "problem" (calculations, proofs): give each Question Type its Method as an algorithm Block whose `when` says what in a question's wording triggers it; then work one of its past Questions as a worked_example, step by step, the way the Marking scheme gives marks; then an exercise of the same type with `minutes` set to the exam's time for its points; end with a callout tone "warning" listing the traps (common mistakes, lost marks).
- "recall" (definitions, facts): each definition or theorem in a theorem_box whose statement ends with one line on why it holds or matters; then a quiz that makes the student retrieve it (not recognise it), with explanations; a mnemonic only for a list to learn by heart, in a callout tone "tip".
- "hands_on" (commands, configuration, code): a terminal session of the exact commands, then a drill (fill_blanks or code_exercise) that makes the student type them, and a callout tone "exam" with the procedure as a short checklist.
Put a callout tone "exam" on what the past papers ask most. Tag every Block that prepares for a Question Type with "exam_types": ["<its exact name>"].

Write the Section as an ordered list of Blocks. Each Block uses exactly one Component from this Catalogue, with data matching its fields (? = optional):
{{catalogue}}

Rules:
- Text fields are Markdown with $inline$ and $$display$$ LaTeX (KaTeX). Fields named latex are bare LaTeX. Every formula in text, diagram labels included, is LaTeX inside $…$: $\sqrt{n}$, $e^{iuX}$, never sqrt(n), e^(iu.X) or x**2. Only fields named expr use the sympy syntax.
- Mermaid diagrams must be valid Mermaid syntax.
- Show, then practise. Every Section where the material allows has at least one visual Block (plot, surface_plot, optimizer_animation, diagram, step_diagram, iteration_table, terminal) and at least one active practice Block (quiz, fill_blanks, code_exercise, exercise). Pick by what the content is:
  - a function of one variable: plot; of two variables: surface_plot; an iterative method on f(x, y): optimizer_animation;
  - a process, pipeline or architecture: diagram, or step_diagram to walk through it one stage at a time;
  - shell commands and their output: terminal; a config file or code to complete: fill_blanks; code to write from a task: code_exercise;
  - a calculation to do on paper: exercise with mode "hand" and steps; checking a definition or a common mistake: quiz with explanations.
- For a practical subject, teach by doing: show the command or file, explain it, then have the learner complete one.
- Expressions in expr, f and claims use sympy syntax: x**2, exp(x), sqrt(x), x1*x2.
- When there is math, add claims to Worked Examples, Exercises and Key Formulas whenever a derivative, gradient, Hessian or equality can be checked. The app verifies them. Each claim is exactly {"op", "expr", "vars", "expected"}, op one of equal, diff, grad, hessian; expected is an expression, a list for grad, a list of rows for hessian:
  {"op": "grad", "expr": "x**2 + x*y", "vars": ["x", "y"], "expected": ["2*x + y", "x"]}
  {"op": "hessian", "expr": "x**2 + x*y", "vars": ["x", "y"], "expected": [["2", "1"], ["1", "0"]]}
  {"op": "equal", "expr": "0.8 - 0.1*(-10.8)", "vars": [], "expected": "1.88"}
- A "from_source" Block says only what its cited pages say. Put your own explanations, intuitions and extra steps in a separate "model_added" Block.
- When PAGES is empty, write the Section from what the course teaches on its title, every Block "model_added". Never answer with a placeholder.
- Keep a Section to at most 12 Blocks: merge small steps, do not repeat what an earlier Block said.
- For an Iteration Table give only the method, f, vars, x0, step and iterations. The app computes the rows.
- origin is "from_source" when the Block restates the pages; it then needs citations [{"source","page","quote"?}] to the pages below. Use "model_added" for your own explanations, intuitions and extra exercises.
- Use prose only when no other Component fits.
- Rarely, when no Component can express something essential (not just style), propose a new one in "proposals":
  {"name": "snake_case", "description": "what it shows", "why": "why no Component fits", "schema": {JSON Schema of its data},
   "samples": [1-3 example data objects]}, and use its name as the Block's component. Never propose one the Catalogue already covers.

Inside JSON strings, escape every backslash: write "\\frac", not "\frac".
Answer with only this JSON object:
{"blocks": [{"component": "<name>", "data": {...}, "citations": [{"source": "...", "page": 1, "quote": "..."}], "origin": "from_source", "exam_types": []}], "proposals": []}

Chapter: {{chapter}}
The source pages for this Section:
PAGES:{{pages}}
SECTION: {{section}}
