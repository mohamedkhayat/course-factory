import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, BookOpen, Check, ClipboardList, FlaskConical, Folder, Layers, Loader2, Merge, Pause, Scissors, SplitSquareVertical, Timer, TriangleAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { PageViewer } from "@/components/blocks";
import { Md } from "@/components/md";
import { duration, get, pageUrl, readEvents, send, type Citation, type Course, type Gpu } from "@/lib/api";
import { cn } from "@/lib/utils";
import { errText, Page } from "./home";

type Step = { name: string; label: string; gate: boolean; state: "done" | "current" | "waiting" };
type Activity = { step: string; attempt: number; elapsed: number; thinking: string; output: string; inputs: Record<string, string> };
type Run = { status: string; gate: string | null; error: string | null; next?: string[]; pages_read: number; pages_total: number;
  seconds_left?: number | null; gpu?: Gpu | null; pipeline: Step[]; active: boolean; activity: Activity | null; progress?: RunProgressTree };
type PSection = { title: string; state: "waiting" | "writing" | "done" | "skipped"; blocks: number; flagged: number };
type PChapter = { id: number; title: string; sections: PSection[]; done: number; total: number };
type RunProgressTree = { chapters: PChapter[]; pages: number; read: number; sections_done: number; sections_total: number; fraction: number };
type Trace = { id: number; step: string; inputs: string; output: string | null; error: string | null; owner_action: string | null;
  duration_ms: number | null; checks: string | null; created_at: string };

const stepName = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replaceAll("_", " ");
const secs = (ms: number) => (ms < 60_000 ? `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s` : `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`);

/** How many problems a Trace's checks found: every check reports its problems as strings in a list. */
function problems(checks: string | null): number {
  const count = (v: unknown): number => Array.isArray(v) ? v.reduce((n: number, x) => n + (typeof x === "string" ? 1 : count(x)), 0)
    : v && typeof v === "object" ? Object.values(v).reduce((n: number, x) => n + count(x), 0) : 0;
  try { return checks ? count(JSON.parse(checks)) : 0; } catch { return 0; }
}

/** Where the Run is, at an Approval Gate: a slim line of the pipeline. */
function PipelineStrip({ pipeline }: { pipeline: Step[] }) {
  const at = pipeline.findIndex((p) => p.state === "current");
  if (at < 0) return null;
  return (
    <div className="mb-6 flex items-center gap-3 text-xs text-muted-foreground">
      <ol className="flex gap-1" aria-hidden>
        {pipeline.map((p) => <li key={p.name} className={cn("h-1.5 w-4 rounded-full", p.state === "done" ? "bg-primary/60" : p.state === "current" ? "bg-primary" : "bg-border")} />)}
      </ol>
      <span>Step {at + 1} of {pipeline.length}: {pipeline[at].label}. Waiting for you</span>
    </div>
  );
}

/** The transcription inside a step's JSON answer, readable while it is still streaming (the closing quote may not be there yet). */
export function streamedText(raw: string): string {
  const m = /"text"\s*:\s*"/.exec(raw);
  if (!m) return raw.trimStart().startsWith("{") ? "" : raw;
  let body = raw.slice(m.index + m[0].length);
  const end = body.search(/(?<!\\)(?:\\\\)*"/);  // first quote not escaped by a backslash
  if (end >= 0) body = body.slice(0, end + (body.slice(end).match(/^(?:\\\\)*/)?.[0].length ?? 0));
  body = body.replace(/(?<!\\)((?:\\\\)*)\\$/, "$1");  // an escape cut mid-stream
  try { return JSON.parse(`"${body}"`) as string; } catch { return body.replaceAll("\\n", "\n"); }
}

function Tail({ label, live, children, text }: { label: string; live: boolean; text: string; children: React.ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);  // follow new text unless the reader scrolled up
  useEffect(() => { if (box.current && pinned.current) box.current.scrollTop = box.current.scrollHeight; }, [text]);
  return (
    <div className="min-w-0">
      <p className="mb-1.5 flex items-center gap-2 text-xs font-medium text-muted-foreground">{label}
        {live && <span className="size-1.5 animate-pulse rounded-full bg-primary" aria-hidden />}</p>
      <div ref={box} onScroll={(e) => { const el = e.currentTarget; pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24; }}
           className="h-48 overflow-y-auto overscroll-contain rounded-md bg-muted/50 px-4 py-3">
        {text ? children : <span className="text-sm text-muted-foreground">Waiting for the model…</span>}
      </div>
    </div>
  );
}

type MapFile = { name: string; pages: number; role: string | null; read: number; unreadable: number };

/** The model step running now: what it works on, its thinking and its output as they stream in. */
function Now({ cid, a }: { cid: number; a: Activity }) {
  const page = a.inputs.source && a.inputs.page ? { source: a.inputs.source, page: Number(a.inputs.page) } : null;
  const detail = Object.entries(a.inputs).filter(([k, v]) => !["source", "page", "language"].includes(k) && v.length <= 80).slice(0, 3);
  return (
    <section aria-label="What the model is doing">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="flex items-center gap-2 text-lg"><Loader2 className="size-4 animate-spin text-primary" aria-hidden />{stepName(a.step)}</h2>
        {page && <span className="min-w-0 truncate text-sm text-muted-foreground">{page.source}, page {page.page}</span>}
        <span className="tabular ml-auto text-xs text-muted-foreground">{a.elapsed} s{a.attempt > 1 && ` · attempt ${a.attempt} of 3`}</span>
      </div>
      {detail.map(([k, v]) => <p key={k} className="mt-1 truncate text-sm text-muted-foreground"><span className="capitalize">{k.replaceAll("_", " ")}</span>: {v}</p>)}
      <div className={cn("mt-3 grid gap-4", page && "sm:grid-cols-[11rem_minmax(0,1fr)]")}>
        {page && (
          <div className="grid aspect-[1/1.414] w-36 place-items-center self-start rounded-sm bg-muted text-xs text-muted-foreground sm:w-full">
            <span className="col-start-1 row-start-1">Page {page.page}</span>
            <img key={`${page.source}-${page.page}`} src={pageUrl(cid, page.source, page.page)} alt={`${page.source}, page ${page.page}`}
                 onError={(e) => { e.currentTarget.hidden = true; }}
                 className="col-start-1 row-start-1 size-full rounded-sm bg-white object-contain shadow-[0_1px_3px_oklch(0_0_0/0.18)]" />
          </div>
        )}
        <div className="min-w-0 space-y-4">
          <Tail label="Thinking" text={a.thinking} live={!a.output}>
            <p className="max-w-[75ch] whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">{a.thinking}</p>
          </Tail>
          <Tail label={a.step === "read_page" ? "Transcription" : "Output"} text={a.output} live={!!a.output}>
            {a.step === "read_page" ? <Md className="prose-cf !text-[0.95rem]">{streamedText(a.output)}</Md>
              : <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed">{a.output}</pre>}
          </Tail>
        </div>
      </div>
    </section>
  );
}

/** The course as imported: folders, their files, and one cell per page that fills in as the model reads it. */
function CourseMap({ cid, now, live }: { cid: number; now: { source: string; page: number } | null; live: boolean }) {
  const { data } = useQuery({ queryKey: ["map", cid], queryFn: () => get<MapFile[]>(`/api/courses/${cid}/map`), refetchInterval: live ? 3000 : false });
  if (!data?.length) return null;
  const folders = new Map<string, MapFile[]>();
  for (const f of data) {
    const dir = f.name.includes("/") ? f.name.slice(0, f.name.lastIndexOf("/")) : "";
    folders.set(dir, [...(folders.get(dir) ?? []), f]);
  }
  const docs = data.filter((f) => f.pages > 0);
  const done = docs.filter((f) => f.read >= f.pages).length;
  return (
    <section aria-label="Course map">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border pb-2">
        <h2 className="text-lg">Your course</h2>
        <p className="tabular text-sm text-muted-foreground">{folders.size} {folders.size === 1 ? "folder" : "folders"} · {done} of {docs.length} documents read
          {data.length > docs.length && ` · ${data.length - docs.length} other files`}</p>
      </div>
      <div className="divide-y divide-border">
        {[...folders].map(([dir, files]) => {
          const fdocs = files.filter((f) => f.pages > 0), others = files.length - fdocs.length;
          const pages = fdocs.reduce((n, f) => n + f.pages, 0), read = fdocs.reduce((n, f) => n + Math.min(f.read, f.pages), 0);
          return (
            <div key={dir} className="py-3">
              <p className="mb-1.5 flex items-baseline gap-2 text-sm">
                <Folder className="size-3.5 shrink-0 self-center text-muted-foreground" aria-hidden />
                <span className="font-medium">{dir || "Top folder"}</span>
                {pages > 0 && <span className="tabular text-xs text-muted-foreground">{Math.round((100 * read) / pages)}%</span>}
              </p>
              <ul className="space-y-px">
                {fdocs.map((f) => {
                  const reading = now?.source === f.name, complete = f.read >= f.pages;
                  return (
                    <li key={f.name} aria-current={reading ? "true" : undefined}
                        className={cn("grid grid-cols-[minmax(0,15rem)_1fr_auto] items-center gap-3 rounded px-2 py-1 text-sm transition-colors duration-500",
                                      reading && "bg-accent")}>
                      <span className={cn("truncate", !complete && !reading && "text-muted-foreground", reading && "font-medium")} title={f.name}>
                        {f.name.slice(dir ? dir.length + 1 : 0)}
                      </span>
                      <span className="flex flex-wrap gap-[3px]" aria-hidden>
                        {Array.from({ length: f.pages }, (_, i) => {
                          const n = i + 1, here = reading && now?.page === n;
                          return <span key={n} className={cn("size-2.5 rounded-[2px] transition-colors duration-700",
                            here ? "animate-pulse bg-primary ring-2 ring-primary/30" : n <= f.read ? (n > f.read - f.unreadable ? "bg-warn" : "bg-primary") : "bg-border")} />;
                        })}
                      </span>
                      <span className="tabular text-xs text-muted-foreground">
                        {complete ? <Check className="size-3.5 text-ok" aria-label={`${f.pages} pages read`} /> : `${f.read}/${f.pages}`}
                      </span>
                    </li>
                  );
                })}
              </ul>
              {others > 0 && <p className="mt-1 px-2 text-xs text-muted-foreground">+ {others} {others === 1 ? "file" : "files"} with no pages to read ({kinds(files.filter((f) => f.pages === 0))})</p>}
            </div>
          );
        })}
      </div>
    </section>
  );
}

/** The approved outline as it gets written: one bar per Chapter, one cell per Section. */
function Plan({ cid, p }: { cid: number; p: RunProgressTree }) {
  if (!p.sections_total) return null;
  const blocks = p.chapters.reduce((n, c) => n + c.sections.reduce((m, s) => m + s.blocks, 0), 0);
  return (
    <section aria-label="Course plan">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border pb-2">
        <h2 className="text-lg">The plan</h2>
        <p className="tabular text-sm text-muted-foreground">{p.chapters.length} Chapters · {p.sections_done} of {p.sections_total} Sections written · {blocks} Blocks</p>
      </div>
      <ul className="divide-y divide-border">
        {p.chapters.map((c) => {
          const pct = c.total ? Math.round((100 * c.done) / c.total) : 0, flagged = c.sections.reduce((n, s) => n + s.flagged, 0);
          return (
            <li key={c.id} className="py-3">
              <p className="mb-1.5 flex items-baseline gap-2 text-sm">
                <Layers className="size-3.5 shrink-0 self-center text-muted-foreground" aria-hidden />
                {c.done ? <Link to="/c/$cid/review" params={{ cid: String(cid) }} hash={`chapter-${c.id}`} className="font-medium hover:underline">{c.title}</Link>
                        : <span className={cn("font-medium", !c.total && "text-muted-foreground line-through")}>{c.title}</span>}
                <span className="tabular ml-auto text-xs text-muted-foreground">{c.total ? `${c.done}/${c.total} · ${pct}%` : "skipped"}
                  {flagged > 0 && <span className="text-destructive"> · {flagged} flagged</span>}</span>
              </p>
              <Progress value={pct} aria-label={`${c.title}: ${pct}%`} className="h-1" />
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {c.sections.map((s, i) => (
                  <li key={i} title={`${s.title}: ${s.state}${s.blocks ? `, ${s.blocks} Blocks` : ""}`}
                      className={cn("max-w-56 truncate rounded px-1.5 py-0.5 text-xs transition-colors duration-500",
                        s.state === "done" ? (s.flagged ? "bg-destructive/15 text-destructive" : "bg-primary/15 text-foreground")
                          : s.state === "writing" ? "animate-pulse bg-primary text-primary-foreground" : "bg-border/60 text-muted-foreground")}>
                    {s.title}
                  </li>
                ))}
              </ul>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const kinds = (files: MapFile[]) => [...new Set(files.map((f) => f.name.includes(".") ? f.name.slice(f.name.lastIndexOf(".")) : "no extension"))].slice(0, 5).join(", ");

function Feed({ cid, running }: { cid: number; running: boolean }) {
  const { data = [] } = useQuery({ queryKey: ["traces", cid], queryFn: () => get<Trace[]>(`/api/courses/${cid}/traces?limit=15`), refetchInterval: running ? 4000 : false });
  const steps = data.filter((t) => !t.owner_action);
  if (!steps.length) return null;
  return (
    <section>
      <h2 className="border-b border-border pb-2 text-lg">Recent model steps</h2>
      <ul className="divide-y divide-border">
        {steps.map((t) => {
          const inp = (() => { try { return JSON.parse(t.inputs) as Record<string, unknown>; } catch { return {}; } })();
          const where = typeof inp.source === "string" && inp.page ? `${inp.source}, page ${inp.page}` : typeof inp.section === "string" ? inp.section : "";
          const bad = problems(t.checks);
          return (
            <li key={t.id}>
              <details className="group py-2">
                <summary className="flex cursor-pointer list-none items-center gap-3 rounded text-sm hover:text-foreground">
                  {t.error ? <X className="size-4 shrink-0 text-destructive" aria-label="failed" />
                    : bad ? <TriangleAlert className="size-4 shrink-0 text-warn" aria-label={`${bad} check problems`} />
                    : <Check className="size-4 shrink-0 text-ok" aria-label="passed" />}
                  <span className="font-medium">{stepName(t.step)}</span>
                  <span className="min-w-0 flex-1 truncate text-muted-foreground">{where}</span>
                  {bad > 0 && <span className="tabular shrink-0 text-xs text-warn">{bad} flagged</span>}
                  {t.duration_ms != null && <span className="tabular shrink-0 text-xs text-muted-foreground">{secs(t.duration_ms)}</span>}
                </summary>
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-muted/60 px-3 py-2 font-mono text-xs text-muted-foreground">
                  {t.error ?? t.output?.slice(0, 3000) ?? ""}
                </pre>
              </details>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** The Run between gates: the pipeline, the course and how much of it is read, the step running now, and what the model just did. */
function RunProgress({ cid, run, onRetry, retrying, retryError }: { cid: number; run: Run; onRetry: () => void; retrying: boolean; retryError: unknown }) {
  const failed = run.status === "failed", paused = run.status === "running" && !run.active, live = run.status === "running" && run.active;
  const a = run.activity;
  const now = a?.inputs.source && a.inputs.page ? { source: a.inputs.source, page: Number(a.inputs.page) } : null;
  const at = run.pipeline.findIndex((p) => p.state === "current");
  return (
    <div className="mb-12 grid gap-x-10 gap-y-8 lg:grid-cols-[15rem_minmax(0,1fr)]">
      <ol className="hidden self-start lg:sticky lg:top-6 lg:block" aria-label="Pipeline">
        {run.pipeline.map((p, i) => {
          const current = p.state === "current", last = i === run.pipeline.length - 1;
          return (
            <li key={p.name} aria-current={current ? "step" : undefined} className="relative flex gap-3 pb-3 text-sm">
              {!last && <span className={cn("absolute top-5 bottom-0 left-[7.5px] w-px", p.state === "done" ? "bg-ok/50" : "bg-border")} aria-hidden />}
              <span className="relative mt-0.5 grid size-4 shrink-0 place-items-center bg-background">
                {p.state === "done" ? <Check className="size-4 text-ok" aria-label="done" />
                  : current && failed ? <X className="size-4 text-destructive" aria-label="stopped" />
                  : current && !paused ? <Loader2 className="size-4 animate-spin text-primary" aria-label="running" />
                  : p.gate ? <Pause className="size-3.5 text-muted-foreground" aria-label="Approval Gate" />
                  : <span className={cn("size-2 rounded-full border", current ? "border-primary" : "border-muted-foreground/50")} />}
              </span>
              <span className={cn("leading-5", p.state === "waiting" && "text-muted-foreground", current && "font-medium")}>
                {p.label}
                {p.gate && p.state === "waiting" && <span className="sr-only"> (Approval Gate)</span>}
              </span>
            </li>
          );
        })}
      </ol>
      <div className="min-w-0 space-y-10" aria-live="polite">
        <header className="space-y-3">
          <h2 className="text-2xl">{at >= 0 ? run.pipeline[at].label : "Starting"}</h2>
          <div className="space-y-2">
            {run.pages_total > 0 && <Progress value={100 * (run.progress?.fraction ?? run.pages_read / run.pages_total)} aria-label="Overall progress" />}
            <p className="tabular flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted-foreground">
                {at >= 0 && <span>Step {at + 1} of {run.pipeline.length}</span>}
                {run.pages_total > 0 && <span><span className="font-medium text-foreground">{Math.round(100 * (run.progress?.fraction ?? run.pages_read / run.pages_total))}%</span> overall</span>}
                {run.pages_total > 0 && <span><span className="font-medium text-foreground">{run.pages_read}</span> of {run.pages_total} pages read</span>}
                {(run.progress?.sections_total ?? 0) > 0 && <span><span className="font-medium text-foreground">{run.progress?.sections_done}</span> of {run.progress?.sections_total} Sections written</span>}
                {live && <span>{run.seconds_left != null ? `${duration(run.seconds_left)} to the next Approval Gate` : "Estimating time left…"}</span>}
                {live && run.gpu && <span>GPU {run.gpu.util}% · {(run.gpu.mem_used_mb / 1024).toFixed(1)} of {(run.gpu.mem_total_mb / 1024).toFixed(0)} GB</span>}
            </p>
          </div>
        </header>
        {failed && (
          <div role="alert" className="rounded-lg bg-destructive/10 px-4 py-3">
            <p className="font-medium">The Run stopped</p>
            <p className="mt-1 break-words font-mono text-xs">{run.error}</p>
            <Button className="mt-3" size="sm" onClick={onRetry} disabled={retrying}>Retry from where it stopped</Button>
          </div>
        )}
        {paused && (
          <div className="rounded-lg bg-accent px-4 py-3">
            <p className="font-medium">The Run is paused</p>
            <p className="mt-1 text-sm text-muted-foreground">The app stopped in the middle of a step. Nothing is lost: it picks up from the last finished step.</p>
            <Button className="mt-3" size="sm" onClick={onRetry} disabled={retrying}>Resume</Button>
          </div>
        )}
        {!!retryError && <p className="text-sm text-destructive">{errText(retryError)}</p>}
        {a ? <Now cid={cid} a={a} /> : live && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" aria-hidden />Working without the model (copying, indexing)…</p>
        )}
        {run.progress && <Plan cid={cid} p={run.progress} />}
        <CourseMap cid={cid} now={now} live={live} />
        <Feed cid={cid} running={run.status === "running"} />
      </div>
    </div>
  );
}
type Source = { id: number; name: string; pages: number; role: string; paired_with: number | null; excluded: boolean };
const ROLES = ["course notes", "exercise sheet", "lab", "past exam", "correction", "personal notes", "data"];
const PRIORITIES = ["focus", "normal", "light", "skip"] as const;

export const useCid = () => Number((useParams({ strict: false }) as { cid: string }).cid);

/** Live Run status over SSE; falls back to the last value if the stream ends. */
function useRun(cid: number) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["run", cid], queryFn: () => get<Run>(`/api/courses/${cid}/run`) });
  const running = q.data?.status === "running";
  useEffect(() => {
    if (!running) return;
    const ctl = new AbortController();
    fetch(`/api/courses/${cid}/run/events`, { signal: ctl.signal })
      .then((res) => readEvents(res, (ev, data) => ev === "status" && qc.setQueryData(["run", cid], data)))
      .then(() => qc.invalidateQueries({ queryKey: ["run", cid] }))
      .catch(() => {});
    return () => ctl.abort();
  }, [cid, running, qc]);
  return q;
}

function FoundGate({ cid }: { cid: number }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["found", cid], queryFn: () => get<{ sources: Source[]; unreadable_pages: { source: string; page: number }[] }>(`/api/courses/${cid}/found`) });
  const [goal, setGoal] = useState<"cram" | "deep">("deep");
  const [date, setDate] = useState("");
  const edit = useMutation({
    mutationFn: ({ id, body }: { id: number; body: object }) => send(`/api/courses/${cid}/sources/${id}`, body, "PATCH"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["found", cid] }),
  });
  const approve = useMutation({
    mutationFn: () => send(`/api/courses/${cid}/gates/found`, { goal, exam_date: date || null }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["run", cid] }),
  });
  if (!data) return null;
  const byId = new Map(data.sources.map((s) => [s.id, s]));
  return (
    <section>
      <h2 className="font-display text-xl font-semibold">What was found</h2>
      <p className="mt-1 text-sm text-muted-foreground">Check what each file is. Corrections should be paired with the exam or sheet they correct.</p>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-muted-foreground"><tr><th className="py-2 font-medium">File</th><th className="font-medium">Pages</th><th className="font-medium">Role</th><th className="font-medium">Paired with</th><th /></tr></thead>
          <tbody>
            {data.sources.map((s) => (
              <tr key={s.id} className={cn("border-t border-border", s.excluded && "text-muted-foreground line-through")} data-source={s.name}>
                <td className="py-2 pr-3 font-mono text-xs">{s.name}</td>
                <td className="tabular pr-3">{s.pages}</td>
                <td className="pr-3">
                  <select aria-label={`Role of ${s.name}`} value={s.role} disabled={s.excluded} onChange={(e) => edit.mutate({ id: s.id, body: { role: e.target.value } })}
                          className="h-8 rounded-md border border-input bg-background px-2">
                    {ROLES.map((r) => <option key={r}>{r}</option>)}
                  </select>
                </td>
                <td className="pr-3">
                  <select aria-label={`Pair ${s.name}`} value={s.paired_with ?? ""} disabled={s.excluded}
                          onChange={(e) => edit.mutate({ id: s.id, body: { paired_with: e.target.value ? +e.target.value : null } })}
                          className="h-8 max-w-48 rounded-md border border-input bg-background px-2">
                    <option value="">—</option>
                    {data.sources.filter((o) => o.id !== s.id && !o.excluded).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                  </select>
                </td>
                <td className="text-right">
                  <Button size="sm" variant="ghost" onClick={() => edit.mutate({ id: s.id, body: { excluded: !s.excluded } })}>{s.excluded ? "Include" : "Exclude"}</Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {edit.error && <p className="mt-2 text-sm text-destructive">{errText(edit.error)}</p>}
      {data.unreadable_pages.length > 0 && (
        <p className="mt-3 text-sm text-warn">Couldn't read: {data.unreadable_pages.map((p) => `${p.source} p.${p.page}`).join(", ")}</p>
      )}
      <fieldset className="mt-6 space-y-3">
        <legend className="font-medium">How will you study?</legend>
        <div className="flex flex-wrap gap-2">
          {([["deep", "Understand it deeply"], ["cram", "Cram for an exam"]] as const).map(([g, label]) => (
            <label key={g} className={cn("cursor-pointer rounded-md border px-3 py-2 text-sm", goal === g ? "border-primary bg-primary/8" : "border-border hover:bg-accent")}>
              <input type="radio" name="goal" className="sr-only" checked={goal === g} onChange={() => setGoal(g)} />{label}
            </label>
          ))}
        </div>
        <label className="flex items-center gap-3 text-sm">Exam date
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="w-44" required={goal === "cram"} />
        </label>
      </fieldset>
      {approve.error && <p className="mt-2 text-sm text-destructive">{errText(approve.error)}</p>}
      <Button className="mt-4" disabled={approve.isPending || (goal === "cram" && !date)} onClick={() => approve.mutate()}>
        Looks right, propose an outline
      </Button>
      <p className="mt-2 text-xs text-muted-foreground">{[...byId.values()].filter((s) => !s.excluded).length} files will be used.</p>
    </section>
  );
}

type OSection = { id: number; title: string; pages: { source: string; page: number }[] };
type OChapter = { id: number; title: string; priority: string; sections: OSection[] };
let tempId = -1; // ids for Chapters and Sections made by a split, until the outline is saved

/** Pure outline edits at Chapter and Section level; each returns a new outline. */
const edits = {
  moveChapter: (o: OChapter[], i: number, d: number) => { const n = [...o]; [n[i], n[i + d]] = [n[i + d], n[i]]; return n; },
  mergeChapter: (o: OChapter[], i: number) =>
    o.flatMap((c, k) => (k === i ? [{ ...c, sections: [...c.sections, ...o[i + 1].sections] }] : k === i + 1 ? [] : [c])),
  splitChapter: (o: OChapter[], i: number, j: number) => o.flatMap((c, k) => k !== i ? [c] : [
    { ...c, sections: c.sections.slice(0, j) },
    { id: tempId--, title: c.sections[j].title, priority: c.priority, sections: c.sections.slice(j) }]),
  section: (o: OChapter[], i: number, f: (s: OSection[]) => OSection[]) => o.map((c, k) => (k === i ? { ...c, sections: f(c.sections) } : c)),
  /** Moves a Section up or down; past the end of its Chapter it joins the neighbouring one. */
  moveSection: (o: OChapter[], i: number, j: number, d: number) => {
    const sec = o[i].sections[j], to = j + d;
    if (to >= 0 && to < o[i].sections.length) return edits.section(o, i, (ss) => { const n = [...ss]; [n[j], n[to]] = [n[to], n[j]]; return n; });
    const out = edits.section(o, i, (ss) => ss.filter((_, k) => k !== j));
    return edits.section(out, i + d, (ss) => (d < 0 ? [...ss, sec] : [sec, ...ss]));
  },
  splitSection: (o: OChapter[], i: number, j: number) => edits.section(o, i, (ss) => ss.flatMap((s, k) => {
    if (k !== j) return [s];
    const half = Math.ceil(s.pages.length / 2);
    return [{ ...s, pages: s.pages.slice(0, half) }, { id: tempId--, title: `${s.title} (2)`, pages: s.pages.slice(half) }];
  })),
  mergeSection: (o: OChapter[], i: number, j: number) => edits.section(o, i, (ss) =>
    ss.flatMap((s, k) => (k === j ? [{ ...s, pages: [...s.pages, ...ss[j + 1].pages] }] : k === j + 1 ? [] : [s]))),
};

function Icon({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return <Button size="icon" variant="ghost" className="size-7" disabled={disabled} onClick={onClick} aria-label={label} title={label}>{children}</Button>;
}

function OutlineGate({ cid }: { cid: number }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["outline", cid], queryFn: () => get<{ chapters: OChapter[] }>(`/api/courses/${cid}/outline`) });
  const [draft, setDraft] = useState<OChapter[] | null>(null);
  useEffect(() => { if (data) setDraft(data.chapters); }, [data]);
  const save = useMutation({
    mutationFn: (chapters: OChapter[]) => send<{ chapters: OChapter[] }>(`/api/courses/${cid}/outline`, { chapters }, "PUT"),
    onSuccess: (d) => { qc.setQueryData(["outline", cid], d); },
  });
  const approve = useMutation({ mutationFn: () => send(`/api/courses/${cid}/gates/outline`), onSuccess: () => qc.invalidateQueries({ queryKey: ["run", cid] }) });
  if (!draft) return null;
  const dirty = JSON.stringify(draft) !== JSON.stringify(data?.chapters);
  const set = (i: number, patch: Partial<OChapter>) => setDraft(draft.map((c, k) => (k === i ? { ...c, ...patch } : c)));
  const setSec = (i: number, j: number, title: string) => setDraft(edits.section(draft, i, (ss) => ss.map((s, k) => (k === j ? { ...s, title } : s))));
  const last = draft.length - 1;
  return (
    <section>
      <h2 className="font-display text-xl font-semibold">Proposed outline</h2>
      <p className="mt-1 text-sm text-muted-foreground">Rename, reorder, merge and split Chapters and Sections, and set how much attention each Chapter gets. Exam Weight is worked out from the past papers once you approve.</p>
      <ol className="mt-4 divide-y divide-border border-y border-border">
        {draft.map((c, i) => (
          <li key={c.id} className="py-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="tabular w-6 text-sm text-muted-foreground">{i + 1}</span>
              <Input value={c.title} onChange={(e) => set(i, { title: e.target.value })} className="h-8 min-w-48 flex-1 font-medium" aria-label={`Chapter ${i + 1} title`} />
              <div className="flex rounded-md border border-border" role="radiogroup" aria-label="Priority">
                {PRIORITIES.map((p) => (
                  <button key={p} type="button" role="radio" aria-checked={c.priority === p} onClick={() => set(i, { priority: p })}
                          className={cn("px-2 py-1 text-xs capitalize first:rounded-l-md last:rounded-r-md", c.priority === p ? "bg-primary text-primary-foreground" : "hover:bg-accent")}>{p}</button>
                ))}
              </div>
              <Icon label="Move up" disabled={i === 0} onClick={() => setDraft(edits.moveChapter(draft, i, -1))}><ArrowUp className="size-4" /></Icon>
              <Icon label="Move down" disabled={i === last} onClick={() => setDraft(edits.moveChapter(draft, i, 1))}><ArrowDown className="size-4" /></Icon>
              <Icon label="Merge with the next Chapter" disabled={i === last} onClick={() => setDraft(edits.mergeChapter(draft, i))}><Merge className="size-4" /></Icon>
              <Icon label="Remove Chapter" disabled={draft.length === 1} onClick={() => setDraft(draft.filter((_, k) => k !== i))}><X className="size-4" /></Icon>
            </div>
            <ol className="ml-8 mt-2 space-y-1">
              {c.sections.map((s, j) => (
                <li key={s.id} className="flex flex-wrap items-center gap-1">
                  <Input value={s.title} onChange={(e) => setSec(i, j, e.target.value)} className="h-7 min-w-40 flex-1 text-sm" aria-label={`Chapter ${i + 1} Section ${j + 1} title`} />
                  <span className="tabular w-14 text-right text-xs text-muted-foreground" title={s.pages.map((p) => `${p.source} p.${p.page}`).join(", ")}>{s.pages.length} pp.</span>
                  <Icon label="Move Section up" disabled={i === 0 && j === 0} onClick={() => setDraft(edits.moveSection(draft, i, j, -1))}><ArrowUp className="size-3.5" /></Icon>
                  <Icon label="Move Section down" disabled={i === last && j === c.sections.length - 1} onClick={() => setDraft(edits.moveSection(draft, i, j, 1))}><ArrowDown className="size-3.5" /></Icon>
                  <Icon label="Split Section" disabled={s.pages.length < 2} onClick={() => setDraft(edits.splitSection(draft, i, j))}><Scissors className="size-3.5" /></Icon>
                  <Icon label="Merge with the next Section" disabled={j === c.sections.length - 1} onClick={() => setDraft(edits.mergeSection(draft, i, j))}><Merge className="size-3.5" /></Icon>
                  <Icon label="Start a new Chapter here" disabled={j === 0} onClick={() => setDraft(edits.splitChapter(draft, i, j))}><SplitSquareVertical className="size-3.5" /></Icon>
                  <Icon label="Remove Section" onClick={() => setDraft(edits.section(draft, i, (ss) => ss.filter((_, k) => k !== j)))}><X className="size-3.5" /></Icon>
                </li>
              ))}
            </ol>
          </li>
        ))}
      </ol>
      {(save.error || approve.error) && <p className="mt-2 text-sm text-destructive">{errText(save.error ?? approve.error)}</p>}
      <div className="mt-4 flex gap-2">
        {dirty ? <Button onClick={() => save.mutate(draft)} disabled={save.isPending}>Save changes</Button>
          : <Button onClick={() => approve.mutate()} disabled={approve.isPending}>Approve, write the Chapters</Button>}
        {dirty && <Button variant="ghost" onClick={() => setDraft(data!.chapters)}>Undo</Button>}
      </div>
    </section>
  );
}

const STUDY = [
  ["read", "Read", BookOpen, "Chapters with sources, tutor and quizzes"], ["exams", "Exams", ClipboardList, "Past papers and Mock exams"],
  ["cards", "Cards", Layers, "Spaced review of what you got wrong"], ["labs", "Labs", FlaskConical, "Notebook steps with Checks"],
  ["focus", "Focus", Timer, "Timer, streak and daily goal"],
] as const;

/** Search the Course's material; a hit opens its page. */
function Search({ cid }: { cid: number }) {
  const [q, setQ] = useState(""), [query, setQuery] = useState("");
  const [cite, setCite] = useState<Citation | null>(null);
  const { data: hits, isFetching } = useQuery({ queryKey: ["search", cid, query], enabled: !!query,
    queryFn: () => get<{ source: string; page: number; text: string }[]>(`/api/courses/${cid}/search?q=${encodeURIComponent(query)}`) });
  return (
    <section className="mt-10">
      <form role="search" onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()); }} className="flex gap-2">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the course material, e.g. condition d'Armijo" aria-label="Search the course material" />
        <Button type="submit" variant="outline" disabled={!q.trim()}>Search</Button>
      </form>
      {isFetching && <p className="mt-2 text-sm text-muted-foreground">Searching…</p>}
      {hits && !hits.length && <p className="mt-2 text-sm text-muted-foreground">Nothing found.</p>}
      <ul className="mt-3 space-y-3">
        {hits?.map((h, i) => (
          <li key={i}><button type="button" onClick={() => setCite(h)} className="block text-left hover:text-primary">
            <span className="text-xs text-muted-foreground">{h.source}, p. {h.page}</span>
            <span className="line-clamp-2 block text-sm">{h.text}</span></button></li>
        ))}
      </ul>
      <PageViewer cid={cid} cite={cite} onClose={() => setCite(null)} />
    </section>
  );
}

/** Switch the Goal later, and add a PDF of your own notes as a Source. */
function Settings({ cid, course }: { cid: number; course: Course }) {
  const qc = useQueryClient();
  const [date, setDate] = useState(course.exam_date ?? "");
  const goal = useMutation({
    mutationFn: (g: "cram" | "deep") => send(`/api/courses/${cid}`, { goal: g, exam_date: date || null }, "PATCH"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["course", String(cid)] }),
  });
  const upload = useMutation({ mutationFn: (f: File) => { const d = new FormData(); d.append("file", f); return send(`/api/courses/${cid}/sources`, d); } });
  return (
    <section className="mt-10 space-y-4 border-t border-border pt-6 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <span>Goal: <span className="font-medium">{course.goal === "cram" ? "cram for an exam" : "understand deeply"}</span></span>
        <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="h-8 w-40" aria-label="Exam date" />
        <Button size="sm" variant="outline" disabled={goal.isPending || (course.goal === "deep" && !date)}
                onClick={() => goal.mutate(course.goal === "cram" ? "deep" : "cram")}>{course.goal === "cram" ? "Switch to deep" : "Switch to cram"}</Button>
      </div>
      {goal.error && <p className="text-destructive">{errText(goal.error)}</p>}
      <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-input px-3 py-1.5 hover:bg-accent">
        Add my notes (PDF)
        <input type="file" accept="application/pdf" className="sr-only" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
      </label>
      {upload.isSuccess && <span className="ml-3 text-ok">Added. It's being read and indexed.</span>}
      {upload.error && <p className="text-destructive">{errText(upload.error)}</p>}
    </section>
  );
}

export function Run() {
  const cid = useCid();
  const qc = useQueryClient();
  const { data: course } = useQuery({ queryKey: ["course", String(cid)], queryFn: () => get<Course>(`/api/courses/${cid}`) });
  const { data: run } = useRun(cid);
  const retry = useMutation({ mutationFn: () => send(`/api/courses/${cid}/run/retry`), onSuccess: () => qc.invalidateQueries({ queryKey: ["run", cid] }) });
  if (!run) return <Page><div className="h-8 w-48 animate-pulse rounded bg-muted" /><div className="mt-6 h-64 animate-pulse rounded-lg bg-muted" /></Page>;
  return (
    <Page title={course?.name} wide={run.gate === "found" || (!run.gate && run.status !== "done")}>
      {run.gate ? <PipelineStrip pipeline={run.pipeline} /> : run.status !== "done" && (
        <RunProgress cid={cid} run={run} onRetry={() => retry.mutate()} retrying={retry.isPending} retryError={retry.error} />
      )}
      {run.gate === "found" && <FoundGate cid={cid} />}
      {run.gate === "outline" && <OutlineGate cid={cid} />}
      {run.gate === "chapter_review" && (
        <div className="mb-8 rounded-md border border-border px-4 py-3">
          <p className="font-medium">The Chapters are written and wait for your review</p>
          <p className="mt-1 text-sm text-muted-foreground">Publishing the last one finishes the Run. Published Chapters can be read already.</p>
          <Link to="/c/$cid/review" params={{ cid: String(cid) }} className="mt-3 inline-block"><Button size="sm">Review Chapters</Button></Link>
        </div>
      )}
      {(run.status === "done" || run.status === "running" || run.gate === "chapter_review") && run.gate !== "found" && run.gate !== "outline" && (
        <ul className="grid gap-3 sm:grid-cols-2">
          {STUDY.map(([to, label, Icon, hint]) => (
            <li key={to}>
              <Link to={`/c/$cid/${to}`} params={{ cid: String(cid) }} className="flex gap-3 rounded-md border border-border p-4 hover:bg-accent">
                <Icon className="mt-0.5 size-5 text-primary" /><span><span className="block font-medium">{label}</span><span className="text-sm text-muted-foreground">{hint}</span></span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {(run.status === "done" || run.gate === "chapter_review") && <Search cid={cid} />}
      {(run.status === "done" || run.gate === "chapter_review") && course && <Settings cid={cid} course={course} />}
    </Page>
  );
}
