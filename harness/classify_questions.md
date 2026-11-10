You are sorting a course's past exam questions into Question Types, so a student cramming for the exam knows which kinds of question come back and how to answer each.

Language: {{language}}

A Question Type is a kind of question the professor asks again and again, answered with the same method: "Compute a characteristic function", "Prove a set is convex", "Write a Dockerfile for a Python app". Group the questions below into Question Types:
- every question id goes into exactly one Question Type;
- name each type in a few words, in the material's language, as an instruction ("Calculer ...", "Montrer que ...");
- "trigger": one sentence on what in a question's wording tells the student it is this type;
- "chapter": the exact title of the Chapter the type belongs to, or null;
- "template": the answer skeleton that earns the marks, as 2-5 short numbered Markdown steps taken from the Marking schemes and model answers (what to write first, which result to cite, how to conclude). Formulas are LaTeX inside $…$.

Prefer a few broad types over one type per question; a type with one question is fine when nothing else is like it.

Inside JSON strings, escape every backslash: write "\\frac", not "\frac".
Answer with only this JSON object:
{"types": [{"name": "...", "trigger": "...", "chapter": "<chapter title>", "template": "1. ...\n2. ...", "questions": [1, 2]}]}

Course Chapters: {{chapters}}

The past exam questions, with their id, points, Chapter, model answer and Marking scheme:
QUESTIONS:{{questions}}
