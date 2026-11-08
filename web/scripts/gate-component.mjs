// The Component gate. Usage: node gate-component.mjs <Component.tsx> <samples.json> <out dir>
// Gates, in order, stopping at the first failure: strict tsc, import allowlist, esbuild bundle,
// render in a sandboxed iframe (no network) with the sample Block data, plus a screenshot.
// Prints {ok, gates: [{gate, ok, errors}]}; on success <out dir> has component.js and screenshot.png.
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";
import * as esbuild from "esbuild";
import { chromium } from "playwright";

const ALLOWED = new Set(["react"]);
const [file, samplesFile, outDir] = process.argv.slice(2);
const web = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const work = fs.mkdtempSync(path.join(web, ".gate-")); // inside web/ so imports resolve to web/node_modules
const src = path.join(work, "Component.tsx");
const entry = path.join(work, "entry.tsx");
fs.copyFileSync(file, src);
fs.writeFileSync(entry, `import { createRoot } from "react-dom/client";
import Component from "./Component";
export function render(el: HTMLElement, data: unknown, onError: (e: unknown) => void) {
  createRoot(el, { onUncaughtError: onError, onCaughtError: onError }).render(<Component data={data as never} />);
}
`);
const gates = [];

function finish() {
  fs.rmSync(work, { recursive: true, force: true });
  console.log(JSON.stringify({ ok: gates.length === 4 && gates.every((g) => g.ok), gates }));
  process.exit(0);
}
function gate(name, errors) {
  gates.push({ gate: name, ok: errors.length === 0, errors });
  if (errors.length) finish();
}

// 1. strict tsc
const program = ts.createProgram([entry], {
  strict: true, noEmit: true, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext,
  moduleResolution: ts.ModuleResolutionKind.Bundler, skipLibCheck: true, types: [], lib: ["lib.es2022.d.ts", "lib.dom.d.ts"],
});
gate("tsc", ts.getPreEmitDiagnostics(program).map((d) => {
  const msg = ts.flattenDiagnosticMessageText(d.messageText, " ");
  if (!d.file) return msg;
  const { line } = d.file.getLineAndCharacterOfPosition(d.start ?? 0);
  return `${path.basename(d.file.fileName)} line ${line + 1}: ${msg}`;
}));

// 2. import allowlist (static imports, re-exports, require and dynamic import)
const sf = ts.createSourceFile(src, fs.readFileSync(src, "utf8"), ts.ScriptTarget.ES2022, true, ts.ScriptKind.TSX);
const bad = [];
(function walk(n) {
  if ((ts.isImportDeclaration(n) || ts.isExportDeclaration(n)) && n.moduleSpecifier && ts.isStringLiteral(n.moduleSpecifier)) {
    if (!ALLOWED.has(n.moduleSpecifier.text)) bad.push(`import of '${n.moduleSpecifier.text}' is not allowed (only: ${[...ALLOWED].join(", ")})`);
  } else if (ts.isCallExpression(n) && (n.expression.kind === ts.SyntaxKind.ImportKeyword ||
             (ts.isIdentifier(n.expression) && n.expression.text === "require"))) {
    bad.push("dynamic import and require are not allowed");
  }
  ts.forEachChild(n, walk);
})(sf);
gate("imports", bad);

// 3. esbuild bundle
fs.mkdirSync(outDir, { recursive: true });
const bundle = path.join(outDir, "component.js");
try {
  await esbuild.build({ entryPoints: [entry], bundle: true, format: "iife", globalName: "CF", platform: "browser", outfile: bundle,
    minify: true, logLevel: "silent", define: { "process.env.NODE_ENV": '"production"' }, jsx: "automatic" });
  gate("bundle", []);
} catch (e) {
  gate("bundle", (e.errors ?? [{ text: String(e) }]).map((x) => x.text));
}

// 4. render each sample in a sandboxed iframe whose CSP allows no network at all
const samples = JSON.parse(fs.readFileSync(samplesFile, "utf8"));
const csp = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:";
const code = fs.readFileSync(bundle, "utf8").replaceAll("</script", "<\\/script");
const doc = `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="${csp}">
<style>body{font:15px system-ui;margin:12px}.cf-sample{border-bottom:1px dashed #ccc;padding:8px 0}</style></head><body>
<script>const errs=[];addEventListener("error",e=>errs.push("crash: "+e.message));
addEventListener("unhandledrejection",e=>errs.push("crash: "+(e.reason&&e.reason.message||e.reason)));
document.addEventListener("securitypolicyviolation",e=>errs.push("network access blocked: "+e.blockedURI));</script>
<script>${code}</script>
<script>const samples=${JSON.stringify(samples).replaceAll("<", "\\u003c")};const roots=samples.map(s=>{
const d=document.createElement("div");d.className="cf-sample";document.body.appendChild(d);
try{CF.render(d,s,e=>errs.push("crash: "+(e&&e.message||e)))}catch(e){errs.push("crash: "+e.message)}return d});
setTimeout(()=>parent.postMessage({errs,empty:roots.filter(r=>!r.innerHTML.trim()).length,height:document.body.scrollHeight},"*"),400);</script>
</body></html>`;
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 860, height: 600 } });
  const requests = [];
  await page.route("**/*", (r) => { requests.push(r.request().url()); r.abort(); });
  await page.setContent("<!doctype html><body style='margin:0'></body>");
  const result = await page.evaluate((html) => new Promise((resolve) => {
    const f = document.createElement("iframe");
    f.setAttribute("sandbox", "allow-scripts");
    f.style.cssText = "width:840px;height:560px;border:0";
    addEventListener("message", (e) => { f.style.height = Math.max(80, e.data.height) + "px"; resolve(e.data); });
    setTimeout(() => resolve({ errs: ["render timed out"], empty: 0, height: 0 }), 8000);
    f.srcdoc = html;
    document.body.appendChild(f);
  }), doc);
  const errors = [...new Set(result.errs)];
  errors.push(...requests.map((u) => `network access attempted: ${u}`));
  if (result.empty) errors.push(`${result.empty} of ${samples.length} samples rendered nothing`);
  if (!errors.length) await page.locator("iframe").screenshot({ path: path.join(outDir, "screenshot.png") });
  gate("render", errors);
} finally {
  await browser.close();
}
finish();
