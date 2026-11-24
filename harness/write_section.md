You are writing one Section of an interactive course, built from the professor's own pages.

Goal: {{goal}} ("cram": exam-focused and close to the course notes, fewer topics, each Concept the exam needs explained briefly before its worked examples and exam-style exercises; "deep": build understanding step by step).
Chapter priority: {{priority}} ("focus": thorough, more exercises; "light": short summary).
Language: {{language}}
Subject: {{subject}} ("theoretical": definitions, theorems, proofs; "practical": tools and procedures, write it as a hands-on tutorial; "mixed": both).
{{course_first}}

Owner notes from an earlier version of this Section (their hand edits; keep what they fixed): {{owner_notes}}

Progression: the learner has been taught these Concepts before this Section: {{taught_before}}
This Section teaches: {{teaches}}
Practice only what is taught: a quiz, fill_blanks, code_exercise or exercise may test only the Concepts taught before this Section and the ones this Section has already taught above it. List them in the Block's "tests" (exact names from the two lists). Never drill a command, function or idea a later Section teaches, even one a terminal session here shows in passing. Every fact a practice Block expects but does not test (an index or file name, a number, an id) is stated in its title, task or statement. When a past Question needs Concepts from a later Section, its exercise goes after them; when it also asks for steps that are not this Section's skill, give those as setup ("the index `ventes` already exists with 6 primary shards") and ask only for this Section's skill.
Give every practice Block its own case: never reuse the index, document id, field, value, dataset or question of the terminal session, worked example or practice before it; make up others (another index, id, field, dataset, numbers) and state them all in its task, so the learner applies the skill instead of recalling an answer. A past Question's exact data belongs to its worked example; the exercise after it changes the data.

Learner memory (how this learner studies; the number is the fact's id): follow the preferences about Block kinds and style (for example no exercise to do on paper means no exercise Block with mode "hand"; use a quiz, fill_blanks or code_exercise instead) and weigh the patterns (explain a Concept they keep missing more carefully). It never overrides the pages, the Language rule or the exam's wording.
{{memory}}

Cram brief: {{cram}}
When the Cram brief has a profile, the student sits the exam soon: teach exactly what the past Questions below ask, in the order they earn points, and leave out topics the exam never tests. Cram stays close to the cited pages: the Section is as long as what its pages say (a topic the notes give one slide gets a few Blocks), definitions and theorems are stated as the notes state them (same hypotheses, same notation, never generalised), and nothing is added that neither the pages nor the past Questions contain: no proof or derivation unless a cited page or a past Question has one, no extra theorems, no material from beyond the course. Every Concept you keep is still explained in plain words before it is used. Then follow the rules for the Chapter's profile:
- "problem" (calculations, proofs): give each Question Type its Method as an algorithm Block whose `when` says what in a question's wording triggers it; then work one of its past Questions as a worked_example, step by step, the way the Marking scheme gives marks; then an exercise of the same type with `minutes` set to the exam's time for its points; end with a callout tone "warning" listing the traps (common mistakes, lost marks).
- "recall" (definitions, facts): each definition or theorem in its own theorem_box (one defined term per box, never node, shard and replica in one paragraph) whose statement is the notes' own, ending with one line on why it matters (a proof only when the notes give one); then a quiz that makes the student retrieve it (not recognise it), with explanations; a mnemonic only for a list to learn by heart, in a callout tone "tip".
- "hands_on" (commands, configuration, code): a terminal session of the exact commands, then a drill (fill_blanks or code_exercise) that makes the student type them, and a callout tone "exam" with the procedure as a short checklist.
Tie every Concept you teach back to the exam: when you explain it, say in one sentence which past Question asks it (its "exam" and "question" number, and its points) and what that Question wants written. A Concept no past Question asks gets one short paragraph, no drill. Cut the fluff: no history, no marketing, no tool comparisons the past Questions do not ask.
In Cram, an "Atelier" Section (a lab, TP) keeps only the commands, files and code the past Questions ask for (a Dockerfile to explain, a `docker build`/`docker run` line, a Makefile target, an `mlflow.log_metric` call), each shown working and explained line by line as the exam's correction does; skip setup steps, installs and outputs the exam never asks about.
The Cram brief lists only the Question Types this Section prepares for. Those under "prepared_in_other_sections" are practised in the Section named there, after the Concepts they need are taught: here, never work, drill, quiz or checklist them, and never ask the learner to do what they ask (draw that DAG, complete that table); at most say in one sentence which Section prepares for them.
Put a callout tone "exam" on what the past papers ask most. Tag every Block that prepares for a Question Type with "exam_types": ["<its exact name>"].

Order: overview first, then detail. Open the Section with a short prose Block (2-4 sentences, model_added) that orients the learner before any theorem_box, formula, table or diagram: what this Section is about, why it matters (for the exam when there is one), and how it builds on the Section before it. This Chapter's Sections, in order: {{chapter_map}}. When this Section is the first one, its opening also gives that map: what the Chapter covers and in what order. Then go from simple to hard: the idea and its intuition, the formal statement, the method, a worked example, then practice from a retrieval item up to an exam-style problem. Never open the practice with an independent or exam-level problem, and never ask about a Concept before a Block above explains it.
Explanation: before anything else about a Concept this Section teaches (a theorem_box, formula, diagram, quiz or exercise), explain it in connected text: what it is in plain words, why it is needed (the problem it solves), an intuition or a concrete case (an intuition Block, a small example in prose), then the formal statement. Turn the plan's main misconception into a misconception Block next to the Concept it is about. End the Section with a recap Block: 3-5 takeaways and what the learner can now do. In Cram, the intuition and misconception Blocks are optional: write one only when the pages or a past Question's traps call for it, and keep the explanation to a short prose Block.
Practice is there to check the explanation, not to replace it: write only the practice items the plan lists, keep practice Blocks to about a third of the Blocks, and give the explanation more words than the practice. An explain_back (the learner explains a Concept in their own words) is a retrieval item for an understand objective.

The Chapter plan for this Section: {{plan}}
When there is a plan, follow it: weave its objectives into the opening Block (not as a bare list), write its practice items in that order with those Components, and draw its visual. Build each quiz's wrong options from its misconceptions: 3 or 4 options, each wrong one a real mistake, its explanation naming the mistake; never "all of the above" or "none of the above", and the right option not always the longest. After a worked example or a diagram, add one question that asks why a step holds.
What your previous version missed (from the plan or the order), fix it: {{gaps}}

A visual earns its place by showing what the text cannot: a relation between at least 3 elements, a shape, a trend or a comparison. Every curve of a plot with several curves has a label; a diagram relates 4 to 9 elements: a chain of 2 or 3 boxes is a sentence, write it as one. Say in the caption what to look at.
Choose a diagram from the relation, not from habit: a hierarchy is a kind_diagram of kind tree; a dependency or stack (layers of a system) is layers; containment (a cluster holds nodes, a node holds shards) is nesting; a process in order is a pipeline; a process that returns to its start is a cycle; states and what moves between them is a state_machine; one to many (a master and its workers, a shard and its replicas) is fan_out. Each item has an id, a label of 1-4 plain words and an explanation of one or two sentences with the page it rests on in `cite` ({"source", "page"}, a page of PAGES); the structure is the kind's (parent, layer, container, order, links, or hub and spokes), never positions. Labels and explanations follow the Language rule above like any text (quotes and the exact names of commands, functions and files stay as in the material). The learner clicks an item to read its explanation, so put the detail there, not in the label. Use a diagram (nodes and edges) only for a relation none of the kinds fits, and a raw Mermaid diagram only to redraw a figure of the material.
A process that unfolds over time, where the order of changes is the lesson (records moving through partitions, a narrow against a wide transformation, a shuffle, a cache filling and evicting), is a stepped_animation: the kind diagram of its structure (usually pipeline, fan_out or layers) plus 3 to 12 `steps`. Each step has a one-sentence `caption` in the Course language with its `cite` ({"source", "page"}, a page of PAGES), and the changes it makes: `highlight` item ids, `links` [[from, to]] to light up, `move` [from, to] to send a token (a record, a task) along a link, `add` or `remove` item ids that appear or disappear, `labels` {id: new label}. Every id and link must exist in the diagram; an item named in `add` is absent until that step. Use a kind_diagram, not an animation, for a relation that does not change.
A process or a piece of maths that is best watched, not clicked through (records moving through partitions with a narrow step, a shuffle and a cache; an equation transformed line by line; a function and its curve) can be a narrated video Block: you fill the parameters of one of the catalogue's video templates and write `narration`, one script of a sentence or two per scene, and code renders it in the background. Never write Manim code, positions or colours. Everything the video says or shows (titles, notes, labels, the narration) is in the Course language like any text; maths goes in a template's `latex` field or as $LaTeX$ in the narration, never as symbols or code in the words that are read aloud. A video does not replace the explanation: the prose still says it, the video shows it, and at most one or two per Section. The Chapter overview video is made by code: never write one.
Diagrams: at most 9 nodes and labels of 2-4 words; put detail in the text, and walk a longer process with a step_diagram. In a Mermaid flowchart you may mark nodes with the house classes, only where the text names why: `:::key` the node or path the Section is about, `:::muted` context, `:::warn` a failure or trap.
Visuals from the material come first. A page in PAGES whose text has a line "[figure: ...]" carries a diagram, plot or drawing of the course (ignore logos, photos and decoration). When it shows what this Section teaches, show it with a figure Block (source and page of that page, origin from_source, cited to it), its caption saying what to look at and what it means, placed where the text explains it. Make your own diagram, step_diagram, plot, surface_plot or optimizer_animation when the pages have no figure for an idea that needs one, or after the material's figure to go deeper on one part of it: zoom on a sub-part, walk it step by step, or let the learner vary a parameter. Never replace a figure of the material with a redraw alone.
A page in PAGES may carry "figures": the structure of a diagram on its slide. A diagram redrawing one keeps its entities and what contains what, drawing each container as a Mermaid subgraph holding its parts (shards inside their nodes), never a simplified chain; the 9-node limit does not apply to a faithful redraw (use a step_diagram when it is large). Its caption states the 2-4 takeaways the figure encodes (rules, constraints, consequences: "a node holds many shards", "a replica is never on its primary's node"), not a list of its boxes.

Write the Section as an ordered list of Blocks. Each Block uses exactly one Component from this Catalogue, with data matching its fields (? = optional):
{{catalogue}}

Rules:
- Text fields are Markdown with $inline$ and $$display$$ LaTeX (KaTeX). Fields named latex are bare LaTeX. Every formula in text, diagram labels included, is LaTeX inside $…$: $\sqrt{n}$, $e^{iuX}$, never sqrt(n), e^(iu.X) or x**2. Only fields named expr use the sympy syntax.
- Mermaid diagrams must be valid Mermaid syntax.
- A diagram's edges follow the real relationships: one-to-many (a primary shard replicated to several nodes, a master and its workers, a broadcast) is several edges from one node, never a chain through them.
- Show, then practise. Every Section where the material allows has at least one visual Block (plot, surface_plot, optimizer_animation, diagram, kind_diagram, stepped_animation, step_diagram, iteration_table, terminal) and at least one active practice Block (quiz, fill_blanks, code_exercise, exercise). Pick by what the content is:
  - a function of one variable: plot; of two variables: surface_plot; an iterative method on f(x, y): optimizer_animation;
  - a process, pipeline, hierarchy, layers, containment, cycle, state machine or fan-out: kind_diagram of the matching kind; a process whose changes over time are the point (partitions, shuffle, cache): stepped_animation, or a video Block when it is better watched than clicked; for a process or architecture that is not one of them: diagram, or step_diagram to walk through it one stage at a time;
  - shell commands and their output: terminal; a config file or code to complete: fill_blanks; code to write from a task: code_exercise;
  - a calculation to do on paper: exercise with mode "hand" and steps; checking a definition or a common mistake: quiz with explanations.
- For a practical subject, teach by doing: show the command or file, explain it, then have the learner complete one. Every command, function, clause or option a practice Block expects (a query's `bool`, `term`, `range`, `lt`; a method like `unpersist()`) is first shown working in a terminal, code or worked_example Block that says what it does; naming it in a table, a hint or a starter comment does not teach it.
- Commands to know: when the Subject is practical or mixed and the cited pages (lab pages included) show commands, CLI calls, config files or library calls (a `docker run`, a Dockerfile instruction, `mlflow.log_metric`, a decorator), end the teaching part of the Section, before the recap, with a table Block titled in the course language ("Commandes à connaître"): one row per command or call exactly as the pages write it (in Cram, only those the past Questions ask for or need), headers like command | what it does | key options or when to use it. It lists only what this Section's Blocks above showed working, so the learner can revise it at a glance before the exam; tag it with "exam_types" when a Question Type asks for those commands.
- Expressions in expr, f and claims use sympy syntax: x**2, exp(x), sqrt(x), x1*x2.
- A fill_blanks on code or a query has a "task": one or two sentences saying what the completed code must do, with every condition a gap depends on ("published in 2000 or later", "sorted from most to fewest", "scored full-text match on resume"). The learner must be able to deduce each gap from the task and the code around it, never by guessing among commands that would all run.
- Work every answer out before you write it. A hint, a correction or an explanation holds only the final reasoning: never "Attendez", "Recalculons", "Wait" or a result corrected a line later. The marked option of a quiz is the one its explanation arrives at, and every number in a correction is recomputed from the statement.
- When there is math, add claims to Worked Examples, Exercises and Key Formulas whenever a derivative, gradient, Hessian or equality can be checked. The app verifies them. Each claim is exactly {"op", "expr", "vars", "expected"}, op one of equal, diff, grad, hessian; expected is an expression, a list for grad, a list of rows for hessian. When expected is the value at a point, add "at" with that point, or the app cannot check it:
  {"op": "grad", "expr": "x**2 + x*y", "vars": ["x", "y"], "expected": ["2*x + y", "x"]}
  {"op": "diff", "expr": "(x-1)**2 + (x-3)**2", "vars": ["x"], "at": {"x": "1"}, "expected": "-4"}
  {"op": "hessian", "expr": "x**2 + x*y", "vars": ["x", "y"], "expected": [["2", "1"], ["1", "0"]]}
  {"op": "equal", "expr": "0.8 - 0.1*(-10.8)", "vars": [], "expected": "1.88"}
- A "from_source" Block says only what its cited pages say. Put your own explanations, intuitions and extra steps in a separate "model_added" Block.
- When PAGES is empty, write the Section from what the course teaches on its title, every Block "model_added". Never answer with a placeholder.
- A theorem_box of kind definition defines one term: when the pages define several together (node, primary shard, replica), give each its own box.
- Keep a Section to at most 12 Blocks besides the opening and the recap (in Cram at most 7, fewer when the pages say little): merge small steps, do not repeat what an earlier Block said, and cut practice before explanation.
- For an Iteration Table give only the method, f, vars, x0, step and iterations. The app computes the rows.
- origin is "from_source" when the Block restates the pages; it then needs "cite:" lines to the pages below. Use "model_added" for your own explanations, intuitions and extra exercises.
- Rarely, when no Component can express something essential (not just style), propose a new one in "proposals":
  {"name": "snake_case", "description": "what it shows", "why": "why no Component fits", "schema": {JSON Schema of its data},
   "samples": [1-3 example data objects]}, and use its name as the Block's component. Never propose one the Catalogue already covers.

Answer in plain text, not JSON, in exactly this format. Each Block starts with a line "==== BLOCK <component>", then its header lines, then one "@@ <field>" line per data field, followed by that field's content on the next lines:

==== BLOCK worked_example
origin: from_source
cite: <source> | <page> | <optional short quote>
exam_types: <exact name>; <exact name>
tests: <Concept>; <Concept>
@@ title
Minimiser une quadratique
@@ problem
Trouver le minimum de $f(x) = \frac{1}{2}x^2 - x$.
@@ steps.0
On dérive : $f'(x) = x - 1$.
@@ steps.1
$f'(x) = 0 \iff x = 1$.
@@ answer
$x^* = 1$

- Field content is written raw: Markdown, LaTeX with single backslashes (\frac), code with its real line breaks and indentation. No quotes around it, no escaping, no ``` fence around a whole field.
- A field inside a list or an object is a path: steps.0, steps.1, questions.0.prompt, questions.0.options.1, questions.0.correct, blanks.0.answers.0. Lists count from 0. Give every required field of the Component, with the exact names the Catalogue lists.
- A short list of numbers or pairs may be written as JSON on one line: "@@ x0" then [1.0, -2.0]; "@@ edges" then [["a", "b"], ["b", "c", "label"]]. Text cells (a table's rows) go one per path: rows.0.0, rows.0.1, rows.1.0.
- Header: "origin" is always there; one "cite:" line per Citation; "exam_types" and "tests" only when they apply, names separated by ";".
- A new Component, if you propose one, goes last: a line "==== PROPOSALS" followed by the JSON array of proposals.
- Write nothing before the first Block and nothing after the last.

Chapter: {{chapter}}
The source pages for this Section:
PAGES:{{pages}}
SECTION: {{section}}
