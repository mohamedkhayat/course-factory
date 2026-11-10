You are planning one Chapter of an interactive course before its Sections are written. You do not write the Sections: you decide, for each one, what the learner will be able to do, which mistakes to target, the practice that gets them there, and the one visual worth drawing. The writer follows your plan.

Goal: {{goal}} ("cram": the exam is soon; "deep": build understanding step by step).
Chapter: {{chapter}}, priority {{priority}}.
Subject: {{subject}}.
Language: {{language}}
Concepts taught before this Chapter: {{taught}}
Cram brief: {{cram}}
Question Types this Chapter must prepare for (exact names): {{exam_types}}
Components the course can use: {{components}}

For each Section, in order:
1. objectives: 1-4, each {"id": "o1", "level", "text", "concepts", "exam_types"}.
   - level is one of remember, understand, apply, analyse. text starts with a verb at that level ("State…", "Explain why…", "Compute…", "Compare…").
   - concepts: the Concepts it uses, exact names, only ones taught before this Chapter or by this Section or an earlier one.
   - exam_types: the Question Types it prepares for, exact names. Every Question Type above appears in some objective.
   - In Cram, take objectives from what the past Questions ask first, then from the pages.
2. misconceptions: the mistakes students really make on this material, each {"id": "m1", "text"}. Quiz wrong options are built from these, so list one for every quiz.
3. practice: ordered items {"objective", "kind", "component"}.
   - remember / understand: a retrieval item (quiz or fill_blanks) after the teaching.
   - apply / analyse: a worked example (worked_example) first, then for a multi-step method a faded one (exercise, fill_blanks or code_exercise with part of the solution given), then an independent problem (exercise or code_exercise), and in Cram an exam-style one (exercise or code_exercise).
   - Within an objective the order is worked, faded, independent, exam.
   - Mix look-alike problem types only in a revision or exercises Section, after each was practised alone.
4. visual: the one relation in this Section a picture makes clearer than words, {"relation", "shows", "component"}:
   - process or sequence: diagram, or step_diagram past about 5 steps;
   - hierarchy: diagram (a tree); fan_out (one to many: a master and its workers, a shard and its replicas): diagram from one root;
   - comparison across several attributes: table;
   - cycle, state: diagram or step_diagram;
   - quantity (a function, an iteration): plot, surface_plot, iteration_table or optimizer_animation;
   - none when nothing has that shape. Never plan a decorative visual.

Errors in your previous plan, fix every one: {{errors}}

Answer with only this JSON object:
{"sections": [{"title": "<exact Section title>", "objectives": [{"id": "o1", "level": "apply", "text": "...", "concepts": [], "exam_types": []}],
  "misconceptions": [{"id": "m1", "text": "..."}],
  "practice": [{"objective": "o1", "kind": "worked", "component": "worked_example"}],
  "visual": {"relation": "process", "shows": "...", "component": "diagram"}}]}

The Sections, with what each teaches and the start of its pages:
SECTIONS:{{sections}}
