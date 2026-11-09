You are rebuilding a real past exam paper faithfully, so a student can sit it again in a timed exam mode.

Language: {{language}}

Copy every question and sub-question in order, word for word, with its points (the barème). If the paper gives no points, share 20 points sensibly. Read the duration from the paper (in minutes; 90 if not given).
Statements are Markdown with $inline$ and $$display$$ KaTeX.

For every question, take the model answer from the corrigé. If there is no corrigé, solve it yourself, carefully. When the corrigé shows the steps that earn points, give them as a Marking scheme whose points add up to the question's points; otherwise leave "scheme" null.

Give every question the course Chapter it tests, by its exact title ("chapter"; null if none fits), and list the Chapters the paper covers.

Inside JSON strings, escape every backslash: write "\\frac", not "\frac".
Answer with only this JSON object:
{"title": "...", "duration_min": 90, "chapters": ["<chapter title>"], "questions": [{"statement": "...", "points": 4, "model_answer": "...", "chapter": "<chapter title>", "scheme": [{"step": "...", "points": 2}]}]}

Course Chapters: {{chapters}}

The corrigé pages:
CORRECTION:{{correction}}

The exam pages:
EXAM:{{exam}}
