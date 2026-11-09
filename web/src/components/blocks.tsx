import { useEffect, useId, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, BookOpen, Check, Flag, GraduationCap, Info, Lightbulb, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { get, pageUrl, send, type Block, type Citation } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Md, Tex } from "./md";
import { Explorer, Plot } from "./plot";

type P<T = any> = { data: T; cid: number; block: Block };

function Reveal({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <details className="group mt-3 rounded-md border border-border/80">
      <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground">{label}</summary>
      <div className="border-t border-border/80 px-3 py-2">{children}</div>
    </details>
  );
}

const KIND: Record<string, string> = { definition: "Définition", theorem: "Théorème", proposition: "Proposition", lemma: "Lemme", corollary: "Corollaire", property: "Propriété" };

function TheoremBox({ data }: P) {
  return (
    <div className="rounded-md border border-foreground/25 bg-card px-5 py-4">
      <p className="mb-1 font-serif text-base"><span className="font-semibold">{KIND[data.kind] ?? data.kind}</span>{data.title && <span className="text-muted-foreground"> — {data.title}</span>}</p>
      <Md>{data.statement}</Md>
      {data.proof && <Reveal label="Démonstration"><Md>{data.proof}</Md></Reveal>}
    </div>
  );
}

function WorkedExample({ data }: P) {
  return (
    <div>
      <h4 className="font-medium">{data.title}</h4>
      <Md>{data.problem}</Md>
      <ol className="mt-2 space-y-1 border-l border-border pl-4">
        {data.steps.map((s: string, i: number) => <li key={i} className="flex gap-3"><span className="tabular pt-1 text-sm text-muted-foreground">{i + 1}</span><Md>{s}</Md></li>)}
      </ol>
      <Reveal label="Answer"><Md>{data.answer}</Md></Reveal>
    </div>
  );
}

function Exercise({ data }: P) {
  const [shown, setShown] = useState(0);
  return (
    <div>
      <h4 className="font-medium">{data.title}</h4>
      <Md>{data.statement}</Md>
      {data.hints.slice(0, shown).map((h: string, i: number) => (
        <div key={i} className="mt-2 flex gap-2 text-sm"><Lightbulb className="mt-1 size-4 text-warn" /><Md>{h}</Md></div>
      ))}
      <div className="mt-3 flex gap-2">
        {shown < data.hints.length && <Button size="sm" variant="outline" onClick={() => setShown(shown + 1)}>Hint {shown + 1} of {data.hints.length}</Button>}
      </div>
      <Reveal label="Correction"><Md>{data.correction}</Md></Reveal>
    </div>
  );
}

/** One question at a time; answers are recorded so mistakes and Cards follow. */
function Quiz({ data, cid, block }: P) {
  const [i, setI] = useState(0);
  const [chosen, setChosen] = useState<number[]>([]);
  const [result, setResult] = useState<{ correct: boolean; correct_options: number[]; explanation: string } | null>(null);
  const [score, setScore] = useState(0);
  const q = data.questions[i];
  if (!q) return <p className="font-medium">Score: {score} / {data.questions.length} <Button size="sm" variant="ghost" onClick={() => { setI(0); setScore(0); }}>Again</Button></p>;
  const toggle = (k: number) => !result && setChosen(q.multiple ? (chosen.includes(k) ? chosen.filter((c) => c !== k) : [...chosen, k]) : [k]);
  const submit = async () => {
    const r = await send<typeof result>(`/api/courses/${cid}/blocks/${block.id}/answers`, { question: i, chosen });
    setResult(r);
    if (r?.correct) setScore(score + 1);
  };
  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-sm text-muted-foreground">
        <span>Question {i + 1} of {data.questions.length}{q.multiple && " · several answers"}</span>
        <span className="flex gap-1">{data.questions.map((_: unknown, k: number) => <span key={k} className={cn("h-1.5 w-5 rounded-full", k < i ? "bg-primary" : k === i ? "bg-primary/60" : "bg-muted")} />)}</span>
      </div>
      <Md>{q.prompt}</Md>
      <div className="mt-3 grid gap-2" role={q.multiple ? "group" : "radiogroup"}>
        {q.options.map((o: string, k: number) => {
          const right = result?.correct_options.includes(k), picked = chosen.includes(k);
          return (
            <button key={k} type="button" role={q.multiple ? "checkbox" : "radio"} aria-checked={picked} onClick={() => toggle(k)}
              className={cn("flex items-center gap-3 rounded-md border px-3 py-2 text-left transition-colors",
                !result && (picked ? "border-primary bg-primary/8" : "hover:bg-accent"),
                result && right && "border-ok bg-ok/10", result && picked && !right && "border-destructive bg-destructive/10")}>
              <span className={cn("grid size-4 shrink-0 place-items-center border border-current", q.multiple ? "rounded-sm" : "rounded-full")}>
                {picked && <span className={cn("size-2 bg-current", q.multiple ? "rounded-[1px]" : "rounded-full")} />}
              </span>
              <Md className="[&_p]:my-0">{o}</Md>
            </button>
          );
        })}
      </div>
      {result && (
        <div className="mt-3 flex gap-2 rounded-md bg-muted px-3 py-2">
          {result.correct ? <Check className="mt-1 size-4 text-ok" /> : <X className="mt-1 size-4 text-destructive" />}
          <Md>{result.explanation}</Md>
        </div>
      )}
      <div className="mt-3">
        {!result ? <Button size="sm" disabled={!chosen.length} onClick={submit}>Check</Button>
          : <Button size="sm" onClick={() => { setI(i + 1); setChosen([]); setResult(null); }}>{i + 1 < data.questions.length ? "Next question" : "See score"}</Button>}
      </div>
    </div>
  );
}

function KeyFormula({ data }: P) {
  return (
    <div className="rounded-md bg-muted/60 px-5 py-3">
      <p className="text-sm font-medium text-muted-foreground">{data.name}</p>
      <Tex latex={data.latex} />
      <Md>{data.meaning}</Md>
    </div>
  );
}

const TONES = {
  tip: { icon: Lightbulb, label: "Tip", cls: "bg-ok/10 [&>svg]:text-ok" },
  warning: { icon: AlertTriangle, label: "Piège", cls: "bg-warn/12 [&>svg]:text-warn" },
  exam: { icon: GraduationCap, label: "À l'examen", cls: "bg-primary/10 [&>svg]:text-primary" },
  note: { icon: Info, label: "Note", cls: "bg-muted [&>svg]:text-muted-foreground" },
} as const;

function Callout({ data }: P) {
  const t = TONES[data.tone as keyof typeof TONES] ?? TONES.note;
  return (
    <div className={cn("flex gap-3 rounded-md px-4 py-3", t.cls)}>
      <t.icon className="mt-1 size-4 shrink-0" aria-hidden />
      <div><p className="text-sm font-semibold">{t.label}</p><Md>{data.text}</Md></div>
    </div>
  );
}

function Algorithm({ data }: P) {
  return (
    <div className="rounded-md border border-border px-5 py-4">
      <p className="font-semibold">Algorithme — {data.name}</p>
      <div className="mt-1 text-sm"><span className="text-muted-foreground">Entrée : </span><Md className="inline-block">{data.inputs}</Md></div>
      <ol className="my-2 space-y-1">
        {data.steps.map((s: string, i: number) => <li key={i} className="flex gap-3"><span className="tabular pt-1 font-mono text-xs text-muted-foreground">{String(i + 1).padStart(2, "0")}</span><Md>{s}</Md></li>)}
      </ol>
      <div className="text-sm"><span className="text-muted-foreground">Sortie : </span><Md className="inline-block">{data.output}</Md></div>
    </div>
  );
}

const fmt = (v: unknown): string | number => (typeof v === "number" ? +v.toPrecision(6) : Array.isArray(v) ? `(${v.map(fmt).join(", ")})` : String(v));

function Table({ headers, rows, caption }: { headers: string[]; rows: unknown[][]; caption?: string }) {
  return (
    <figure className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead><tr>{headers.map((h) => <th key={h} className="border-b border-foreground/30 px-3 py-1.5 text-left font-semibold">{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i} className="border-b border-border/70">{r.map((c, j) => <td key={j} className="px-3 py-1.5 align-top">{typeof c === "string" ? <Md className="[&_p]:my-0">{c}</Md> : fmt(c)}</td>)}</tr>)}</tbody>
      </table>
      {caption && <figcaption className="mt-2 text-sm text-muted-foreground"><Md>{caption}</Md></figcaption>}
    </figure>
  );
}

function IterationTable({ data }: P) {
  const rows: Record<string, unknown>[] = data.rows ?? [];
  const headers = rows.length ? Object.keys(rows[0]) : [];
  return (
    <div>
      <p className="mb-2 text-sm text-muted-foreground">Méthode {data.method === "newton" ? "de Newton" : "du gradient"} sur <code className="font-mono">f = {data.f}</code>, x₀ = ({data.x0.join(", ")}){data.method === "gradient" && `, pas ${data.step}`}</p>
      <Table headers={headers} rows={rows.map((r) => headers.map((h) => (typeof r[h] === "string" ? r[h] : fmt(r[h]))))} caption={data.caption} />
    </div>
  );
}

function Diagram({ data }: P) {
  const id = "m" + useId().replace(/[^a-zA-Z0-9]/g, "");
  const [svg, setSvg] = useState<string | null>(null);
  const dark = document.documentElement.dataset.theme === "instrument";
  useEffect(() => {
    import("mermaid").then(({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, theme: dark ? "dark" : "neutral", securityLevel: "strict" });
      return mermaid.render(id, data.mermaid);
    }).then((r) => setSvg(r.svg)).catch(() => setSvg(""));
  }, [data.mermaid, id, dark]);
  return (
    <figure>
      {svg === "" ? <pre className="overflow-x-auto font-mono text-sm">{data.mermaid}</pre>
        : <div className="flex justify-center overflow-x-auto [&_svg]:max-w-full" dangerouslySetInnerHTML={{ __html: svg ?? "" }} />}
      {data.caption && <figcaption className="mt-2 text-sm text-muted-foreground"><Md>{data.caption}</Md></figcaption>}
    </figure>
  );
}

function Figure({ data, cid }: P) {
  return (
    <figure>
      <img src={pageUrl(cid, data.source, data.page)} alt={data.caption || `${data.source} page ${data.page}`} className="max-h-[480px] rounded-md border border-border" loading="lazy" />
      <figcaption className="mt-2 text-sm text-muted-foreground"><Md>{data.caption || `${data.source}, p. ${data.page}`}</Md></figcaption>
    </figure>
  );
}

function Code({ data }: P) {
  return (
    <figure>
      <pre className="overflow-x-auto rounded-md bg-muted px-4 py-3 font-mono text-[0.85rem] leading-relaxed"><code>{data.code}</code></pre>
      {data.caption && <figcaption className="mt-2 text-sm text-muted-foreground"><Md>{data.caption}</Md></figcaption>}
    </figure>
  );
}

type Comp = { id: number; name: string; status: string; reviewed: boolean };

/** A model-made Component runs only inside a sandboxed iframe with no network; until approved its Block shows as Markdown. */
export function CustomComponent({ block, comp, height = 160 }: { block: { data: unknown; fallback_markdown?: string; component: string }; comp?: Comp; height?: number }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const live = comp && (comp.status === "approved" || comp.status === "preview");
  const { data: code } = useQuery({ queryKey: ["bundle", comp?.id], enabled: !!live, staleTime: Infinity,
    queryFn: () => fetch(`/api/components/${comp!.id}/bundle.js`).then((r) => r.text()) });
  const [h, setH] = useState(height);
  useEffect(() => {
    const on = (e: MessageEvent) => { if (e.source === ref.current?.contentWindow && e.data?.height) setH(Math.min(1200, e.data.height + 8)); };
    addEventListener("message", on);
    return () => removeEventListener("message", on);
  }, []);
  if (!live || !code) return <Md>{block.fallback_markdown ?? ""}</Md>;
  const style = getComputedStyle(document.documentElement);
  const doc = `<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:">
<style>:root{color-scheme:${style.colorScheme || "light"}}body{margin:0;font:16px ${style.getPropertyValue("--font-read")};color:${style.getPropertyValue("--foreground")};background:transparent}</style><div id=r></div>
<script>${code.replaceAll("</script", "<\\/script")}</script><script>CF.render(document.getElementById("r"),${JSON.stringify(block.data).replaceAll("<", "\\u003c")},function(){});
new ResizeObserver(function(){parent.postMessage({height:document.body.scrollHeight},"*")}).observe(document.body);</script>`;
  return <iframe ref={ref} title={block.component} sandbox="allow-scripts" srcDoc={doc} className="w-full border-0" style={{ height: h }} />;
}

const RENDER: Record<string, (p: P) => React.ReactNode> = {
  theorem_box: TheoremBox, worked_example: WorkedExample, exercise: Exercise, quiz: Quiz, key_formula: KeyFormula,
  callout: Callout, algorithm: Algorithm, iteration_table: IterationTable, plot: ({ data }) => <Plot data={data} />,
  explorer: ({ data }) => <Explorer data={data} />, diagram: Diagram, figure: Figure,
  table: ({ data }) => <Table headers={data.headers} rows={data.rows} caption={data.caption} />, code: Code,
  prose: ({ data }) => <Md>{data.markdown}</Md>,
};

export function useComponents() {
  return useQuery({ queryKey: ["components"], queryFn: () => get<Comp[]>("/api/components") }).data ?? [];
}

export function BlockBody({ block, cid }: { block: Block; cid: number }) {
  const comps = useComponents();
  const R = RENDER[block.component];
  if (R) return <R data={block.data} cid={cid} block={block} />;
  const comp = comps.find((c) => c.name === block.component);
  return (
    <div>
      <CustomComponent block={block} comp={comp?.status === "approved" ? comp : undefined} />
      {comp?.status === "approved" && !comp.reviewed && <p className="mt-1 text-xs text-muted-foreground">Made by local model · not reviewed yet</p>}
    </div>
  );
}

export function PageViewer({ cid, cite, onClose }: { cid: number; cite: Citation | null; onClose: () => void }) {
  return (
    <Dialog open={!!cite} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader><DialogTitle>{cite?.source}, page {cite?.page}</DialogTitle></DialogHeader>
        {cite?.quote && <blockquote className="border-l border-foreground/40 pl-3 font-serif italic">{cite.quote}</blockquote>}
        {cite && <img src={pageUrl(cid, cite.source, cite.page)} alt={`${cite.source} page ${cite.page}`} className="max-h-[70vh] w-full rounded-md border border-border object-contain" />}
      </DialogContent>
    </Dialog>
  );
}

/** A Block as the learner sees it: content, then its Citations and origin, and a way to flag it. */
export function ReaderBlock({ block, cid, onCite }: { block: Block; cid: number; onCite: (c: Citation) => void }) {
  const [flagging, setFlagging] = useState(false);
  const [flagged, setFlagged] = useState(false);
  const flag = async (reason: "wrong" | "unclear") => {
    await send(`/api/courses/${cid}/blocks/${block.id}/flags`, { reason });
    setFlagged(true);
    setFlagging(false);
  };
  return (
    <section className="group/block relative" data-block={block.id}>
      <BlockBody block={block} cid={cid} />
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground opacity-80 transition-opacity group-hover/block:opacity-100">
        {block.citations.map((c, i) => (
          <button key={i} type="button" onClick={() => onCite(c)} className="inline-flex items-center gap-1 underline decoration-dotted hover:text-foreground">
            <BookOpen className="size-3" />{c.source} p.{c.page}
          </button>
        ))}
        <span>{block.origin === "from_source" ? "From source" : "Model-added"}</span>
        <span className="ml-auto flex items-center gap-1">
          {flagged ? <span className="text-warn">Flagged, thanks</span> : flagging ? (
            <>
              <Button size="sm" variant="ghost" className="h-6 px-2 text-xs" onClick={() => flag("wrong")}>Wrong</Button>
              <Button size="sm" variant="ghost" className="h-6 px-2 text-xs" onClick={() => flag("unclear")}>Unclear</Button>
            </>
          ) : (
            <button type="button" onClick={() => setFlagging(true)} className="inline-flex items-center gap-1 hover:text-foreground" aria-label="Flag this Block"><Flag className="size-3" />Flag</button>
          )}
        </span>
      </div>
    </section>
  );
}
