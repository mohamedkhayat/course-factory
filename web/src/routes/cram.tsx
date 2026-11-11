import { useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, Moon, Printer, RotateCcw } from "lucide-react";
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
  likelihood: "high" | "medium" | "low" };
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

export function CramPage() {
  const cid = useCid();
  const qc = useQueryClient();
  const go = useGo(cid);
  const { data, error } = useQuery({ queryKey: ["cram", cid], queryFn: () => get<Cram>(`/api/courses/${cid}/cram`) });
  const hours = useMutation({
    mutationFn: (h: number) => send(`/api/courses/${cid}/cram/settings`, { hours_per_day: h }, "PUT"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cram", cid] }),
  });
  const prepare = useMutation({ mutationFn: () => send(`/api/courses/${cid}/cram/prepare`) });
  const [h, setH] = useState<string>("");
  if (error) return <Page title="Cram"><p className="text-destructive">{errText(error)}</p></Page>;
  if (!data) return <Page title="Cram"><p className="text-muted-foreground">Loading…</p></Page>;
  const { plan } = data;
  const today = plan.days[0];
  return (
    <Page title="Cram" wide>
      <LateNight examDate={data.exam_date} />
      {plan.needs_date && <p className="text-muted-foreground">Set the exam date in the Course settings to get a Cram Plan.</p>}
      {data.exam_date && !plan.days.length && <p className="text-muted-foreground">The exam is today. Read the Cheat Sheet once, calmly, and go.</p>}
      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div>
          {today && (
            <section className="rounded-lg border border-border bg-card px-5 py-5">
              <p className="text-sm text-muted-foreground">Today · {hm(today.minutes)} planned</p>
              {plan.next ? (
                <div className="mt-2 flex flex-wrap items-center justify-between gap-4">
                  <p className="font-display text-xl font-semibold">{plan.next.title}<span className="tabular ml-2 text-sm font-normal text-muted-foreground">{hm(plan.next.minutes)}</span></p>
                  <Button size="lg" onClick={() => go(plan.next!)} disabled={plan.next.ready === false}>Next<ArrowRight className="size-4" /></Button>
                </div>
              ) : <p className="mt-2 font-display text-xl font-semibold">Today's plan is done.</p>}
              {plan.next?.ready === false && <p className="mt-1 text-sm text-muted-foreground">This Chapter isn't published yet: publish it from Review.</p>}
              <ul className="mt-4 divide-y divide-border border-t border-border">
                {today.activities.map((a, i) => (
                  <li key={i} className="flex items-center gap-3 py-2 text-sm">
                    <span className={cn("grid size-4 shrink-0 place-items-center rounded-full border", a.done ? "border-ok bg-ok text-white" : "border-input")}>{a.done && <Check className="size-3" />}</span>
                    <button type="button" className={cn("flex-1 text-left hover:text-primary", a.done && "text-muted-foreground line-through")} onClick={() => go(a)}>{a.title}</button>
                    <span className="tabular text-muted-foreground">{hm(a.minutes)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {plan.skip.length > 0 && (
            <section className="mt-6 rounded-lg border border-warn/40 bg-warn/5 px-5 py-4 text-sm">
              <p className="font-medium">Not enough time for everything: these are left out ({plan.skipped_points} of {plan.skipped_points + plan.kept_points} past-paper points)</p>
              <ul className="mt-1 list-disc pl-5">{plan.skip.map((s) => <li key={s.chapter_id}>{s.title} <span className="tabular text-muted-foreground">· {s.points} pts</span></li>)}</ul>
              <p className="mt-1 text-muted-foreground">More hours per day, or Priority focus on a Chapter, brings it back.</p>
            </section>
          )}
          <section className="mt-8">
            <h2 className="mb-2 font-medium">The days until the exam</h2>
            <ol className="space-y-3">
              {plan.days.slice(1).map((d) => (
                <li key={d.date} className="rounded-md border border-border px-4 py-3 text-sm">
                  <p className="flex justify-between"><span className="font-medium">{fmtDay(d.date)}{d.eve && " · the eve"}</span><span className="tabular text-muted-foreground">{hm(d.minutes)}</span></p>
                  <ul className="mt-1 text-muted-foreground">{d.activities.map((a, i) => <li key={i}>{a.title} · {hm(a.minutes)}</li>)}</ul>
                </li>
              ))}
            </ol>
          </section>
        </div>
        <aside className="space-y-8">
          <section>
            <h2 className="mb-2 font-medium">Time</h2>
            <form className="flex items-center gap-2 text-sm" onSubmit={(e) => { e.preventDefault(); if (+h > 0) hours.mutate(+h); }}>
              <Input type="number" min={0.5} max={16} step={0.5} className="w-20" aria-label="Hours per day" placeholder={String(data.hours_per_day)}
                     value={h} onChange={(e) => setH(e.target.value)} />hours a day <Button size="sm" variant="outline" type="submit" disabled={!h}>Set</Button>
            </form>
            <p className="mt-2 text-sm"><Link to="/c/$cid/sheet" params={{ cid: String(cid) }} className="text-primary underline-offset-4 hover:underline">Cheat Sheet</Link>
              <span className="mx-2 text-muted-foreground">·</span><Link to="/c/$cid/mixed" params={{ cid: String(cid) }} className="text-primary underline-offset-4 hover:underline">Mixed practice</Link></p>
          </section>
          <section>
            <h2 className="mb-2 font-medium">What the exam asks</h2>
            {!data.question_types.length && (
              <div className="text-sm text-muted-foreground">
                <p>No Question Types yet. They come from the past papers.</p>
                {data.unclassified > 0 && <Button size="sm" variant="outline" className="mt-2" disabled={prepare.isPending || prepare.isSuccess} onClick={() => prepare.mutate()}>
                  {prepare.isSuccess ? "Sorting on the GPU… reload later" : "Sort the past Questions into types"}</Button>}
              </div>
            )}
            <ul className="space-y-2">
              {data.question_types.map((t) => (
                <li key={t.id} className="text-sm">
                  <p className="flex items-baseline justify-between gap-2"><span className="font-medium"><MdLine>{t.name}</MdLine></span>
                    <span className={cn("tabular shrink-0 rounded-full px-2 py-0.5 text-xs", LIKELIHOOD[t.likelihood].cls)}>{Math.round(t.share * 100)}% · {t.papers} paper{t.papers === 1 ? "" : "s"}</span></p>
                  {t.trigger && <p className="text-muted-foreground"><MdLine>{t.trigger}</MdLine></p>}
                </li>
              ))}
            </ul>
          </section>
          {data.technique.types.length > 0 && (
            <section>
              <h2 className="mb-2 font-medium">Exam technique</h2>
              {data.technique.minutes_per_point && <p className="text-sm">About <span className="tabular font-medium">{data.technique.minutes_per_point.toFixed(1)} min</span> per point: stuck past that, move on and come back.</p>}
              {data.technique.types.filter((t) => t.template || t.method_marks.length).map((t) => (
                <details key={t.name} className="mt-2 rounded-md border border-border px-3 py-2 text-sm">
                  <summary className="cursor-pointer font-medium"><MdLine>{t.name}</MdLine></summary>
                  {t.template && <div className="mt-1"><Md>{t.template}</Md></div>}
                  {t.method_marks.length > 0 && <><p className="mt-2 text-muted-foreground">Marks are given for:</p>
                    <ul className="list-disc pl-5">{t.method_marks.map((m) => <li key={m.step}><MdLine>{m.step}</MdLine> <span className="tabular text-muted-foreground">({m.points} pts)</span></li>)}</ul></>}
                </details>
              ))}
            </section>
          )}
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
