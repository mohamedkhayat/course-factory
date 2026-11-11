// Reads {math: [{id, tex, display}], mermaid: [{id, src}]} on stdin; prints {errors: [{id, kind, message}]}.
import { JSDOM } from "jsdom";
import katex from "katex";

const dom = new JSDOM("<!doctype html><body></body>");
globalThis.window = dom.window;
globalThis.document = dom.window.document;
// Mermaid sanitizes labels holding HTML (<br/>) with DOMPurify, which needs the DOM classes (Element, Node...) as globals.
for (const k of Object.getOwnPropertyNames(dom.window)) if (/^[A-Z]/.test(k) && !(k in globalThis)) globalThis[k] = dom.window[k];
const { default: mermaid } = await import("mermaid");

let input = "";
for await (const chunk of process.stdin) input += chunk;
const { math = [], mermaid: diagrams = [] } = JSON.parse(input || "{}");
const errors = [];
for (const m of math) {
  try { katex.renderToString(m.tex, { displayMode: !!m.display, throwOnError: true, strict: "ignore" }); }
  catch (e) { errors.push({ id: m.id, kind: "math", message: `${String(e.message).split("\n")[0]} in: ${m.tex.slice(0, 120)}` }); }
}
for (const d of diagrams) {
  try { await mermaid.parse(d.src); }
  catch (e) { errors.push({ id: d.id, kind: "diagram", message: String(e.message).split("\n").slice(0, 3).join(" ") }); }
}
process.stdout.write(JSON.stringify({ errors }));
