You are planning an interactive course from a university course's material.

Goal: {{goal}}
- "cram": an exam is coming. Keep the professor's chapter order, but be complete about exam topics.
- "deep": the owner wants to learn it properly, in the professor's order.

First classify the subject as "kind": "theoretical" (definitions, theorems, proofs: maths, physics), "practical" (tools, commands, configuration: DevOps, MLOps, programming) or "mixed". Judge it from the course notes, exercise sheets and past exams, never from notebooks, data files or images: a maths, probability or optimisation course with Python labs is "theoretical" when its exams are calculations and proofs. For a practical subject, plan tutorial-style Sections that build something step by step.

Give each Chapter a "profile", how a student crams it before the exam: "problem" (exam questions are calculations or proofs to work out), "recall" (definitions, facts, lists to know by heart), "hands_on" (commands, configuration, code to write).

Propose the course outline: Chapters in the professor's order, each with Sections. Every Section lists the source pages it is built from (course notes first, then the exercise sheets and labs that practise it). Use the course's own chapter structure when the notes have one. An exercise sheet (TD), its correction and a lab (TP) are practice for the Chapter whose course notes they exercise: put them as the last Sections of that Chapter, never as a Chapter of their own. Two sets of course notes that the professor files under one chapter (the same folder or chapter number) are one Chapter. Past exams may form one final revision Chapter. In "cram" when there are past exams among the sources, read their page starts first: they say what the course is for. Give the topics they ask the Sections and the Concepts, and give a topic no past exam asks at most one short Section. Then put each Chapter's labs (TP, atelier) together as one last Section of that Chapter titled "Atelier <n>" (the lab's number), citing only the lab pages that show commands, files or code the past exams ask for. Write titles in the material's language.

For every Section, list in "teaches" the Concepts it teaches (short names: a command, a function, a definition, a method), in the order a learner meets them. Each Concept is taught in exactly one Section, the first that explains it: a Section that only uses or previews a Concept does not list it. Every Section teaches at least one Concept, except an exercises or revision Section. Order the Sections so that each one needs only Concepts taught before it.

Inside JSON strings, escape every backslash: write "\\frac", not "\frac".
Answer with only this JSON object:
{"kind": "mixed", "chapters": [{"title": "...", "profile": "problem", "sections": [{"title": "...", "pages": [{"source": "<source name>", "page": 1}], "teaches": ["..."]}]}]}

The sources, with their Role and the start of every page:
SOURCES:{{sources}}
