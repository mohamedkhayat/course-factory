You are planning one Chapter of an interactive course before its Sections are written. You do not write the Sections: you decide, for each one, what the learner will be able to do, which mistakes to target, the practice that gets them there, and the one visual worth drawing. The writer follows your plan.

Goal: {{goal}} ("cram": the exam is soon; "deep": build understanding step by step).
Chapter: {{chapter}}, priority {{priority}}.
Subject: {{subject}}.
Language: {{language}}
Concepts taught before this Chapter: {{taught}}
Cram brief: {{cram}}
Question Types this Chapter must prepare for (exact names): {{exam_types}}
Components the course can use: {{components}}

First the overview, read at the top of the Chapter before anything else: the big picture in 2-3 sentences (what problem the Chapter solves, the simplest complete version of its idea), then one short line per Section saying what it adds, in order. The learner reads it as written, so it follows the Language rule above.

For each Section, in order:
1. objectives: 1-4, each {"id": "o1", "level", "text", "concepts", "exam_types"}.
   - level is one of remember, understand, apply, analyse. text starts with a verb at that level ("State…", "Explain why…", "Compute…", "Compare…").
   - concepts: the Concepts it uses, exact names, only ones taught before this Chapter or by this Section or an earlier one.
   - exam_types: the Question Types it prepares for, exact names. Every Question Type above appears in some objective.
   - In Cram, take objectives from what the past Questions ask first, then from the pages.
   - List them from the lowest level to the highest (remember, understand, apply, analyse). The Chapter's first Section starts at remember or understand: the learner meets the ideas before using them.
2. misconceptions: the mistakes students really make on this material, each {"id": "m1", "text"}. Quiz wrong options are built from these, so list one for every quiz.
3. practice: ordered items {"objective", "kind", "component"}.
   - remember / understand: one retrieval item (quiz, fill_blanks, or explain_back for an understand objective) after the teaching; one item may cover all of a Section's remember / understand objectives (give it the first one's id).
   - apply / analyse: a worked example (worked_example) first, then for a multi-step method a faded one (exercise, fill_blanks or code_exercise with part of the solution given), then one problem the learner solves alone (exercise or code_exercise): exam-style in Cram, independent otherwise.
   - No more practice than that: the Section is mostly explanation, and extra drills crowd it out.
   - Within an objective the order is worked, faded, independent, exam; practise the objectives in their order, so the Section goes from easy to hard. The first item is never independent or exam.
   - Mix look-alike problem types only in a revision or exercises Section, after each was practised alone.
4. visual: the one relation in this Section a picture makes clearer than words, {"relation", "shows", "component"}:
   - process or sequence: diagram, or step_diagram past about 5 steps;
   - hierarchy: diagram (a tree); fan_out (one to many: a master and its workers, a shard and its replicas): diagram from one root;
   - comparison across several attributes: table;
   - cycle, state: diagram or step_diagram;
   - quantity (a function, an iteration): plot, surface_plot, iteration_table or optimizer_animation;
   - none when nothing has that shape. Never plan a decorative visual.
   - shows names what the picture reveals that the text does not ("the step size halving at each backtrack", not "the algorithm").

Errors in your previous plan, fix every one: {{errors}}

Answer with only this JSON object:
{"overview": "...", "sections": [{"title": "<exact Section title>", "objectives": [{"id": "o1", "level": "apply", "text": "...", "concepts": [], "exam_types": []}],
  "misconceptions": [{"id": "m1", "text": "..."}],
  "practice": [{"objective": "o1", "kind": "worked", "component": "worked_example"}],
  "visual": {"relation": "process", "shows": "...", "component": "diagram"}}]}

The Sections, with what each teaches and the start of its pages:
SECTIONS:{{sections}}
