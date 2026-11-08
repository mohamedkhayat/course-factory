Grade a student's exam answer step by step against the Marking scheme. For each scheme step, award between 0 and that step's points, and write one short comment in English saying what was right or what is missing. Grade what is written, not what the student probably meant. Give partial credit where the scheme allows it.

Answer with only this JSON object, one entry per scheme step, in the scheme's order and with the step text copied exactly:
{"steps": [{"step": "<scheme step>", "awarded": 1.5, "comment": "..."}]}

Question: {{statement}}

Model answer:
{{model_answer}}

Marking scheme:
{{scheme}}

The student's answer:
{{answer}}
