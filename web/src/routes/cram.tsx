import { useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, ChevronRight, Moon, Printer, RotateCcw } from "lucide-react";
import { Md, MdLine } from "@/components/md";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { exported, get, send, type CheatItem, type CheatSheet } from "@/lib/api";
import { LIKELIHOOD } from "@/lib/cram";
import { cn } from "@/lib/utils";
import { errText, Page } from "./home";
import { useCid } from "./run";

type Activity = { kind: string; title: string; minutes: number; chapter_id?: number; section_id?: number | null; exam_id?: number;
  types?: string[]; done?: boolean; ready?: boolean };
type Day = { date: string; eve: boolean; minutes: number; activities: Activity[] };
type QType = { id: number; name: string; trigger: string; chapter: string | null; points: number; papers: number; share: number;
  likelihood: "high" | "medium" | "low"; blocks: number };
type Technique = { minutes_per_point: number | null; papers: { title: string; duration_min: number; points: number }[];
  types: { name: string; trigger: string; template: string; points: number; papers: number; likelihood: "high" | "medium" | "low";
    chapter: string | null; method_marks: { step: string; points: number }[] }[] };
type Cram = { goal: string | null; exam_date: string | null; hours_per_day: number; unclassified: number; question_types: QType[];
  technique: Technique;
  plan: { days: Day[]; skip: { chapter_id: number; title: string; points: number }[]; skipped_points: number; kept_points: number;
    next?: Activity | null; needs_date?: boolean } };

const fmtDay = (iso: string) => new Date(`${iso}T12:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
const hm = (m: number) => (m < 60 ? `${m} min` : `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60}` : ""}`);

/** Where an activity is done: the existing views (Reader, Cards, mixed practice, Exam mode, Cheat Sheet). */
function useGo(cid: number) {
  const nav = useNavigate();
  const c = String(cid);
  return async (a: Activity) => {
    if (a.kind === "learn" && a.section_id) return nav({ to: "/c/$cid/read", params: { cid: c }, search: { section: a.section_id } as never });
    if (a.kind === "cards" || a.kind === "mistakes") return nav({ to: "/c/$cid/cards", params: { cid: c } });
    if (a.kind === "review") return nav({ to: "/c/$cid/mixed", params: { cid: c }, search: { chapter: a.chapter_id } as never });
    if (a.kind === "variants") return nav({ to: "/c/$cid/mixed", params: { cid: c }, search: { types: a.types?.join("|") } as never });
    if (a.kind === "mixed") return nav({ to: "/c/$cid/mixed", params: { cid: c } });
    if (a.kind === "cheatsheet") return nav({ to: "/c/$cid/sheet", params: { cid: c } });
    if (a.kind === "mock" && a.exam_id) {
      const copy = await send<{ id: number }>(`/api/courses/${cid}/exams/${a.exam_id}/copies`);
      return nav({ to: "/c/$cid/exams/$eid", params: { cid: c, eid: String(a.exam_id) }, search: { copy: copy.id } as never });
    }
  };
}

/** A soft nudge on the exam's eve: sleep consolidates what was learnt; an all-nighter costs more than it gains. */
function LateNight({ examDate }: { examDate: string | null }) {
  const now = new Date();
  const tomorrow = new Date(now.getTime() + 86_400_000).toLocaleDateString("sv");
  if (!examDate || examDate !== tomorrow || now.getHours() < 23) return null;
  return (
    <p className="mb-6 flex items-center gap-2 rounded-md bg-primary/10 px-4 py-3 text-sm">
      <Moon className="size-4 shrink-0 text-primary" />It's late and the exam is tomorrow. Sleep now keeps what you learnt; one last look at the Cheat Sheet, then bed.
    </p>
  );
}

const ROUTINE = new Set(["cards", "mistakes"]);
const CHIP: Record<string, string> = { learn: "bg-primary/10 text-primary", review: "bg-muted text-foreground",
  mock: "bg-warn/15 text-warn font-medium", cheatsheet: "border border-border text-foreground", variants: "bg-muted text-foreground",
  mixed: "bg-muted text-foreground" };
const daysUntil = (iso: string) => Math.round((new Date(`${iso}T12:00`).getTime() - new Date(new Date().toLocaleDateString("sv") + "T12:00").getTime()) / 86_400_000);
const monday = (iso: string) => { const d = new Date(`${iso}T12:00`); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return d.toLocaleDateString("sv"); };

const routineOnly = (d: Day) => !d.eve && d.activities.every((a) => ROUTINE.has(a.kind));
/** Runs of two or more routine-only days of the same length fold into one quiet row. */
const quiet = (days: Day[]) => days.reduce<(Day | Day[])[]>((out, d) => {
  const last = out.at(-1);
  const prev = Array.isArray(last) ? last.at(-1)! : last;
  if (prev && routineOnly(d) && routineOnly(prev) && prev.minutes === d.minutes) {
    out[out.length - 1] = Array.isArray(last) ? [...last, d] : [prev, d];
  } else out.push(d);
  return out;
}, []);

/** One day of the run-up: its distinctive work as chips, the daily routine as a quiet note, and its load as a bar. */
function DayRow({ d, max, go }: { d: Day; max: number; go: (a: Activity) => void }) {
  const work = d.activities.filter((a) => !ROUTINE.has(a.kind));
  const routine = d.activities.filter((a) => ROUTINE.has(a.kind));
  const date = new Date(`${d.date}T12:00`);
  return (
    <li className={cn("grid grid-cols-[3.25rem_minmax(0,1fr)_3.5rem] items-start gap-x-3 py-2", d.eve && "rounded-md bg-primary/5 px-2 -mx-2")}>
      <p className="leading-tight"><span className="block text-xs text-muted-foreground">{date.toLocaleDateString(undefined, { weekday: "short" })}</span>
        <span className="tabular text-base font-semibold">{date.getDate()}</span></p>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          {d.eve && <span className="mr-1 font-medium">The eve</span>}
          {work.map((a, i) => (
            <button key={i} type="button" onClick={() => go(a)} title={`${a.title} · ${hm(a.minutes)}`}
                    className={cn("max-w-full truncate rounded px-2 py-0.5 text-left transition-colors hover:ring-1 hover:ring-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", CHIP[a.kind] ?? "bg-muted")}>
              {a.title}<span className="tabular ml-1.5 opacity-70">{hm(a.minutes)}</span></button>
          ))}
          {routine.length > 0 && <span className="text-xs text-muted-foreground">{work.length ? "+ " : ""}{routine.map((a) => a.kind === "cards" ? "cards" : "mistakes").join(" and ")}
            <span className="tabular"> · {hm(routine.reduce((n, a) => n + a.minutes, 0))}</span></span>}
        </div>
        <div className="mt-1.5 h-1 rounded-full bg-muted" aria-hidden><div className="h-1 rounded-full bg-primary/50" style={{ width: `${(100 * d.minutes) / max}%` }} /></div>
      </div>
      <p className="tabular pt-0.5 text-right text-sm text-muted-foreground">{hm(d.minutes)}</p>
    </li>
  );
}

export function CramPage() {
  const cid = useCid();
  const qc = useQueryClient();
  const go = useGo(cid);
  const { data, error } = useQuery({ queryKey: ["cram", cid], queryFn: () => get<Cram>(`/api/courses/${cid}/cram`) });
  const hours = useMutation({
    mutationFn: (h: number) => send(`/api/courses/${cid}/cram/settings`, { hours_per_day: h }, "PUT"),
    onSuccess: () => { setH(""); qc.invalidateQueries({ queryKey: ["cram", cid] }); },
  });
  const prepare = useMutation({ mutationFn: () => send(`/api/courses/${cid}/cram/prepare`) });
  const [h, setH] = useState<string>("");
  if (error) return <Page title="Cram"><p className="text-destructive">{errText(error)}</p></Page>;
  if (!data) return <Page title="Cram"><p className="text-muted-foreground">Loading…</p></Page>;
  const { plan, technique } = data;
  const today = plan.days[0];
  const ahead = plan.days.slice(1);
  const max = Math.max(1, ...ahead.map((d) => d.minutes));
  const weeks = [...ahead.reduce((m, d) => m.set(monday(d.date), [...(m.get(monday(d.date)) ?? []), d]), new Map<string, Day[]>())];
  const left = data.exam_date ? daysUntil(data.exam_date) : null;
  const how = new Map(technique.types.map((t) => [t.name, t]));
  const top = Math.max(0.01, ...data.question_types.map((t) => t.share));
  const doneMin = today ? today.activities.filter((a) => a.done).reduce((n, a) => n + a.minutes, 0) : 0;
  return (
    <Page title="Cram" wide>
      <LateNight examDate={data.exam_date} />
      <div className="-mt-2 mb-8 flex flex-wrap items-end justify-between gap-x-8 gap-y-4 border-b border-border pb-5">
        <p className="font-display">
          {left === null ? <span className="text-muted-foreground">No exam date: set it in the Course settings to get a Cram Plan.</span>
            : <><span className="tabular text-3xl font-semibold">{left <= 0 ? "Today" : left === 1 ? "Tomorrow" : `${left} days`}</span>
                <span className="ml-2 text-muted-foreground">{left > 1 ? "to the exam, " : ""}{fmtDay(data.exam_date!)}</span></>}
        </p>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <form className="flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (+h > 0) hours.mutate(+h); }}>
            <Input type="number" min={0.5} max={16} step={0.5} className="h-8 w-16" aria-label="Hours per day" placeholder={String(data.hours_per_day)}
                   value={h} onChange={(e) => setH(e.target.value)} /><span className="text-muted-foreground">hours a day</span>
            {h && <Button size="sm" variant="outline" type="submit" disabled={hours.isPending}>{hours.isPending ? "Replanning…" : "Replan"}</Button>}
          </form>
          <Button size="sm" variant="outline" asChild><Link to="/c/$cid/sheet" params={{ cid: String(cid) }}>Cheat Sheet</Link></Button>
          <Button size="sm" variant="outline" asChild><Link to="/c/$cid/mixed" params={{ cid: String(cid) }}>Mixed practice</Link></Button>
        </div>
      </div>
      {data.exam_date && !plan.days.length && <p className="mb-8 text-muted-foreground">The exam is today. Read the Cheat Sheet once, calmly, and go.</p>}
      <div className="grid gap-x-12 gap-y-10 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="min-w-0">
          {today && (
            <section aria-labelledby="today" className="rounded-lg border border-border bg-card px-5 py-4">
              <div className="flex items-baseline justify-between gap-4">
                <h2 id="today" className="font-display text-lg font-semibold">Today</h2>
                <p className="tabular text-sm text-muted-foreground">{doneMin ? `${hm(doneMin)} of ` : ""}{hm(today.minutes)}</p>
              </div>
              {!plan.next && <p className="mt-1 text-sm text-ok">Today's plan is done. Rest counts too.</p>}
              <ul className="mt-3 space-y-1">
                {today.activities.map((a, i) => {
                  const next = !!plan.next && !a.done && a.title === plan.next.title && a.kind === plan.next.kind;
                  return (
                    <li key={i} className={cn("flex items-center gap-3 rounded-md px-2 py-2 text-sm", next && "bg-primary/5")}>
                      <span className={cn("grid size-4 shrink-0 place-items-center rounded-full border", a.done ? "border-ok bg-ok text-white" : next ? "border-primary" : "border-input")}>
                        {a.done && <Check className="size-3" />}</span>
                      <button type="button" onClick={() => go(a)} disabled={a.ready === false}
                              className={cn("min-w-0 flex-1 truncate text-left hover:text-primary disabled:cursor-not-allowed disabled:opacity-60", next && "font-medium", a.done && "text-muted-foreground line-through")}>{a.title}</button>
                      <span className="tabular text-muted-foreground">{hm(a.minutes)}</span>
                      {next && <Button size="sm" onClick={() => go(a)} disabled={a.ready === false}>Start<ArrowRight className="size-4" /></Button>}
                    </li>
                  );
                })}
              </ul>
              {plan.next?.ready === false && <p className="mt-2 text-sm text-muted-foreground">This Chapter isn't published yet: publish it from Review.</p>}
            </section>
          )}
          {plan.skip.length > 0 && (
            <section className="mt-6 rounded-lg border border-warn/40 bg-warn/5 px-5 py-4 text-sm">
              <p className="font-medium">Not enough time for everything: these are left out ({plan.skipped_points} of {plan.skipped_points + plan.kept_points} past-paper points)</p>
              <ul className="mt-1 list-disc pl-5">{plan.skip.map((s) => <li key={s.chapter_id}>{s.title} <span className="tabular text-muted-foreground">· {s.points} pts</span></li>)}</ul>
              <p className="mt-1 text-muted-foreground">More hours per day, or Priority focus on a Chapter, brings it back.</p>
            </section>
          )}
          {weeks.length > 0 && (
            <section aria-labelledby="runup" className="mt-10">
              <h2 id="runup" className="font-display text-lg font-semibold">The run-up</h2>
              <p className="mt-0.5 text-sm text-muted-foreground">Every day starts with your due cards and yesterday's mistakes; the rest is shown.</p>
              {weeks.map(([start, days]) => (
                <div key={start} className="mt-5">
                  <p className="flex justify-between border-b border-border pb-1 text-xs text-muted-foreground">
                    <span>Week of {fmtDay(start)}</span><span className="tabular">{hm(days.reduce((n, d) => n + d.minutes, 0))}</span></p>
                  <ol className="divide-y divide-border/60">{quiet(days).map((r) => Array.isArray(r) ? (
                    <li key={r[0].date} className="grid grid-cols-[3.25rem_minmax(0,1fr)_3.5rem] gap-x-3 py-2 text-xs text-muted-foreground">
                      <span className="tabular">{new Date(`${r[0].date}T12:00`).getDate()}–{new Date(`${r.at(-1)!.date}T12:00`).getDate()}</span>
                      <span>Cards and mistakes only</span><span className="tabular whitespace-nowrap text-right">{hm(r[0].minutes)}/day</span>
                    </li>
                  ) : <DayRow key={r.date} d={r} max={max} go={go} />)}</ol>
                </div>
              ))}
            </section>
          )}
        </div>
        <aside aria-labelledby="asks" className="min-w-0">
          <h2 id="asks" className="font-display text-lg font-semibold">What the exam asks</h2>
          {technique.papers.length > 0 && (
            <p className="mt-0.5 text-sm text-muted-foreground">
              From {technique.papers.length} past paper{technique.papers.length === 1 ? "" : "s"}
              {technique.minutes_per_point && <>; about <span className="tabular font-medium text-foreground">{technique.minutes_per_point.toFixed(1)} min</span> a point: stuck past that, move on and come back</>}.</p>
          )}
          {!data.question_types.length && (
            <div className="mt-3 text-sm text-muted-foreground">
              <p>No Question Types yet. They come from the past papers.</p>
              {data.unclassified > 0 && <Button size="sm" variant="outline" className="mt-2" disabled={prepare.isPending || prepare.isSuccess} onClick={() => prepare.mutate()}>
                {prepare.isSuccess ? "Sorting on the GPU… reload later" : "Sort the past Questions into types"}</Button>}
            </div>
          )}
          <ul className="mt-4 divide-y divide-border border-y border-border">
            {data.question_types.map((t) => {
              const tech = how.get(t.name);
              return (
                <li key={t.id} className="py-3">
                  <p className="text-sm font-medium"><MdLine>{t.name}</MdLine></p>
                  <div className="mt-1.5 flex items-center gap-2 text-xs">
                    <div className="h-1.5 flex-1 rounded-full bg-muted" aria-hidden>
                      <div className={cn("h-1.5 rounded-full", t.likelihood === "high" ? "bg-destructive/70" : t.likelihood === "medium" ? "bg-warn/70" : "bg-muted-foreground/40")}
                           style={{ width: `${(100 * t.share) / top}%` }} /></div>
                    <span className="tabular shrink-0 text-muted-foreground">{Math.round(t.share * 100)}% of points · {t.papers} paper{t.papers === 1 ? "" : "s"}</span>
                  </div>
                  <p className={cn("mt-1 text-xs", t.blocks ? "text-muted-foreground" : "text-warn")}>
                    {t.blocks ? `${t.blocks} Block${t.blocks === 1 ? "" : "s"} prepare for it` : "No Block prepares for it yet"}</p>
                  <div className="mt-2 space-y-2 text-sm">
                    {t.trigger && <div><p className="text-xs font-medium text-muted-foreground">How to recognise it</p><MdLine>{t.trigger}</MdLine></div>}
                    {tech?.template && <div><p className="text-xs font-medium text-muted-foreground">How to answer</p><Md className="sheet-md">{tech.template}</Md></div>}
                    {!!tech?.method_marks.length && (
                      <details className="group">
                        <summary className="flex cursor-pointer list-none items-center gap-1 rounded-sm text-xs font-medium text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                          <ChevronRight className="size-3.5 transition-transform duration-200 group-open:rotate-90" />Marks are given for</summary>
                        <ul className="ml-5 mt-1 space-y-0.5">{tech.method_marks.map((m) => (
                          <li key={m.step} className="flex justify-between gap-3"><MdLine>{m.step}</MdLine><span className="tabular shrink-0 text-muted-foreground">{m.points} pts</span></li>))}</ul>
                      </details>
                    )}
                    <Link to="/c/$cid/mixed" params={{ cid: String(cid) }} search={{ types: t.name } as never} className="inline-flex items-center gap-1 text-primary hover:underline">
                      Practise this type<ArrowRight className="size-3.5" /></Link>
                  </div>
                </li>
              );
            })}
          </ul>
        </aside>
      </div>
    </Page>
  );
}

/** The Cheat Sheet: what to know for the exam, from the checked Blocks and the past papers' Question Types;
 * "Rebuild it" hides it and asks you to write it from memory first. */
export function CheatSheetPage() {
  const cid = useCid();
  const { data } = useQuery({ queryKey: ["sheet", cid], queryFn: () => get<CheatSheet>(`/api/courses/${cid}/cheatsheet`) });
  return <SheetView sheet={data} cid={cid} />;
}

const GROUPS: [string, string[]][] = [["Definitions", ["definition", "theorem", "proposition", "lemma", "corollary", "property"]],
  ["Formulas", ["formula"]], ["Methods", ["method"]], ["Common questions and how to answer them", ["question"]], ["Commands", ["commands"]],
  ["Tips", ["tip"]], ["Traps", ["trap"]], ["What the exam asks", ["exam"]]];

/** Likely-in-the-exam as a small mark: filled for high, ringed for medium, nothing for low. */
function Mark({ level }: { level: CheatItem["likelihood"] }) {
  if (level !== "high" && level !== "medium") return null;
  return <span title={LIKELIHOOD[level].label} aria-label={LIKELIHOOD[level].label}
               className={cn("mr-1 inline-block size-[0.55em] translate-y-[-0.1em] rounded-full align-middle",
                             level === "high" ? "bg-destructive" : "border border-warn")} />;
}

/** Router-free, so the exported file can show it too (links only render with a server).
 * By Chapter, then by kind; commands as a table of command and what it does. */
export function SheetView({ sheet, cid }: { sheet?: CheatSheet; cid: number }) {
  const [rebuild, setRebuild] = useState(false);
  const [recall, setRecall] = useState<Record<number, string>>({});
  const [shown, setShown] = useState<Set<number>>(new Set());
  const done = useMutation({ mutationFn: () => send(`/api/courses/${cid}/cheatsheet/done`) });
  if (!sheet) return <Page title="Cheat Sheet"><p className="text-muted-foreground">Loading…</p></Page>;
  const chapters = [...new Map(sheet.items.map((i) => [i.chapter_id, i.chapter])).entries()];
  const body = (i: CheatItem) => rebuild && !shown.has(i.block_id) ? (
    <div className="mt-1 print:hidden">
      <Textarea rows={2} placeholder="Write it from memory…" value={recall[i.block_id] ?? ""} onChange={(e) => setRecall({ ...recall, [i.block_id]: e.target.value })} />
      <Button size="sm" variant="ghost" className="mt-1" onClick={() => setShown(new Set(shown).add(i.block_id))}>Compare</Button>
    </div>
  ) : (
    <>
      {i.rows ? (
        <table className="w-full table-fixed border-collapse">
          <tbody>
            {i.rows.map((r, k) => (
              <tr key={k} className="border-t border-border/70 align-top first:border-t-0">
                <td className="w-[58%] py-1 pr-3"><code className="block whitespace-pre-wrap font-mono text-[0.86em] leading-snug [overflow-wrap:anywhere]">{r.command}</code></td>
                <td className="py-1 text-muted-foreground">{r.note && <Md className="sheet-md">{r.note}</Md>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <Md className="sheet-md">{i.body}</Md>}
      {rebuild && recall[i.block_id] && <p className="mt-1 border-t border-dashed border-input pt-1 text-muted-foreground">You wrote: {recall[i.block_id]}</p>}
    </>
  );
  return (
    <Page title="Cheat Sheet" wide>
      <div className="mb-6 flex flex-wrap items-center gap-2 print:hidden">
        <Button variant={rebuild ? "outline" : "default"} onClick={() => { setRebuild(!rebuild); setShown(new Set()); }}>
          <RotateCcw className="size-4" />{rebuild ? "Show the sheet" : "Rebuild it from memory"}</Button>
        <Button variant="outline" onClick={() => { print(); if (!exported) done.mutate(); }}><Printer className="size-4" />Print</Button>
        {!exported && !done.isSuccess && <Button variant="ghost" onClick={() => done.mutate()}>Mark as read today</Button>}
        <span className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
          <span><Mark level="high" />likely</span><span><Mark level="medium" />sometimes</span>
        </span>
      </div>
      {!sheet.items.length && <p className="text-muted-foreground">Nothing yet: the sheet fills as Chapters are published.</p>}
      <div className="cheat-sheet columns-1 gap-8 text-[0.84rem] leading-snug md:columns-2 print:columns-2 print:gap-5 print:text-[8.5pt]">
        {chapters.map(([chid, title]) => (
          <section key={chid} className="mb-5 print:mb-2">
            <h2 className="mb-1.5 break-after-avoid border-b-2 border-foreground pb-0.5 font-display text-base font-semibold print:text-[9pt]">{title}</h2>
            {GROUPS.map(([label, kinds]) => {
              const items = sheet.items.filter((i) => i.chapter_id === chid && kinds.includes(i.kind));
              if (!items.length) return null;
              return (
                <div key={label} className="mb-2.5 print:mb-1">
                  <h3 className="break-after-avoid text-[0.7rem] font-semibold uppercase tracking-wider text-muted-foreground print:text-[6.5pt]">{label}</h3>
                  {items.map((i) => (
                    <article key={i.block_id} className={cn("break-inside-avoid py-1 print:py-0.5",
                      i.kind === "trap" && "border-l-2 border-warn pl-2", (i.kind === "exam" || i.kind === "question") && "border-l-2 border-primary pl-2")}>
                      {i.title ? (
                        <p className="font-semibold"><Mark level={i.likelihood} />
                          {exported || i.section_id == null ? <MdLine>{i.title}</MdLine> : (
                            <Link to="/c/$cid/read" params={{ cid: String(cid) }} search={{ section: i.section_id } as never} title={`${i.chapter} › ${i.section}`}
                                  className="hover:text-primary"><MdLine>{i.title}</MdLine></Link>
                          )}</p>
                      ) : null}
                      {i.title ? body(i) : <div className="flex items-start"><span className="pt-[0.45em]"><Mark level={i.likelihood} /></span><div className="min-w-0 flex-1">{body(i)}</div></div>}
                    </article>
                  ))}
                </div>
              );
            })}
          </section>
        ))}
      </div>
    </Page>
  );
}

type MixedItem = { kind: "question" | "exercise"; question_id?: number; block_id?: number; chapter_id: number | null; title: string;
  statement: string; answer: string; scheme: { step: string; points: number }[] | null; type: string | null };

/** Mixed practice: one problem at a time from different Chapters, answer on paper, then self-mark. A miss becomes a Card. */
export function Mixed() {
  const cid = useCid();
  const qc = useQueryClient();
  const params = new URLSearchParams(location.search);
  const query = new URLSearchParams({ ...(params.get("chapter") ? { chapter: params.get("chapter")! } : {}), ...(params.get("types") ? { types: params.get("types")! } : {}) });
  const { data: items = [], isLoading } = useQuery({ queryKey: ["mixed", cid, query.toString()], queryFn: () => get<MixedItem[]>(`/api/courses/${cid}/cram/mixed?${query}`) });
  const [i, setI] = useState(0);
  const [shown, setShown] = useState(false);
  const mark = useMutation({
    mutationFn: (m: string) => send(`/api/courses/${cid}/cram/mixed/mark`, { mark: m, chapter_id: items[i].chapter_id, block_id: items[i].block_id, question_id: items[i].question_id }),
    onSuccess: () => { setShown(false); setI(i + 1); qc.invalidateQueries({ queryKey: ["cram", cid] }); },
  });
  const item = items[i];
  const title = params.get("types") ? "Variants of what you missed" : params.get("chapter") ? "Retrieval practice" : "Mixed practice";
  return (
    <Page title={title}>
      {isLoading ? <p className="text-muted-foreground">Loading…</p> : !item ? (
        <p className="text-muted-foreground">{items.length ? `Done: ${items.length} problems.` : "Nothing to practise yet: read a Section first."}
          <Link to="/c/$cid/cram" params={{ cid: String(cid) }} className="ml-2 text-primary hover:underline">Back to the plan</Link></p>
      ) : (
        <div className="rounded-lg border border-border bg-card px-6 py-5">
          <p className="tabular flex justify-between text-xs text-muted-foreground"><span>{item.title}{item.type && ` · ${item.type}`}</span><span>{i + 1} / {items.length}</span></p>
          <div className="prose-cf mt-4"><Md>{item.statement}</Md></div>
          {!shown ? <Button className="mt-5" onClick={() => setShown(true)}>I've answered on paper: show the answer</Button> : (
            <>
              <div className="prose-cf mt-5 border-t border-dashed border-input pt-4"><Md>{item.answer}</Md></div>
              {item.scheme && <ul className="mt-3 text-sm">{item.scheme.map((s) => <li key={s.step} className="flex justify-between gap-4"><MdLine>{s.step}</MdLine><span className="tabular text-muted-foreground">{s.points} pts</span></li>)}</ul>}
              <div className="mt-5 flex flex-wrap gap-2">
                <Button variant="secondary" disabled={mark.isPending} onClick={() => mark.mutate("got")}>Got it</Button>
                <Button variant="outline" disabled={mark.isPending} onClick={() => mark.mutate("partly")}>Partly</Button>
                <Button variant="outline" disabled={mark.isPending} onClick={() => mark.mutate("missed")}>Missed</Button>
              </div>
            </>
          )}
        </div>
      )}
    </Page>
  );
}
