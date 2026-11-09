You are sorting the files of one university course.

For every source below, choose its role from exactly this list:
"course notes", "exercise sheet", "lab", "past exam", "correction", "personal notes", "data".

If a source is the correction (corrigé) of another source, set "paired_with" on the ORIGINAL source to the correction's name. Otherwise "paired_with" is null.

Inside JSON strings, escape every backslash: write "\\frac", not "\frac".
Answer with only this JSON object:
{"sources": [{"name": "<name>", "role": "<role>", "paired_with": "<name or null>"}]}

Each source has its name and the start of its first page.
SOURCES:{{sources}}
