A learner is doing a hands-on exercise. Judge whether their code or config does what the task asks. The reference solution is one correct answer, not the only one: accept any answer that would work and meets the task.

- `correct`: true when the answer works and meets the task. Ignore style, comments and harmless differences.
- `feedback`: when wrong, say what is wrong or missing in one or two sentences, without giving the fix. When right, say briefly why it works, and mention one improvement if there is a real one.
- `hint`: a nudge towards the next thing to fix that does not give the answer away. Empty when correct.

{{language}}

TASK:
{{task}}

LANGUAGE: {{code_language}}

REFERENCE SOLUTION:
{{solution}}

LEARNER'S ANSWER:
{{code}}

Answer with only this JSON object:
{"correct": false, "feedback": "", "hint": ""}
