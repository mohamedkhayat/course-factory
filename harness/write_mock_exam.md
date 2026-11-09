You are writing Mock exam number {{number}} for a course, in the style of its past papers: same length, duration, tone, notation and kinds of questions. Cover the recurring question types, weighting Chapters by their Exam Weight. Write new questions; do not copy the past papers.

Language: {{language}}

Statements and model answers are Markdown with $inline$ and $$display$$ KaTeX. Give each question the Chapter it tests ("chapter", its exact title), its points and a Marking scheme whose points add up to the question's points.

Inside JSON strings, escape every backslash: write "\\frac", not "\frac".
Answer with only this JSON object:
{"title": "...", "duration_min": 90, "chapters": ["<chapter title>"], "questions": [{"statement": "...", "points": 4, "model_answer": "...", "chapter": "<chapter title>", "scheme": [{"step": "...", "points": 2}]}]}

The Chapters with their Exam Weight:
CHAPTERS:{{chapters}}

The past papers (statements and points):
PAST:{{past_papers}}
