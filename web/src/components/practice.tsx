import { Fragment, useState } from "react";
import { Check, Lightbulb, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { send, type Block } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CodeEditor } from "./code-editor";
import { Md, MdLine } from "./md";

type P<T = any> = { data: T; cid: number; block: Block };
type Blank = { answers: string[]; hint: string };

const norm = (s: string) => s.trim().replace(/\s+/g, " ").toLowerCase();

/** Text or code with gaps; each gap is checked against its accepted answers, case and spacing ignored. */
export function FillBlanks({ data }: P<{ title: string; language: string; template: string; blanks: Blank[]; explanation: string }>) {
  const [values, setValues] = useState<string[]>(data.blanks.map(() => ""));
  const [checked, setChecked] = useState(false);
  const [shown, setShown] = useState<Set<number>>(new Set());
  const ok = (i: number) => data.blanks[i].answers.some((a) => norm(a) === norm(values[i]));
  const parts = data.template.split(/\[\[(\d+)\]\]/);
  const all = checked && data.blanks.every((_, i) => ok(i));
  const gap = (i: number) => {
    const b = data.blanks[i], width = Math.max(4, ...b.answers.map((a) => a.length)) + 2;
    return (
      <input aria-label={`Blank ${i + 1}`} value={shown.has(i) ? b.answers[0] : values[i]} readOnly={shown.has(i)}
        onChange={(e) => { setValues(values.map((v, k) => (k === i ? e.target.value : v))); setChecked(false); }}
        style={{ width: `${width}ch` }}
        className={cn("mx-0.5 rounded border bg-background px-1 font-mono text-[0.9em] outline-none focus:ring-2 focus:ring-ring",
          shown.has(i) ? "border-border text-muted-foreground" : checked ? (ok(i) ? "border-ok bg-ok/10" : "border-destructive bg-destructive/10") : "border-input")} />
    );
  };
  const body = parts.map((p, k) => (k % 2 ? <Fragment key={k}>{gap(Number(p) - 1)}</Fragment>
    : data.language ? <Fragment key={k}>{p}</Fragment> : <MdLine key={k}>{p}</MdLine>));
  const missed = checked ? data.blanks.map((_, i) => i).filter((i) => !ok(i) && !shown.has(i)) : [];
  return (
    <div>
      <h4 className="font-medium"><MdLine>{data.title}</MdLine></h4>
      {data.language ? <pre className="mt-2 overflow-x-auto rounded-md bg-muted px-4 py-3 font-mono text-[0.85rem] leading-loose">{body}</pre>
                     : <p className="mt-2 whitespace-pre-wrap leading-loose">{body}</p>}
      {missed.map((i) => data.blanks[i].hint && (
        <p key={i} className="mt-1 flex gap-2 text-sm"><Lightbulb className="mt-0.5 size-4 shrink-0 text-warn" />Blank {i + 1}: {data.blanks[i].hint}</p>))}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => setChecked(true)}>Check</Button>
        {missed.length > 0 && <Button size="sm" variant="outline" onClick={() => setShown(new Set([...shown, missed[0]]))}>Show blank {missed[0] + 1}</Button>}
        {all && <span className="flex items-center gap-1 text-sm text-ok"><Check className="size-4" />All correct</span>}
      </div>
      {all && data.explanation && <div className="mt-2 text-sm"><Md>{data.explanation}</Md></div>}
    </div>
  );
}

type Grade = { correct: boolean; feedback: string; hint: string };

/** Starter code to complete in an editor; the answer is graded by the model, hints go from written to model-made. */
export function CodeExercise({ data, cid, block }: P<{ title: string; task: string; language: string; starter: string; solution: string; hints: string[] }>) {
  const [code, setCode] = useState(data.starter);
  const [grade, setGrade] = useState<Grade | null>(null);
  const [hints, setHints] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const check = async () => {
    setBusy(true);
    setError("");
    try {
      setGrade(await send<Grade>(`/api/courses/${cid}/blocks/${block.id}/grade`, { code }));
    } catch {
      setError("Grading is only available once the Chapter is published.");
    } finally {
      setBusy(false);
    }
  };
  const hint = async () => {
    if (hints.length < data.hints.length) return setHints([...hints, data.hints[hints.length]]);
    setBusy(true);
    try {
      const g = await send<Grade>(`/api/courses/${cid}/blocks/${block.id}/grade`, { code });
      setHints([...hints, g.hint || g.feedback]);
    } catch {
      setError("More hints are only available once the Chapter is published.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <h4 className="font-medium"><MdLine>{data.title}</MdLine></h4>
      <Md>{data.task}</Md>
      <CodeEditor value={code} onChange={(v) => { setCode(v); setGrade(null); }} onRun={check} label={`${data.language} answer`} language={data.language} />
      {hints.map((h, i) => <div key={i} className="mt-2 flex gap-2 text-sm"><Lightbulb className="mt-1 size-4 shrink-0 text-warn" /><Md>{h}</Md></div>)}
      {grade && (
        <div role="status" className={cn("mt-3 flex gap-2 rounded-md px-3 py-2 text-sm", grade.correct ? "bg-ok/10" : "bg-destructive/10")}>
          {grade.correct ? <Check className="mt-0.5 size-4 shrink-0 text-ok" /> : <X className="mt-0.5 size-4 shrink-0 text-destructive" />}
          <Md>{grade.feedback}</Md>
        </div>
      )}
      {error && <p className="mt-2 text-sm text-muted-foreground">{error}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" onClick={check} disabled={busy}>{busy ? "Checking…" : "Check"}</Button>
        <Button size="sm" variant="outline" onClick={hint} disabled={busy}>Hint</Button>
        <Button size="sm" variant="ghost" onClick={() => { setCode(data.starter); setGrade(null); }}>Reset</Button>
      </div>
      <details className="mt-3 rounded-md border border-border/80">
        <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground">Reference solution</summary>
        <pre className="overflow-x-auto border-t border-border/80 px-3 py-2 font-mono text-[0.85rem]">{data.solution}</pre>
      </details>
    </div>
  );
}

/** Work on paper, then reveal the correction one step at a time and mark yourself. */
export function HandCorrection({ steps, correction, cid, block }: { steps: string[]; correction: string; cid: number; block: Block }) {
  const [n, setN] = useState(0);
  const [mark, setMark] = useState<string | null>(null);
  const done = n > steps.length;
  const rate = (m: string) => { setMark(m); send(`/api/courses/${cid}/blocks/${block.id}/self-mark`, { mark: m }).catch(() => {}); };
  return (
    <div className="mt-3 space-y-2">
      {n === 0 && <p className="text-sm text-muted-foreground">Work it on paper first, then compare step by step.</p>}
      {steps.slice(0, n).map((s, i) => <div key={i} className="flex gap-3 border-l border-border pl-3"><span className="tabular text-sm text-muted-foreground">{i + 1}</span><Md>{s}</Md></div>)}
      {done && <div className="rounded-md bg-muted/60 px-3 py-2"><Md>{correction}</Md></div>}
      {!done ? <Button size="sm" variant="outline" onClick={() => setN(n + 1)}>{n < steps.length ? `Show step ${n + 1} of ${steps.length}` : "Show the answer"}</Button>
        : mark ? <p className="text-sm text-muted-foreground">Marked: {mark === "got" ? "got it" : mark}</p>
        : <div className="flex flex-wrap items-center gap-2 text-sm"><span>How did you do?</span>
            {[["got", "Got it"], ["partly", "Partly"], ["missed", "Missed it"]].map(([m, l]) => <Button key={m} size="sm" variant="outline" onClick={() => rate(m)}>{l}</Button>)}</div>}
    </div>
  );
}

/** A shell session, one command at a time. */
export function Terminal({ data }: P<{ title: string; shell: string; entries: { command: string; output: string; note: string }[] }>) {
  const [n, setN] = useState(1);
  const prompt = data.shell === "powershell" ? "PS>" : "$";
  return (
    <figure>
      {data.title && <h4 className="mb-2 font-medium"><MdLine>{data.title}</MdLine></h4>}
      <div className="overflow-x-auto rounded-md bg-[#16181d] px-4 py-3 font-mono text-[0.85rem] leading-relaxed text-[#e6e6e6]">
        {data.entries.slice(0, n).map((e, i) => (
          <div key={i} className={cn(i > 0 && "mt-3")}>
            <div><span className="select-none text-[#7ee787]">{prompt} </span>{e.command}</div>
            {e.output && <pre className="whitespace-pre-wrap text-[#a8b0bd]">{e.output}</pre>}
          </div>
        ))}
      </div>
      {data.entries.slice(0, n).map((e, i) => e.note && <div key={i} className="mt-1 flex gap-2 text-sm"><code className="shrink-0 text-muted-foreground">{i + 1}.</code><Md>{e.note}</Md></div>)}
      {n < data.entries.length && <Button size="sm" variant="outline" className="mt-2" onClick={() => setN(n + 1)}>Next command ({n}/{data.entries.length})</Button>}
    </figure>
  );
}
