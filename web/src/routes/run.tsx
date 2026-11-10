import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowRight, ArrowUp, BookOpen, Play, Check, ClipboardList, Download, FlaskConical, Folder, Layers, Loader2, Merge, Pause, Scissors, SplitSquareVertical, Timer, TriangleAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { PageViewer } from "@/components/blocks";
import { Md } from "@/components/md";
import { duration, get, pageUrl, readEvents, send, type Citation, type Course, type Gpu } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Cover, courseHue, DeleteCourse, errText, Page } from "./home";

type Step = { name: string; label: string; gate: boolean; state: "done" | "current" | "waiting" };
type Activity = { step: string; attempt: number; elapsed: number; thinking: string; output: string; running?: boolean; inputs: Record<string, string> };
type Run = { status: string; gate: string | null; error: string | null; next?: string[]; pages_read: number; pages_total: number;
  seconds_left?: number | null; time_left?: { stage: string; left: number; seconds: number | null }[]; gpu?: Gpu | null; pipeline: Step[]; active: boolean; activity: Activity | null; progress?: RunProgressTree };
type PSection = { title: string; state: "waiting" | "writing" | "checking" | "repairing" | "judging" | "done" | "flagged" | "skipped"; blocks: number; flagged: number };
type PChapter = { id: number; title: string; sections: PSection[]; done: number; total: number; components?: Record<string, number> };
type PFolder = { name: string; sources: { name: string; pages: number; read: number }[]; pages: number; read: number };
type RunProgressTree = { folders?: PFolder[]; chapters: PChapter[]; pages: number; read: number; sections_done: number; sections_total: number; fraction: number };
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

function Tail({ label, live, children, text, waiting, className }: { label: string; live: boolean; text: string; waiting: string; className?: string; children: React.ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);  // follow new text unless the reader scrolled up
  useEffect(() => { if (box.current && pinned.current) box.current.scrollTop = box.current.scrollHeight; }, [text]);
  return (
    <div className="min-w-0">
      <p className="mb-1.5 flex items-center gap-2 text-xs font-medium text-muted-foreground">{label}
        {live && <span className="size-1.5 animate-pulse rounded-full bg-primary" aria-hidden />}</p>
      <div ref={box} onScroll={(e) => { const el = e.currentTarget; pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24; }}
           className={cn("overflow-y-auto overscroll-contain rounded-md px-4 py-3", className ?? "h-48 bg-muted/50")}>
        {text ? children : (
          <div className="ruled-wait h-full min-h-24 pt-1 text-sm leading-[1.6rem] text-muted-foreground">
            <span className="animate-pulse">{waiting}</span>
          </div>
        )}
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
        <span className="tabular ml-auto flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-0.5 text-xs text-muted-foreground"><Timer className="size-3" aria-hidden />{a.elapsed} s{a.attempt > 1 && ` · attempt ${a.attempt} of 3`}</span>
      </div>
      {detail.map(([k, v]) => <p key={k} className="mt-1 truncate text-sm text-muted-foreground"><span className="capitalize">{k.replaceAll("_", " ")}</span>: {v}</p>)}
      {page ? (
        <div className="mt-4 grid gap-5 sm:grid-cols-[13rem_minmax(0,1fr)]">
          <figure className="w-40 self-start sm:w-full">
            <div className="scan grid aspect-[1/1.414] place-items-center rounded-sm bg-card text-xs text-muted-foreground shadow-[var(--lift)]">
              <span className="col-start-1 row-start-1">Page {page.page}</span>
              <img key={`${page.source}-${page.page}`} src={pageUrl(cid, page.source, page.page)} alt={`${page.source}, page ${page.page}`}
                   onError={(e) => { e.currentTarget.hidden = true; }}
                   className="col-start-1 row-start-1 size-full rounded-sm bg-white object-contain" />
            </div>
            <figcaption className="mt-2 text-center text-xs text-muted-foreground">The original</figcaption>
          </figure>
          <Tail label="Transcription" text={a.output} live={!!a.output} waiting="The model writes the page out here once it has looked at it."
                className="h-[22rem] border border-border bg-card shadow-[var(--lift)] sm:px-6 sm:py-5">
            <Md className="prose-cf !text-[0.95rem]">{streamedText(a.output)}</Md>
          </Tail>
          <div className="sm:col-span-2">
            <Tail label="Thinking" text={a.thinking} live={!a.output} waiting="Looking at the page…" className="h-28 bg-muted/50">
              <p className="max-w-[75ch] whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">{a.thinking}</p>
            </Tail>
          </div>
        </div>
      ) : (
        <div className="mt-3 min-w-0 space-y-4">
          <Tail label="Thinking" text={a.thinking} live={!a.output} waiting={a.running ? "Reading the prompt…" : "Queued: both model lanes are busy with other Sections."}>
            <p className="max-w-[75ch] whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">{a.thinking}</p>
          </Tail>
          <Tail label="Output" text={a.output} live={!!a.output} waiting="The answer appears here as the model writes it.">
            <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed">{a.output}</pre>
          </Tail>
        </div>
      )}
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
                <span className="tabular text-xs text-muted-foreground">{files.length} {files.length === 1 ? "file" : "files"}</span>
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
const BUSY: PSection["state"][] = ["checking", "repairing", "judging"];

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
                      className={cn("max-w-64 truncate rounded px-1.5 py-0.5 text-xs transition-colors duration-500",
                        s.state === "done" ? "bg-primary/15 text-foreground" : s.state === "flagged" ? "bg-destructive/15 text-destructive"
                          : s.state === "writing" ? "animate-pulse bg-primary text-primary-foreground"
                          : BUSY.includes(s.state) ? "animate-pulse bg-warn/25 text-foreground" : "bg-border/60 text-muted-foreground")}>
                    {BUSY.includes(s.state) && <span className="font-medium">{s.state} · </span>}{s.title}
                  </li>
                ))}
              </ul>
              {c.components && Object.keys(c.components).length > 0 && (
                <p className="mt-1.5 text-xs text-muted-foreground">
                  {Object.entries(c.components).map(([k, n]) => `${k.replaceAll("_", " ")} ${n}`).join(" · ")}
                </p>
              )}
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
                {!!run.progress?.folders?.length && (() => {
                  const all = run.progress.folders.flatMap((f) => f.sources), done = all.filter((s) => s.read >= s.pages).length;
                  return <span>Sources <span className="font-medium text-foreground">{done}</span>/{all.length}</span>;
                })()}
                {(run.progress?.sections_total ?? 0) > 0 && <span><span className="font-medium text-foreground">{run.progress?.sections_done}</span> of {run.progress?.sections_total} Sections written</span>}
                {live && <span>{run.seconds_left != null ? `${duration(run.seconds_left)} to the next Approval Gate` : "Estimating time left…"}</span>}
                {live && run.time_left?.map((s) => <span key={s.stage}>{s.stage}: {s.left} left{s.seconds != null && ` · ${duration(s.seconds)}`}</span>)}
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

type OSection = { id: number; title: string; pages: { source: string; page: number }[]; teaches?: string[] };
type OChapter = { id: number; title: string; priority: string; profile?: string | null; sections: OSection[] };
/** How a Chapter is crammed: worked problems, memorisation, or commands and code. */
const PROFILES = [["problem", "Problems"], ["recall", "Recall"], ["hands_on", "Hands-on"]] as const;
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
              <div className="flex rounded-md border border-border" role="radiogroup" aria-label="Cram style" title="How this Chapter is crammed: worked problems, memorisation, or commands and code">
                {PROFILES.map(([p, label]) => (
                  <button key={p} type="button" role="radio" aria-checked={c.profile === p} onClick={() => set(i, { profile: p })}
                          className={cn("px-2 py-1 text-xs first:rounded-l-md last:rounded-r-md", c.profile === p ? "bg-secondary text-secondary-foreground ring-1 ring-primary" : "hover:bg-accent")}>{label}</button>
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
                  <Input key={(s.teaches ?? []).join(",")} defaultValue={(s.teaches ?? []).join(", ")} placeholder="Concepts it teaches, comma-separated"
                    title="Practice only tests Concepts taught by its own Section or an earlier one"
                    onBlur={(e) => setDraft(edits.section(draft, i, (ss) => ss.map((x, k) => k === j ? { ...x, teaches: e.target.value.split(",").map((t) => t.trim()).filter(Boolean) } : x)))}
                    className="h-7 basis-full text-xs text-muted-foreground" aria-label={`Chapter ${i + 1} Section ${j + 1} Concepts`} />
                </li>
              ))}
            </ol>
          </li>
        ))}
      </ol>
      {(save.error || approve.error) && <p className="mt-2 text-sm text-destructive">{errText(save.error ?? approve.error)}</p>}
      <div className="mt-4"><AutoResolveToggle cid={cid} /></div>
      <div className="mt-4 flex gap-2">
        {dirty ? <Button onClick={() => save.mutate(draft)} disabled={save.isPending}>Save changes</Button>
          : <Button onClick={() => approve.mutate()} disabled={approve.isPending}>Approve, write the Chapters</Button>}
        {dirty && <Button variant="ghost" onClick={() => setDraft(data!.chapters)}>Undo</Button>}
      </div>
    </section>
  );
}

type TocChapter = { id: number; title: string; priority: string; exam_weight: number; status: string; sections: { id: number; title: string }[] };

const daysTo = (date: string | null) => (date ? Math.round((new Date(date + "T00:00").getTime() - new Date().setHours(0, 0, 0, 0)) / 86_400_000) : null);

/** The Course's name on its cover colour, with its Goal and exam date. */
function CourseHead({ course, chapters }: { course: Course; chapters?: number }) {
  const days = daysTo(course.exam_date);
  return (
    <header className="mb-8 flex items-center gap-5" style={{ "--hue": courseHue(course.id) } as React.CSSProperties}>
      <Cover id={course.id} name={course.name} className="size-16 rounded-lg text-[2rem] shadow-[var(--lift)]" />
      <div className="min-w-0">
        <h1 className="truncate font-display text-3xl font-semibold tracking-tight sm:text-4xl">{course.name}</h1>
        <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted-foreground">
          {course.goal && <span>{course.goal === "cram" ? "Cram for the exam" : "Learn it deeply"}</span>}
          {chapters != null && <span className="tabular">{chapters} Chapter{chapters === 1 ? "" : "s"}</span>}
          {course.exam_date && days != null && (
            <span className="tabular">Exam {new Date(course.exam_date + "T00:00").toLocaleDateString(undefined, { day: "numeric", month: "long" })}
              {days >= 0 && <> · <span className={cn("font-medium", days <= 14 ? "text-foreground mark" : "")}>{days === 0 ? "today" : `in ${days} day${days === 1 ? "" : "s"}`}</span></>}</span>
          )}
        </p>
      </div>
    </header>
  );
}

/** A finished (or publishing) Course: its Chapters to read, and the study tools beside them. */
function Overview({ cid, course, full }: { cid: number; course: Course; full: boolean }) {
  const { data: outline } = useQuery({ queryKey: ["outline", cid], queryFn: () => get<{ chapters: TocChapter[] }>(`/api/courses/${cid}/outline`) });
  const { data: place } = useQuery({ queryKey: ["place", cid], queryFn: () => get<{ section_id: number | null; read: number[] }>(`/api/courses/${cid}/place`) });
  const { data: cards } = useQuery({ queryKey: ["cards", cid], queryFn: () => get<unknown[]>(`/api/courses/${cid}/cards/due`) });
  const { data: exams } = useQuery({ queryKey: ["exams", cid], queryFn: () => get<{ kind: string }[]>(`/api/courses/${cid}/exams`) });
  const { data: labs } = useQuery({ queryKey: ["labs", cid], queryFn: () => get<{ steps: number; passed: number }[]>(`/api/courses/${cid}/labs`) });
  const chapters = (outline?.chapters ?? []).filter((c) => c.priority !== "skip");
  const read = new Set(place?.read ?? []);
  const maxWeight = Math.max(0.0001, ...chapters.map((c) => c.exam_weight));
  const current = chapters.flatMap((c) => c.sections.map((s) => ({ ...s, chapter: c }))).find((s) => s.id === place?.section_id);
  const labSteps = labs?.reduce((n, l) => n + l.steps, 0) ?? 0, labPassed = labs?.reduce((n, l) => n + l.passed, 0) ?? 0;
  const tools = [
    ["read", "Read", BookOpen, current ? "Pick up where you left off" : "Start at Chapter 1", null],
    ["cards", "Cards", Layers, cards?.length ? "Due for review" : "None due", cards?.length ?? null],
    ["exams", "Exams", ClipboardList, exams ? `${exams.filter((e) => e.kind !== "mock").length} past, ${exams.filter((e) => e.kind === "mock").length} mock` : "…", exams?.length ?? null],
    ["labs", "Labs", FlaskConical, labs?.length ? `${labPassed} of ${labSteps} Steps done` : "None in this Course", labs?.length ?? null],
    ["focus", "Focus", Timer, "Timer and daily goal", null],
  ] as const;
  return (
    <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_19rem]" style={{ "--hue": courseHue(cid) } as React.CSSProperties}>
      <div className="min-w-0">
        {current && (
          <Link to="/c/$cid/read" params={{ cid: String(cid) }}
                className="lift group mb-8 flex items-center gap-4 rounded-lg border border-border bg-card p-5 hover:border-transparent">
            <span className="cover grid size-11 shrink-0 place-items-center rounded-full"><Play className="ml-0.5 size-4 fill-current" aria-hidden /></span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm text-muted-foreground">Continue reading · {current.chapter.title}</span>
              <span className="block truncate font-display text-lg font-semibold">{current.title}</span>
            </span>
            <ArrowRight className="size-5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden />
          </Link>
        )}
        <h2 className="mb-3 font-display text-lg font-semibold">Chapters</h2>
        {!outline ? <div className="h-48 animate-pulse rounded-lg bg-muted" /> : (
          <ol className="divide-y divide-border border-y border-border">
            {chapters.map((c, i) => {
              const done = c.sections.filter((s) => read.has(s.id)).length;
              const published = c.status === "published";
              const body = (
                <>
                  <span className="tabular w-8 shrink-0 pt-0.5 font-display text-2xl font-semibold text-muted-foreground/60 group-hover:cover-ink">{i + 1}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium leading-snug">{c.title.replace(/^Chapitre\s+\d+\s*[—:–-]\s*/i, "")}</span>
                    <span className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
                      <span className="flex gap-0.5" aria-label={`${done} of ${c.sections.length} Sections read`}>
                        {c.sections.map((s) => <span key={s.id} className={cn("h-1.5 w-3 rounded-full", read.has(s.id) ? "cover" : "bg-muted")} />)}
                      </span>
                      <span className="tabular">{done} / {c.sections.length} read</span>
                      {!published && <span className="rounded bg-muted px-1.5 py-0.5">Not published yet</span>}
                      {c.priority !== "normal" && <span className="rounded bg-muted px-1.5 py-0.5 capitalize">{c.priority}</span>}
                    </span>
                  </span>
                  {c.exam_weight > 0 && (
                    <span className="hidden w-24 shrink-0 sm:block" title={`Exam Weight ${Math.round(c.exam_weight * 100)}%`}>
                      <span className="block text-right text-xs text-muted-foreground tabular">{Math.round(c.exam_weight * 100)}% of the exam</span>
                      <span className="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-muted"><span className="block h-full rounded-full bg-warn" style={{ width: `${(100 * c.exam_weight) / maxWeight}%` }} /></span>
                    </span>
                  )}
                </>
              );
              return (
                <li key={c.id}>
                  {published ? <Link to="/c/$cid/read" params={{ cid: String(cid) }} className="group flex items-start gap-4 py-4 transition-colors hover:bg-accent/40">{body}</Link>
                    : <div className="flex items-start gap-4 py-4 opacity-70">{body}</div>}
                </li>
              );
            })}
          </ol>
        )}
        {full && <Search cid={cid} />}
      </div>
      <aside className="space-y-8">
        <nav aria-label="Study" className="overflow-hidden rounded-lg border border-border bg-card">
          <ul className="divide-y divide-border">
            {tools.map(([to, label, Icon, hint, count]) => (
              <li key={to}>
                <Link to={`/c/$cid/${to}`} params={{ cid: String(cid) }} className="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-accent/60">
                  <span className="cover-wash cover-ink grid size-8 shrink-0 place-items-center rounded-md"><Icon className="size-4" aria-hidden /></span>
                  <span className="min-w-0 flex-1"><span className="block text-sm font-medium">{label}</span><span className="block truncate text-xs text-muted-foreground">{hint}</span></span>
                  {count != null && count > 0 && <span className="tabular rounded-full bg-muted px-2 py-0.5 text-xs font-medium">{count}</span>}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        {full && <Settings cid={cid} course={course} />}
      </aside>
    </div>
  );
}

/** Search the Course's material; a hit opens its page. */
function Search({ cid }: { cid: number }) {
  const [q, setQ] = useState(""), [query, setQuery] = useState("");
  const [cite, setCite] = useState<Citation | null>(null);
  const { data: hits, isFetching } = useQuery({ queryKey: ["search", cid, query], enabled: !!query,
    queryFn: () => get<{ source: string; page: number; text: string }[]>(`/api/courses/${cid}/search?q=${encodeURIComponent(query)}`) });
  return (
    <section className="mt-10">
      <h2 className="mb-3 font-display text-lg font-semibold">Search the material</h2>
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
/** Per-Run option: the local model resolves each Chapter's flags as soon as it is written, so Review shows cleaner Chapters. */
function AutoResolveToggle({ cid }: { cid: number }) {
  const qc = useQueryClient();
  const { data: course } = useQuery({ queryKey: ["course", String(cid)], queryFn: () => get<Course>(`/api/courses/${cid}`) });
  const set = useMutation({ mutationFn: (on: boolean) => send(`/api/courses/${cid}/auto-resolve`, { on }, "PUT"),
    onSuccess: (c) => qc.setQueryData(["course", String(cid)], c) });
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm">
      <input type="checkbox" className="size-4 accent-primary" checked={!!course?.auto_resolve} disabled={!course || set.isPending}
             onChange={(e) => set.mutate(e.target.checked)} />
      Auto-resolve flagged Blocks before review
    </label>
  );
}

type RefreshDiff = { new: string[]; changed: string[]; removed: string[]; sections: { id: number; title: string; chapter: string }[];
  edited_sections: { id: number; title: string; chapter: string }[];
  last: { state: "running" | "done" | "failed"; error?: string; result?: { regenerated: number[]; kept: number[]; changed_pages: [string, number][] } } | null };

/** Refresh Sources: shows what changed in the folder first, then redoes only that. */
function RefreshSources({ cid }: { cid: number }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [edited, setEdited] = useState<"keep" | "regenerate" | "notes">("keep");
  const { data, refetch, isFetching } = useQuery({ queryKey: ["refresh", cid], enabled: open, queryFn: () => get<RefreshDiff>(`/api/courses/${cid}/refresh`),
    refetchInterval: (q) => (q.state.data?.last?.state === "running" ? 3000 : false) });
  const start = useMutation({ mutationFn: () => send(`/api/courses/${cid}/refresh`, { edited }), onSuccess: () => { refetch(); qc.invalidateQueries({ queryKey: ["run", cid] }); } });
  if (!open) return <Button size="sm" variant="outline" onClick={() => setOpen(true)}>Refresh Sources…</Button>;
  if (!data) return <p className="text-muted-foreground">Comparing the folder with what was imported…</p>;
  const nothing = !data.new.length && !data.changed.length && !data.removed.length;
  const list = (label: string, xs: string[]) => xs.length > 0 && <p><span className="font-medium">{label}:</span> {xs.join(", ")}</p>;
  return (
    <div className="space-y-2 rounded-md border border-border px-4 py-3">
      {data.last?.state === "running" && <p>Refreshing on the GPU: re-reading the changed pages, then rewriting their Sections…</p>}
      {data.last?.state === "failed" && <p className="text-destructive">The last Refresh failed: {data.last.error}</p>}
      {data.last?.state === "done" && data.last.result && <p className="text-ok">Refreshed: {data.last.result.changed_pages.length} changed pages, {data.last.result.regenerated.length} Sections rewritten
        {data.last.result.kept.length ? `, ${data.last.result.kept.length} edited ones kept` : ""}. They wait in Review.</p>}
      {nothing ? <p className="text-muted-foreground">Nothing changed in the folder.</p> : (
        <>
          {list("New", data.new)}{list("Changed", data.changed)}{list("Removed (they will be excluded, not deleted)", data.removed)}
          {data.sections.length > 0 && <p className="text-muted-foreground">Sections citing these files: {data.sections.map((s) => s.title).join(", ")}. Only those whose pages actually changed are rewritten.</p>}
          {data.edited_sections.length > 0 && (
            <fieldset className="space-y-1">
              <legend>You edited {data.edited_sections.map((s) => s.title).join(", ")} by hand. For those:</legend>
              {([["keep", "Keep my version"], ["regenerate", "Rewrite them"], ["notes", "Rewrite them, keeping my edits as notes"]] as const).map(([v, label]) => (
                <label key={v} className="flex items-center gap-2"><input type="radio" name="edited" className="accent-primary" checked={edited === v} onChange={() => setEdited(v)} />{label}</label>
              ))}
            </fieldset>
          )}
          <Button size="sm" disabled={start.isPending || data.last?.state === "running"} onClick={() => start.mutate()}>Refresh now</Button>
        </>
      )}
      {start.error && <p className="text-destructive">{errText(start.error)}</p>}
      <Button size="sm" variant="ghost" disabled={isFetching} onClick={() => refetch()}>Check again</Button>
    </div>
  );
}

function Settings({ cid, course }: { cid: number; course: Course }) {
  const qc = useQueryClient();
  const [date, setDate] = useState(course.exam_date ?? "");
  const goal = useMutation({
    mutationFn: ({ g, d }: { g: "cram" | "deep"; d: string }) => send(`/api/courses/${cid}`, { goal: g, exam_date: d || null }, "PATCH"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["course", String(cid)] }),
  });
  const upload = useMutation({ mutationFn: (f: File) => { const d = new FormData(); d.append("file", f); return send(`/api/courses/${cid}/sources`, d); } });
  return (
    <section className="space-y-4 text-sm">
      <h2 className="font-display text-lg font-semibold">This Course</h2>
      <p>Goal: <span className="font-medium">{course.goal === "cram" ? "cram for an exam" : "understand deeply"}</span></p>
      <div className="flex flex-wrap items-center gap-2">
        {/* a date on its own saves too; Cram cannot lose its date */}
        <Input type="date" value={date} className="h-8 w-40" aria-label="Exam date"
               onChange={(e) => { setDate(e.target.value); if (e.target.value || course.goal !== "cram") goal.mutate({ g: course.goal === "cram" ? "cram" : "deep", d: e.target.value }); }} />
        <Button size="sm" variant="outline" disabled={goal.isPending || (course.goal === "deep" && !date)}
                onClick={() => goal.mutate({ g: course.goal === "cram" ? "deep" : "cram", d: date })}>{course.goal === "cram" ? "Switch to deep" : "Switch to cram"}</Button>
      </div>
      {goal.error && <p className="text-destructive">{errText(goal.error)}</p>}
      <div><AutoResolveToggle cid={cid} /></div>
      <RefreshSources cid={cid} />
      <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-input px-3 py-1.5 hover:bg-accent">
        Add my notes (PDF)
        <input type="file" accept="application/pdf" className="sr-only" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
      </label>
      {upload.isSuccess && <p className="text-ok">Added. It's being read and indexed.</p>}
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
  const study = !!run && (run.status === "done" || run.status === "running" || run.gate === "chapter_review") && run.gate !== "found" && run.gate !== "outline";
  if (!run) return <Page><div className="h-8 w-48 animate-pulse rounded bg-muted" /><div className="mt-6 h-64 animate-pulse rounded-lg bg-muted" /></Page>;
  return (
    <Page wide={run.gate === "found" || (!run.gate && run.status !== "done") || study}>
      {course && <CourseHead course={course} />}
      {run.gate ? <PipelineStrip pipeline={run.pipeline} /> : run.status !== "done" && (
        <RunProgress cid={cid} run={run} onRetry={() => retry.mutate()} retrying={retry.isPending} retryError={retry.error} />
      )}
      {run.gate === "found" && <FoundGate cid={cid} />}
      {run.gate === "outline" && <OutlineGate cid={cid} />}
      {run.gate === "chapter_review" && (
        <div className="mb-8 flex flex-wrap items-center justify-between gap-4 rounded-lg border border-border bg-card px-5 py-4" style={{ "--hue": courseHue(cid) } as React.CSSProperties}>
          <div>
            <p className="font-medium">The Chapters are written and wait for your review</p>
            <p className="mt-1 text-sm text-muted-foreground">Publishing the last one finishes the Run. Published Chapters can be read already.</p>
          </div>
          <Link to="/c/$cid/review" params={{ cid: String(cid) }}><Button>Review Chapters</Button></Link>
        </div>
      )}
      {study && course && <Overview cid={cid} course={course} full={run.status === "done" || run.gate === "chapter_review"} />}
      {course && <div className="mt-14 flex justify-end gap-2 border-t border-border pt-4">
        <Button asChild variant="ghost" size="sm" className="text-muted-foreground" title="One HTML file that opens offline: published Chapters, quizzes, exercises and Exams with answers, no tutor or grading">
          <a href={`/api/courses/${cid}/export`} download><Download className="size-4" />Export Course</a>
        </Button>
        <DeleteCourse cid={cid} name={course.name} busy={run.active} /></div>}
    </Page>
  );
}
