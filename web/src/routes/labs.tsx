import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, Play } from "lucide-react";
import { CodeEditor } from "@/components/code-editor";
import { Md } from "@/components/md";
import { Button } from "@/components/ui/button";
import { get, send } from "@/lib/api";
import { cn } from "@/lib/utils";
import { errText, Page } from "./home";
import { useCid } from "./run";

type LabStep = { id: number; position: number; statement: string; starter: string; hints: string[]; hints_left: number; passed: boolean; gave_up: boolean; solution: string | null };
type Lab = { id: number; title: string; intro: string; flags: { step: number; statement: string; errors: string[] }[]; steps: LabStep[]; kernel_running: boolean };
type Out = { output_type: string; text?: string | string[]; data?: Record<string, string | string[]>; ename?: string; evalue?: string; traceback?: string[] };

export function Labs() {
  const cid = useCid();
  const { data = [] } = useQuery({ queryKey: ["labs", cid], queryFn: () => get<{ id: number; title: string; steps: number; passed: number }[]>(`/api/courses/${cid}/labs`) });
  return (
    <Page title="Labs">
      {!data.length && <p className="text-muted-foreground">No Lab in this Course.</p>}
      <ul className="divide-y divide-border border-y border-border">
        {data.map((l) => (
          <li key={l.id}><Link to="/c/$cid/labs/$lid" params={{ cid: String(cid), lid: String(l.id) }} className="flex justify-between py-3 hover:text-primary">
            <span className="font-medium">{l.title}</span><span className="tabular text-sm text-muted-foreground">{l.passed} / {l.steps} Steps</span></Link></li>
        ))}
      </ul>
    </Page>
  );
}

const join = (t?: string | string[]) => (Array.isArray(t) ? t.join("") : t ?? "");
const stripAnsi = (s: string) => s.replace(/\x1b\[[0-9;]*m/g, "");

function Output({ o }: { o: Out }) {
  if (o.output_type === "stream") return <pre className="whitespace-pre-wrap">{join(o.text)}</pre>;
  if (o.output_type === "error") return <pre className="whitespace-pre-wrap text-destructive">{stripAnsi((o.traceback ?? []).join("\n")) || `${o.ename}: ${o.evalue}`}</pre>;
  const png = o.data?.["image/png"];
  if (png) return <img src={`data:image/png;base64,${join(png)}`} alt="Plot output" className="max-w-full bg-white" />;
  return <pre className="whitespace-pre-wrap">{join(o.data?.["text/plain"])}</pre>;
}

/** One WebSocket to the Lab's kernel; runs are queued one at a time by the server. */
function useKernel(cid: number, lid: number) {
  const ws = useRef<WebSocket | null>(null);
  const waiting = useRef<{ onOut: (o: Out) => void; done: (err: unknown) => void } | null>(null);
  useEffect(() => () => ws.current?.close(), []);
  const open = () => new Promise<WebSocket>((ok, fail) => {
    if (ws.current?.readyState === WebSocket.OPEN) return ok(ws.current);
    const s = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/courses/${cid}/labs/${lid}/run`);
    s.onopen = () => ok(s);
    s.onerror = () => fail(new Error("couldn't reach the kernel"));
    s.onclose = () => { waiting.current?.done({ evalue: "the kernel connection closed" }); waiting.current = null; ws.current = null; };
    s.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.output) waiting.current?.onOut(m.output);
      if (m.done) { waiting.current?.done(m.error); waiting.current = null; }
    };
    ws.current = s;
  });
  return async (code: string, onOut: (o: Out) => void) => {
    const s = await open();
    return new Promise<unknown>((done) => { waiting.current = { onOut, done }; s.send(JSON.stringify({ code })); });
  };
}

function StepCell({ cid, lid, step, run, onChange }: { cid: number; lid: number; step: LabStep; run: ReturnType<typeof useKernel>; onChange: () => void }) {
  const [code, setCode] = useState(step.starter);
  const [out, setOut] = useState<Out[]>([]);
  const [busy, setBusy] = useState<"run" | "check" | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const base = `/api/courses/${cid}/labs/${lid}/steps/${step.id}`;
  const exec = async () => {
    setBusy("run"); setOut([]); setMsg(null);
    try { await run(code, (o) => setOut((x) => [...x, o])); } catch (e) { setMsg(String(e)); } finally { setBusy(null); }
  };
  const check = async () => {
    setBusy("check"); setMsg(null);
    try {
      const r = await send<{ passed: boolean; message: string | null }>(`${base}/check`);
      setMsg(r.passed ? null : r.message ?? "not yet"); onChange();
    } catch (e) { setMsg(errText(e)); } finally { setBusy(null); }
  };
  return (
    <li className="py-6" data-step={step.position + 1}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="font-semibold">Step {step.position + 1}</h2>
        {step.passed ? <span className="flex items-center gap-1 text-sm text-ok"><Check className="size-4" />Passed</span> : step.gave_up && <span className="text-sm text-muted-foreground">Solution shown</span>}
      </div>
      <div className="prose-cf mt-1"><Md>{step.statement}</Md></div>
      <CodeEditor value={code} onChange={setCode} onRun={exec} label={`Code for step ${step.position + 1}`} />
      {out.length > 0 && <div className="mt-2 max-h-96 overflow-auto rounded-md border border-border p-3 font-mono text-xs">{out.map((o, i) => <Output key={i} o={o} />)}</div>}
      {msg && <p className="mt-2 text-sm text-destructive">{msg}</p>}
      {step.hints.map((h, i) => <div key={i} className="mt-2 rounded-md bg-warn/12 px-3 py-2 text-sm"><Md>{h}</Md></div>)}
      {step.solution && <pre className="mt-2 overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs">{step.solution}</pre>}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" onClick={exec} disabled={!!busy}><Play className="size-4" />{busy === "run" ? "Running…" : "Run"}</Button>
        <Button size="sm" variant="outline" onClick={check} disabled={!!busy || step.passed}>{busy === "check" ? "Checking…" : "Check"}</Button>
        {step.hints_left > 0 && !step.passed && <Button size="sm" variant="ghost" onClick={() => send(`${base}/hint`).then(onChange)}>Hint</Button>}
        {!step.passed && !step.gave_up && <Button size="sm" variant="ghost" onClick={() => send(`${base}/give-up`).then(onChange)}>Show the solution</Button>}
      </div>
    </li>
  );
}

export function LabView() {
  const cid = useCid();
  const lid = Number((useParams({ strict: false }) as { lid: string }).lid);
  const qc = useQueryClient();
  const { data: lab } = useQuery({ queryKey: ["lab", cid, lid], queryFn: () => get<Lab>(`/api/courses/${cid}/labs/${lid}`) });
  const run = useKernel(cid, lid);
  if (!lab) return null;
  const refresh = () => qc.invalidateQueries({ queryKey: ["lab", cid, lid] });
  return (
    <Page>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="font-display text-2xl font-semibold">{lab.title}</h1>
        <a href={`/api/courses/${cid}/labs/${lid}/notebook`} className={cn("inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground")}><Download className="size-4" />Notebook</a>
      </div>
      <div className="prose-cf mt-2"><Md>{lab.intro}</Md></div>
      {lab.flags.map((f) => <p key={f.step} className="mt-2 text-sm text-warn" title={f.errors.join("\n")}>Step {f.step} of the TP was left out: its Check couldn't be proven ({f.statement})</p>)}
      <p className="mt-2 text-xs text-muted-foreground">Code runs in an isolated kernel with no network. Shift+Enter runs a cell.</p>
      <ol className="mt-4 divide-y divide-border border-t border-border">
        {lab.steps.map((s) => <StepCell key={s.id} cid={cid} lid={lid} step={s} run={run} onChange={refresh} />)}
      </ol>
    </Page>
  );
}
