import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, NotebookPen, Target } from "lucide-react";
import { Md, MdLine } from "@/components/md";
import { Button } from "@/components/ui/button";
import { get, type Confidence, type Note, type PracticeQueue, type Progress } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useCid } from "./run";

const LEVEL: Record<Confidence, [string, string]> = {
  solid: ["Solid", "bg-ok/15 text-ok"], shaky: ["Shaky", "bg-warn/20 text-foreground"], lost: ["Lost", "bg-destructive/15 text-destructive"],
};

/** A link into the reader at a Section, and at one Block when given. */
function ToSection({ cid, section, block, className, children }: { cid: number; section: number; block?: number; className?: string; children: React.ReactNode }) {
  return <Link to="/c/$cid/read" params={{ cid: String(cid) }} search={{ section, ...(block ? { block } : {}) } as never} className={className}>{children}</Link>;
}

function Stat({ value, label, hint }: { value: string; label: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <p className="tabular font-display text-2xl font-semibold">{value}</p>
      <p className="text-sm">{label}</p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

/** Where the learner stands in a Course: what is read, how sure they feel, what the quizzes say, and what to work on next. */
export function ProgressPage() {
  const cid = useCid();
  const { data: p } = useQuery({ queryKey: ["progress", cid], queryFn: () => get<Progress>(`/api/courses/${cid}/progress`) });
  const { data: notes = [] } = useQuery({ queryKey: ["notes", cid], queryFn: () => get<Note[]>(`/api/courses/${cid}/notes`) });
  const { data: queue } = useQuery({ queryKey: ["practice", cid], queryFn: () => get<PracticeQueue>(`/api/courses/${cid}/practice`) });
  if (!p) return <p className="px-6 py-10 text-muted-foreground" role="status">Loading…</p>;
  const sections = p.chapters.flatMap((c) => c.sections);
  if (!sections.length) return <p className="px-6 py-10 text-muted-foreground">No Chapter is published yet. Publish Chapters from Review.</p>;
  const read = sections.filter((s) => s.read).length, rated = sections.filter((s) => s.confidence).length;
  const answered = sections.reduce((n, s) => n + s.answered, 0), correct = sections.reduce((n, s) => n + s.correct, 0);
  const questions = sections.reduce((n, s) => n + s.questions, 0);
  const tested = p.concepts.filter((c) => c.mastery !== null).sort((a, b) => a.mastery! - b.mastery!);
  const untested = p.concepts.filter((c) => c.mastery === null && c.blocks).length;
  const due = queue ? queue.counts.missed + queue.counts.weak + queue.counts.due : 0;
  return (
    <div className="mx-auto w-full max-w-5xl space-y-10 px-5 py-8 sm:px-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">Progress</h1>
          <p className="mt-1 text-muted-foreground">What you have read, how sure you feel, and what your answers say.</p>
        </div>
        <Button asChild><Link to="/c/$cid/practice" params={{ cid: String(cid) }}><Target className="size-4" />
          {due ? `Practise ${due} thing${due > 1 ? "s" : ""} you need` : "Practise"}</Link></Button>
      </header>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat value={`${read}/${sections.length}`} label="Sections read" />
        <Stat value={`${sections.filter((s) => s.confidence === "solid").length}/${sections.length}`} label="Sections you call solid" hint={rated ? `${rated} rated` : "Rate one at the end of a Section"} />
        <Stat value={answered ? `${Math.round((correct / answered) * 100)}%` : "—"} label="Quiz answers right" hint={`${answered} of ${questions} questions tried`} />
        <Stat value={String(notes.length)} label={notes.length === 1 ? "Note" : "Notes"} />
      </div>

      {!!p.next.length && (
        <section aria-labelledby="next-h">
          <h2 id="next-h" className="mb-3 font-display text-lg font-semibold">Work on these next</h2>
          <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-card">
            {p.next.map((n) => (
              <li key={n.section_id}>
                <ToSection cid={cid} section={n.section_id} className="group flex items-center gap-4 px-4 py-3 transition-colors hover:bg-accent/60">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{n.section}</span>
                    <span className="block truncate text-sm text-muted-foreground">{n.chapter} · {n.reason}</span>
                  </span>
                  <ArrowRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" aria-hidden />
                </ToSection>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="chapters-h">
        <h2 id="chapters-h" className="mb-3 font-display text-lg font-semibold">By Chapter</h2>
        <div className="space-y-6">
          {p.chapters.map((c) => (
            <div key={c.id} className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-sm">
                <caption className="border-b border-border bg-card px-4 py-2.5 text-left font-display font-semibold">{c.title}
                  <span className="tabular ml-2 font-sans text-xs font-normal text-muted-foreground">{c.sections.filter((s) => s.read).length}/{c.sections.length} read</span></caption>
                <thead className="sr-only"><tr><th>Section</th><th>Confidence</th><th>Practice</th></tr></thead>
                <tbody className="divide-y divide-border">
                  {c.sections.map((s) => (
                    <tr key={s.id}>
                      <td className="px-4 py-2">
                        <ToSection cid={cid} section={s.id} className="flex items-center gap-2 hover:text-primary">
                          <span className={cn("size-1.5 shrink-0 rounded-full", s.read ? "bg-ok" : "bg-border")} aria-label={s.read ? "read" : "not read"} />{s.title}</ToSection>
                      </td>
                      <td className="w-24 px-2 py-2">
                        {s.confidence ? <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", LEVEL[s.confidence][1])}>{LEVEL[s.confidence][0]}</span>
                          : <span className="text-xs text-muted-foreground">not rated</span>}</td>
                      <td className="tabular w-44 whitespace-nowrap px-4 py-2 text-right text-muted-foreground">
                        {s.practice ? <>{s.missed + (s.answered - s.correct) > 0 && <span className="mr-2 text-destructive">{s.missed + (s.answered - s.correct)} missed</span>}
                          {s.tried}/{s.practice} <span className="text-xs">practised</span></> : <span className="text-xs">no practice</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="concepts-h">
        <h2 id="concepts-h" className="mb-1 font-display text-lg font-semibold">Concepts, weakest first</h2>
        <p className="mb-3 text-sm text-muted-foreground">From your latest result on every quiz, exercise and gap text that tests the Concept.
          {untested > 0 && ` ${untested} more ${untested > 1 ? "have" : "has"} practice you have not tried.`}</p>
        {tested.length ? (
          <ul className="grid gap-x-8 gap-y-1 sm:grid-cols-2">
            {tested.map((c) => (
              <li key={`${c.section_id}-${c.name}`}>
                <ToSection cid={cid} section={c.section_id} className="flex items-center gap-3 rounded-md px-2 py-1.5 text-sm hover:bg-accent">
                  <span className="min-w-0 flex-1"><span className="block truncate">{c.name}</span>
                    <span className="block truncate text-xs text-muted-foreground">{c.section}</span></span>
                  <span className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-muted" aria-hidden>
                    <span className={cn("block h-full", c.mastery! >= 0.8 ? "bg-ok" : c.mastery! >= 0.5 ? "bg-warn" : "bg-destructive")}
                          style={{ width: `${Math.max(8, c.mastery! * 100)}%` }} /></span>
                  <span className="tabular w-20 shrink-0 text-right text-xs text-muted-foreground">
                    {c.mastery! >= 0.8 ? "solid" : c.mastery! >= 0.5 ? "shaky" : "weak"} · {c.tried}/{c.blocks}</span>
                </ToSection>
              </li>
            ))}
          </ul>
        ) : <p className="rounded-lg border border-dashed border-border px-4 py-6 text-sm text-muted-foreground">
          Nothing yet. Do the quizzes and exercises inside the Sections and each Concept shows up here with how you stand.</p>}
      </section>

      <section aria-labelledby="notes-h">
        <h2 id="notes-h" className="mb-3 font-display text-lg font-semibold">Your notes</h2>
        {notes.length ? (
          <ul className="space-y-3">
            {notes.map((n) => (
              <li key={n.block_id} className="rounded-lg border border-border bg-card px-4 py-3">
                <ToSection cid={cid} section={n.section_id} block={n.block_id} className="text-xs text-muted-foreground hover:text-primary">{n.chapter} · {n.section}</ToSection>
                <div className="prose-cf mt-1 text-[0.95rem]"><Md>{n.text}</Md></div>
              </li>
            ))}
          </ul>
        ) : <p className="flex items-center gap-2 rounded-lg border border-dashed border-border px-4 py-6 text-sm text-muted-foreground">
          <NotebookPen className="size-4 shrink-0" /><span>No notes yet. Use <MdLine>**Note**</MdLine> under any Block while reading: your own wording of an idea is what you will remember.</span></p>}
      </section>
    </div>
  );
}
