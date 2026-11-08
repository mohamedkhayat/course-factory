You are building one React Component for an interactive course, in TypeScript (TSX). It renders one Block of data.

Component name: {{name}}
What it shows: {{description}}
The Block data's JSON Schema: {{schema}}
Sample Block data (it must render all of them): {{samples}}

Fill in this template. Keep its shape: one file, `export type Data` matching the schema exactly, one default export taking `{ data }`.
Only "react" may be imported. No network (no fetch, no images from URLs), no storage, no timers that never stop, no globals.
It must pass `tsc --strict`. Text fields are plain strings: render them as text.
TEMPLATE:{{template}}

Owner's note (follow it if not empty): {{note}}

Your previous file (empty if none), and why it failed the gates (empty if none):
PREVIOUS:{{previous}}
ERRORS:{{errors}}

Answer with only this JSON object: {"code": "<the whole .tsx file>"}
