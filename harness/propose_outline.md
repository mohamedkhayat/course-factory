You are planning an interactive course from a university course's material.

Goal: {{goal}}
- "cram": an exam is coming. Keep the professor's chapter order, but be complete about exam topics.
- "deep": the owner wants to learn it properly, in the professor's order.

First classify the subject as "kind": "theoretical" (definitions, theorems, proofs: maths, physics), "practical" (tools, commands, configuration: DevOps, MLOps, programming) or "mixed". For a practical subject, plan tutorial-style Sections that build something step by step.

Propose the course outline: Chapters in the professor's order, each with Sections. Every Section lists the source pages it is built from (course notes first, then the exercise sheets and labs that practise it). Use the course's own chapter structure when the notes have one. Write titles in the material's language.

Inside JSON strings, escape every backslash: write "\\frac", not "\frac".
Answer with only this JSON object:
{"kind": "mixed", "chapters": [{"title": "...", "sections": [{"title": "...", "pages": [{"source": "<source name>", "page": 1}]}]}]}

The sources, with their Role and the start of every page:
SOURCES:{{sources}}
