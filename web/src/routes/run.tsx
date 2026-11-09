import { useEffect, useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, BookOpen, ClipboardList, FlaskConical, Layers, Timer, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { get, readEvents, send, type Course } from "@/lib/api";
import { cn } from "@/lib/utils";
import { errText, Page } from "./home";

type Run = { status: string; gate: string | null; error: string | null; next?: string[]; pages_read: number; pages_total: number };
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

type OChapter = { id: number; title: string; priority: string; exam_hits: number; exam_weight: number; sections: { id: number; title: string; pages: { source: string; page: number }[] }[] };

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
  const move = (i: number, d: number) => { const n = [...draft]; [n[i], n[i + d]] = [n[i + d], n[i]]; setDraft(n); };
  return (
    <section>
      <h2 className="font-display text-xl font-semibold">Proposed outline</h2>
      <p className="mt-1 text-sm text-muted-foreground">Rename, reorder, and set how much attention each Chapter gets. Exam hits count how often past exams test it.</p>
      <ol className="mt-4 divide-y divide-border border-y border-border">
        {draft.map((c, i) => (
          <li key={c.id} className="py-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="tabular w-6 text-sm text-muted-foreground">{i + 1}</span>
              <Input value={c.title} onChange={(e) => set(i, { title: e.target.value })} className="h-8 min-w-48 flex-1 font-medium" aria-label={`Chapter ${i + 1} title`} />
              <span className="tabular text-xs text-muted-foreground" title="Questions in past exams">{c.exam_hits} exam hits</span>
              <div className="flex rounded-md border border-border" role="radiogroup" aria-label="Priority">
                {PRIORITIES.map((p) => (
                  <button key={p} type="button" role="radio" aria-checked={c.priority === p} onClick={() => set(i, { priority: p })}
                          className={cn("px-2 py-1 text-xs capitalize first:rounded-l-md last:rounded-r-md", c.priority === p ? "bg-primary text-primary-foreground" : "hover:bg-accent")}>{p}</button>
                ))}
              </div>
              <Button size="icon" variant="ghost" className="size-7" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up"><ArrowUp className="size-4" /></Button>
              <Button size="icon" variant="ghost" className="size-7" disabled={i === draft.length - 1} onClick={() => move(i, 1)} aria-label="Move down"><ArrowDown className="size-4" /></Button>
              <Button size="icon" variant="ghost" className="size-7" disabled={draft.length === 1} onClick={() => setDraft(draft.filter((_, k) => k !== i))} aria-label="Remove Chapter"><X className="size-4" /></Button>
            </div>
            <p className="ml-8 mt-1 text-sm text-muted-foreground">{c.sections.map((s) => s.title).join(" · ")}</p>
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
      {(run.status === "done" || run.status === "running") && !run.gate && (
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
    </Page>
  );
}
