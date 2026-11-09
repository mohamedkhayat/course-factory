You are planning an interactive course from a university course's material.

Goal: {{goal}}
- "cram": an exam is coming. Keep the professor's chapter order, but be complete about exam topics.
- "deep": the owner wants to learn it properly, in the professor's order.

Propose the course outline: Chapters in the professor's order, each with Sections. Every Section lists the source pages it is built from (course notes first, then the exercise sheets and labs that practise it). Use the course's own chapter structure when the notes have one. Write titles in the material's language.

Answer with only this JSON object:
{"chapters": [{"title": "...", "sections": [{"title": "...", "pages": [{"source": "<source name>", "page": 1}]}]}]}

The sources, with their Role and the start of every page:
SOURCES:{{sources}}
