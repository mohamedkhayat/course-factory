// LaTeX to speech for Listen: `node speech.mjs` reads {"locale": "en"|"fr", "items": [latex...]} on stdin and prints a list with the
// spoken text of each formula, or null for one it can't turn into words. KaTeX makes the MathML, the Speech Rule Engine speaks it.
import katex from "katex";
import SRE from "speech-rule-engine";

const { locale, items } = JSON.parse(await new Promise((ok) => { let s = ""; process.stdin.on("data", (c) => (s += c)).on("end", () => ok(s)); }));
await SRE.setupEngine({ locale, domain: "clearspeak", modality: "speech" });
const speak = (latex) => {
  try {
    const mml = katex.renderToString(latex, { output: "mathml", throwOnError: true }).match(/<math[\s\S]*<\/math>/)?.[0];
    return (mml && SRE.toSpeech(mml).replace(/\s+/g, " ").trim()) || null;
  } catch { return null; }
};
process.stdout.write(JSON.stringify(items.map(speak)));
