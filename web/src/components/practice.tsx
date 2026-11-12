import { Fragment, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Lightbulb, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { exported, get, readEvents, send, type Block, type Gpu } from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { CodeEditor } from "./code-editor";
import { Md, MdLine } from "./md";

type P<T = any> = { data: T; cid: number; block: Block };
type Blank = { answers: string[]; regex?: string; hint: string };

const norm = (s: string) => s.trim().replace(/\s+/g, " ").toLowerCase();

/** Accepted when it equals an answer (case and spacing ignored) or the whole of it matches the blank's regex. */
function accepts(b: Blank, value: string) {
  if (b.answers.some((a) => norm(a) === norm(value))) return true;
  try { return !!b.regex && new RegExp(`^(?:${b.regex})$`, "i").test(value.trim()); } catch { return false; }
}

/** Text or code with gaps; each gap is checked against its accepted answers, case and spacing ignored. */
export function FillBlanks({ data, cid, block }: P<{ title: string; task?: string; language: string; template: string; blanks: Blank[]; explanation: string }>) {
  const [values, setValues] = useState<string[]>(data.blanks.map(() => ""));
  const [checked, setChecked] = useState(false);
  const [shown, setShown] = useState<Set<number>>(new Set());
  const ok = (i: number) => accepts(data.blanks[i], values[i]);
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
      {data.task && <div className="mt-1 text-[0.95rem]"><Md>{data.task}</Md></div>}
      {data.language ? <pre className="mt-2 overflow-x-auto rounded-md bg-muted px-4 py-3 font-mono text-[0.85rem] leading-loose">{body}</pre>
                     : <p className="mt-2 whitespace-pre-wrap leading-loose">{body}</p>}
      {missed.map((i) => data.blanks[i].hint && (
        <p key={i} className="mt-1 flex gap-2 text-sm"><Lightbulb className="mt-0.5 size-4 shrink-0 text-warn" />Blank {i + 1}: {data.blanks[i].hint}</p>))}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => {
          setChecked(true);  // a gap that was shown counts as missed
          if (!exported) send(`/api/courses/${cid}/blocks/${block.id}/outcome`,
            { score: data.blanks.filter((_, i) => ok(i) && !shown.has(i)).length / data.blanks.length }).catch(() => {});
        }}>Check</Button>
        {missed.length > 0 && <Button size="sm" variant="outline" onClick={() => setShown(new Set([...shown, missed[0]]))}>Show blank {missed[0] + 1}</Button>}
        {all && <span className="flex items-center gap-1 text-sm text-ok"><Check className="size-4" />All correct</span>}
      </div>
      {all && data.explanation && <div className="mt-2 text-sm"><Md>{data.explanation}</Md></div>}
    </div>
  );
}

type Grade = { correct: boolean; feedback: string; hint: string };

/** Starter code to complete in an editor; the answer is graded by the model, hints go from written to model-made. */
type CodeData = { title: string; task: string; language: string; starter: string; solution: string; hints: string[]; blanks?: Blank[] };

const Solution = ({ code }: { code: string }) => (
  <details className="mt-3 rounded-md border border-border/80">
    <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground">Reference solution</summary>
    <pre className="overflow-x-auto border-t border-border/80 px-3 py-2 font-mono text-[0.85rem]">{code}</pre>
  </details>
);

/** Code with blanks is checked by match, like fill_blanks; free-form code goes to the model grader. */
export function CodeExercise(props: P<CodeData>) {
  const { data } = props;
  if (!data.blanks?.length) return exported ? <ExportedCode data={data} /> : <FreeCode {...props} />;
  return (
    <div>
      <Md>{data.task}</Md>
      <FillBlanks {...props} data={{ title: data.title, language: data.language || "text", template: data.starter, blanks: data.blanks, explanation: "" }} />
      <Solution code={data.solution} />
    </div>
  );
}

/** In a standalone export there is no grader: the learner writes code, uses the written hints, and compares with the solution. */
function ExportedCode({ data }: { data: CodeData }) {
  const [code, setCode] = useState(data.starter);
  const [shown, setShown] = useState(0);
  return (
    <div>
      <h4 className="font-medium"><MdLine>{data.title}</MdLine></h4>
      <Md>{data.task}</Md>
      <CodeEditor value={code} onChange={setCode} label={`${data.language} answer`} language={data.language} />
      {data.hints.slice(0, shown).map((h, i) => <div key={i} className="mt-2 flex gap-2 text-sm"><Lightbulb className="mt-1 size-4 shrink-0 text-warn" /><Md>{h}</Md></div>)}
      <div className="mt-3 flex flex-wrap gap-2">
        {shown < data.hints.length && <Button size="sm" variant="outline" onClick={() => setShown(shown + 1)}>Hint {shown + 1} of {data.hints.length}</Button>}
        <Button size="sm" variant="ghost" onClick={() => setCode(data.starter)}>Reset</Button>
      </div>
      <Solution code={data.solution} />
    </div>
  );
}

function FreeCode({ data, cid, block }: P<CodeData>) {
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
    setError("");
    let text = "";
    const k = hints.length;
    try {  // past the written hints, the tutor coaches on the current code; it never sees the solution
      const res = await fetch(`/api/courses/${cid}/tutor`, { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: "Give me one short hint for the next thing to fix in my code. Do not give the answer.", block_id: block.id, code }) });
      if (!res.ok) throw new Error(String(res.status));
      await readEvents(res, (ev, d) => {
        if (ev === "token") { text += d.text; setHints((h) => [...h.slice(0, k), text]); }
        if (ev === "error") throw new Error(d.message);
      });
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
      <Solution code={data.solution} />
    </div>
  );
}

type Written = { text: string; files: number; subject: string;
  grade: { total: number; max: number; transcription: string; steps: { step: string; points: number; awarded: number; comment: string }[] } | null };

/** The learner's answer to an exercise: typed (Markdown and $LaTeX$, with a preview) or uploaded (photos or a tablet PDF),
 * kept per Block, and graded against the exercise's steps. Opens on Upload for a theoretical Course, Type otherwise. */
export function WrittenAnswer({ cid, block }: { cid: number; block: Block }) {
  const url = `/api/courses/${cid}/blocks/${block.id}/written`;
  const qc = useQueryClient();
  const { data: w } = useQuery({ queryKey: ["written", block.id], queryFn: () => get<Written>(url), enabled: !exported });
  const { data: sys } = useQuery({ queryKey: ["system"], queryFn: () => get<{ model: string | null; gpu: Gpu | null }>("/api/system"), enabled: !exported });
  const [text, setText] = useState<string | null>(null);
  const [busy, setBusy] = useState<"" | "upload" | "grade">("");
  const [error, setError] = useState("");
  const value = text ?? w?.text ?? "";
  useEffect(() => {  // saved as you type
    if (text === null || exported) return;
    const t = setTimeout(() => send<Written>(url, { text }, "PUT").then((r) => qc.setQueryData(["written", block.id], r)).catch(() => {}), 600);
    return () => clearTimeout(t);
  }, [text]);
  const act = async (kind: "upload" | "grade", call: () => Promise<Written>) => {
    setBusy(kind);
    setError("");
    try { qc.setQueryData(["written", block.id], await call()); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(""); }
  };
  const uploadFiles = (files: FileList | null) => act("upload", async () => {
    let r = w as Written;
    for (const f of Array.from(files ?? [])) { const body = new FormData(); body.append("file", f); r = await send<Written>(`${url}/files`, body); }
    return r;
  });
  const why = sys && !sys.model ? "No model is set up to grade it" : !value.trim() && !w?.files ? "Type or upload an answer first" : "";
  if (exported) return <Textarea className="mt-3" rows={6} aria-label="Your answer" placeholder="Write your answer here…" />;
  if (!w) return null;
  return (
    <div className="mt-3">
      <Tabs defaultValue={w.subject === "theoretical" ? "upload" : "type"}>
        <TabsList><TabsTrigger value="type">Type</TabsTrigger><TabsTrigger value="upload">Upload{w.files ? ` (${w.files})` : ""}</TabsTrigger></TabsList>
        <TabsContent value="type">
          <Textarea rows={6} aria-label="Your answer" placeholder="Write your answer: Markdown, and $math$ in LaTeX…" value={value} onChange={(e) => setText(e.target.value)} />
          {/\$/.test(value) && <div className="mt-2 rounded-md border border-dashed border-border px-3 py-1 text-sm"><Md>{value}</Md></div>}
        </TabsContent>
        <TabsContent value="upload" className="space-y-2">
          <label className="flex cursor-pointer items-center gap-2 rounded-md border border-dashed border-input px-3 py-4 text-sm text-muted-foreground hover:bg-accent">
            <Upload className="size-4" aria-hidden />{busy === "upload" ? "Uploading…" : "Photos of your paper, tablet ink as an image, or a PDF"}
            <input type="file" multiple accept="image/png,image/jpeg,image/webp,application/pdf" className="sr-only" onChange={(e) => uploadFiles(e.target.files)} />
          </label>
          {w.files > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              {Array.from({ length: w.files }, (_, i) => <a key={i} href={`${url}/files/${i}`} target="_blank" rel="noreferrer">
                <img src={`${url}/files/${i}`} alt={`Page ${i + 1} of your answer`} className="h-20 rounded border border-border object-cover" /></a>)}
              <Button size="sm" variant="ghost" onClick={() => act("upload", () => send<Written>(`${url}/files`, undefined, "DELETE"))}>Remove</Button>
            </div>
          )}
        </TabsContent>
      </Tabs>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" disabled={!!busy || !!why}
                title={why || undefined}
                onClick={() => act("grade", async () => { if (text !== null) await send(url, { text: value }, "PUT"); return send<Written>(`${url}/grade`); })}>
          {busy === "grade" ? "Grading…" : w.grade ? "Grade it again" : "Grade it"}</Button>
        {why && !busy && <span className="text-sm text-muted-foreground">{why}</span>}
        {!why && (sys?.gpu?.util ?? 0) >= 90 && <span className="text-sm text-muted-foreground">The GPU is busy: grading waits for a free lane.</span>}
        {error && <span role="alert" className="text-sm text-destructive">{error}</span>}
      </div>
      {w.grade && (
        <div role="status" className="mt-2 space-y-1 rounded-md bg-muted/60 px-3 py-2 text-sm">
          <p className="font-medium tabular">{w.grade.total} / {w.grade.max}</p>
          {w.grade.steps.map((s, i) => (
            <div key={i} className="flex gap-2">
              {s.awarded >= s.points ? <Check className="mt-0.5 size-4 shrink-0 text-ok" /> : <X className="mt-0.5 size-4 shrink-0 text-destructive" />}
              <span><MdLine>{s.step}</MdLine>: <span className="text-muted-foreground">{s.comment}</span></span>
            </div>
          ))}
          {w.grade.transcription && <details><summary className="cursor-pointer text-muted-foreground">What the model read</summary><Md>{w.grade.transcription}</Md></details>}
        </div>
      )}
    </div>
  );
}

/** Work on paper, then reveal the correction one step at a time and mark yourself. */
export function HandCorrection({ steps, correction, cid, block, intro = "Work it on paper first, then compare step by step." }:
  { steps: string[]; correction: string; cid: number; block: Block; intro?: string }) {
  const [n, setN] = useState(0);
  const [mark, setMark] = useState<string | null>(null);
  const done = n > steps.length;
  const rate = (m: string) => { setMark(m); if (!exported) send(`/api/courses/${cid}/blocks/${block.id}/self-mark`, { mark: m }).catch(() => {}); };
  return (
    <div className="mt-3 space-y-2">
      {n === 0 && <p className="text-sm text-muted-foreground">{intro}</p>}
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
            <div className="whitespace-pre-wrap"><span className="select-none text-[#7ee787]">{prompt} </span>{e.command}</div>
            {e.output && <pre className="whitespace-pre-wrap text-[#a8b0bd]">{e.output}</pre>}
          </div>
        ))}
      </div>
      {data.entries.slice(0, n).map((e, i) => e.note && <div key={i} className="mt-1 flex gap-2 text-sm"><code className="shrink-0 text-muted-foreground">{i + 1}.</code><Md>{e.note}</Md></div>)}
      {n < data.entries.length && <Button size="sm" variant="outline" className="mt-2" onClick={() => setN(n + 1)}>Next command ({n}/{data.entries.length})</Button>}
    </figure>
  );
}
