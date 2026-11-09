import { useEffect, useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, BookOpen, ClipboardList, FlaskConical, Layers, Merge, Scissors, SplitSquareVertical, Timer, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { PageViewer } from "@/components/blocks";
import { get, readEvents, send, type Citation, type Course } from "@/lib/api";
import { cn } from "@/lib/utils";
import { errText, Page } from "./home";

type Gpu = { name: string; util: number; mem_used_mb: number; mem_total_mb: number };
type Run = { status: string; gate: string | null; error: string | null; next?: string[]; pages_read: number; pages_total: number; seconds_left?: number | null; gpu?: Gpu | null };

const duration = (s: number) => (s < 90 ? "under 2 min" : s < 5400 ? `about ${Math.round(s / 60)} min` : `about ${(s / 3600).toFixed(1)} h`);
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
  if (!run) return null;
  return (
    <Page title={course?.name} wide={run.gate === "found"}>
      {run.status === "running" && (
        <div className="mb-8 space-y-2" aria-live="polite">
          <p className="text-sm">Working: {run.next?.join(", ").replaceAll("_", " ") ?? "…"}</p>
          {run.pages_total > 0 && <><Progress value={(100 * run.pages_read) / run.pages_total} /><p className="tabular text-xs text-muted-foreground">{run.pages_read} of {run.pages_total} pages read</p></>}
          <p className="tabular text-xs text-muted-foreground">
            {run.seconds_left != null ? `${duration(run.seconds_left)} left until the next step` : "Estimating time left…"}
            {run.gpu && <> · GPU {run.gpu.util}% · {(run.gpu.mem_used_mb / 1024).toFixed(1)} of {(run.gpu.mem_total_mb / 1024).toFixed(0)} GB</>}
          </p>
        </div>
      )}
      {run.status === "failed" && (
        <div className="mb-8 rounded-md bg-destructive/10 px-4 py-3">
          <p className="font-medium">The Run stopped</p>
          <p className="mt-1 font-mono text-xs">{run.error}</p>
          <Button className="mt-3" size="sm" onClick={() => retry.mutate()}>Retry from where it stopped</Button>
        </div>
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
