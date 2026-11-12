You are writing Mock exam number {{number}} for a course, in the style of its past papers: same length, duration, tone, notation and kinds of questions. Cover the recurring question types, weighting Chapters by their Exam Weight. Write new questions; do not copy the past papers or the Mock exams already written.

When there are no past papers, write the exam a professor of this course would set: about 90 minutes, one exercise per Chapter weighted by what the course teaches, each exercise a short case with numbered questions.

Ask what the course teaches, with its own names, commands and code. The course digest below lists, per Chapter, the Concepts taught and the exact commands, code and configuration shown in the course and its labs. For a practical or mixed course, at least half of the points ask the student to write, complete, correct or explain those commands and code: a command with the right options for a stated goal, a file or snippet to complete, what a given command or snippet does and what it prints, the order of the commands of a procedure. Use only the commands, options, decorators and functions the digest shows; never a tool or flag the course does not teach. The rest checks understanding (why a step is needed, what goes wrong without it, comparing two approaches), not recitation.

Language: {{language}}

Statements and model answers are Markdown with $inline$ and $$display$$ KaTeX; code and commands go in fenced code blocks with their language. Give each question the Chapter it tests ("chapter", its exact title), its points and a Marking scheme whose points add up to the question's points. A model answer gives the exact command or code expected, then one line on why.

Inside JSON strings, escape every backslash: write "\\frac", not "\frac".
Answer with only this JSON object:
{"title": "...", "duration_min": 90, "chapters": ["<chapter title>"], "questions": [{"statement": "...", "points": 4, "model_answer": "...", "chapter": "<chapter title>", "scheme": [{"step": "...", "points": 2}]}]}

The Chapters with their Exam Weight:
CHAPTERS:{{chapters}}

The course digest, per Chapter:
DIGEST:{{digest}}

The past papers and Mock exams already written (statements and points):
PAST:{{past_papers}}
