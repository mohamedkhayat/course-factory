import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, FileText, Lightbulb, NotebookPen, Search } from "lucide-react";
import { MdLine } from "@/components/md";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { get, send, type Block, type Chapter, type Citation, type Confidence, type Note, type Progress, type Section, type Standing } from "@/lib/api";
import { cn } from "@/lib/utils";

const KIND: Record<string, string> = {
  prose: "Explanation", theorem_box: "Statement", worked_example: "Example", exercise: "Exercise", quiz: "Quiz", key_formula: "Formula",
  callout: "Note", algorithm: "Method", iteration_table: "Iterations", plot: "Plot", explorer: "Explorer", diagram: "Diagram", figure: "Figure",
  table: "Table", code: "Code", fill_blanks: "Fill the gaps", code_exercise: "Code exercise", surface_plot: "Surface", optimizer_animation: "Animation",
  step_diagram: "Walkthrough", terminal: "Terminal", intuition: "Intuition", misconception: "Common mistake", recap: "Recap", explain_back: "Explain back",
};
const TITLE_FIELDS = ["title", "name", "concept", "statement", "markdown", "idea", "belief", "text", "caption", "task", "prompt"];

/** What a Block is and a one-line title for it, for the outline and search. The title is cut on a word, never inside $math$. */
export function blockLabel(b: Block): { kind: string; title: string } {
  const d = b.data ?? {};
  const raw = TITLE_FIELDS.map((f) => d[f]).find((v) => typeof v === "string" && v.trim()) ?? d.questions?.[0]?.prompt ?? d.takeaways?.[0] ?? "";
  let title = String(raw).trim().split("\n")[0].replace(/^#+\s*/, "");
  if (title.length > 110) {
    title = title.slice(0, 110).replace(/\s+\S*$/, "");
    if ((title.match(/\$/g)?.length ?? 0) % 2) title = title.slice(0, title.lastIndexOf("$"));
    title = title.trimEnd() + "…";
  }
  return { kind: KIND[b.component] ?? b.component.replaceAll("_", " "), title };
}

/** Words in a Block's text, for a reading-time estimate. */
const words = (v: unknown): number => typeof v === "string" ? v.split(/\s+/).filter(Boolean).length
  : Array.isArray(v) ? v.reduce((n: number, x) => n + words(x), 0)
  : v && typeof v === "object" ? Object.values(v).reduce((n: number, x) => n + words(x), 0) : 0;
const PRACTICE_MIN: Record<string, number> = { quiz: 2, fill_blanks: 2, exercise: 8, code_exercise: 10, explain_back: 4 };
/** Minutes a Section takes: reading at 180 words a minute, plus a few minutes per practice Block. */
export const sectionMinutes = (s: Section) =>
  Math.max(1, Math.round(s.blocks.reduce((n, b) => n + words(b.data), 0) / 180 + s.blocks.reduce((n, b) => n + (PRACTICE_MIN[b.component] ?? 0), 0)));

/** How far down the page the reader is, as a thin bar under the header. */
export function ReadingBar() {
  const [p, setP] = useState(0);
  useEffect(() => {
    const on = () => { const max = document.documentElement.scrollHeight - innerHeight; setP(max > 0 ? Math.min(1, scrollY / max) : 0); };
    on();
    addEventListener("scroll", on, { passive: true });
    addEventListener("resize", on);
    return () => { removeEventListener("scroll", on); removeEventListener("resize", on); };
  }, []);
  return <div className="pointer-events-none fixed inset-x-0 top-12 z-30 h-0.5 print:hidden" role="progressbar" aria-label="Reading progress"
              aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(p * 100)}>
    <div className="h-full origin-left bg-primary transition-transform duration-100" style={{ transform: `scaleX(${p})` }} /></div>;
}

export const scrollToBlock = (id: number) => document.querySelector(`[data-block="${id}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });

/** The Section's Blocks as a list beside the text; the one on screen is marked, a click jumps to it. */
export function Outline({ section, notes, results }: { section: Section; notes: Map<number, string>; results: Record<string, Standing> }) {
  const [at, setAt] = useState<number | null>(null);
  useEffect(() => {
    const seen = new Map<number, boolean>();
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) seen.set(Number((e.target as HTMLElement).dataset.block), e.isIntersecting);
      const first = section.blocks.find((b) => seen.get(b.id));
      if (first) setAt(first.id);
    }, { rootMargin: "-15% 0px -55% 0px" });
    document.querySelectorAll("[data-block]").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [section.id, section.blocks.length]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <nav aria-label="In this Section" className="mb-2 ml-3 mt-1 text-sm">
      <ol className="space-y-px border-l border-border">
        {section.blocks.map((b) => {
          const { kind, title } = blockLabel(b);
          return (
            <li key={b.id}>
              <button type="button" onClick={() => scrollToBlock(b.id)} aria-current={at === b.id ? "location" : undefined}
                      className={cn("-ml-px block w-full border-l-2 border-transparent py-1 pl-3 pr-1 text-left text-muted-foreground hover:text-foreground",
                                    at === b.id && "border-primary text-foreground")}>
                <span className="flex items-center gap-1 text-[0.7rem] uppercase tracking-wide opacity-80">{kind}
                  {notes.has(b.id) && <NotebookPen className="size-3 text-primary" aria-label="has your note" />}
                  {results[b.id] && <span className={cn("size-1.5 rounded-full", results[b.id].last >= 0.8 ? "bg-ok" : "bg-destructive")}
                                          aria-label={results[b.id].last >= 0.8 ? "got it right" : "missed"} />}</span>
                {title && <span className="line-clamp-2 text-[0.8rem] leading-snug [overflow-wrap:anywhere]"><MdLine>{title}</MdLine></span>}
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Retrieval before reading: recall the last Section's points from memory, then check. Trying first is what makes it stick. */
export function WarmUp({ previous }: { previous: Section }) {
  const [shown, setShown] = useState(false);
  const recap = previous.blocks.find((b) => b.component === "recap")?.data?.takeaways as string[] | undefined;
  const points = recap?.length ? recap : previous.objectives?.length ? previous.objectives : previous.teaches ?? [];
  useEffect(() => setShown(false), [previous.id]);
  if (!points.length) return null;
  return (
    <aside className="mt-6 rounded-lg border border-dashed border-border px-4 py-3 text-sm" aria-label="Warm-up">
      <p className="flex items-center gap-2 font-medium"><Lightbulb className="size-4 text-primary" />Warm-up, one minute</p>
      <p className="mt-1 text-muted-foreground">Before reading on: from memory, what did <span className="text-foreground">“{previous.title}”</span> establish?
        Say it out loud or jot it down, then check against its {points.length} {points.length === 1 ? "point" : "points"}.</p>
      {shown ? <ul className="mt-2 list-disc space-y-1 pl-5">{points.map((t, i) => <li key={i}><MdLine>{t}</MdLine></li>)}</ul>
        : <button type="button" onClick={() => setShown(true)} className="mt-2 text-primary underline decoration-dotted underline-offset-4 hover:decoration-solid">Check my recall</button>}
    </aside>
  );
}

const LEVELS: [Confidence, string, string][] = [
  ["solid", "Solid", "I could explain it and solve its exercises"],
  ["shaky", "Shaky", "I followed, but could not redo it alone"],
  ["lost", "Lost", "I need this explained again"],
];

/** At the end of a Section: how sure the learner feels. Shaky and lost Sections come back first on Progress. */
export function ConfidenceCheck({ cid, section, onAsk }: { cid: number; section: Section; onAsk: () => void }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["progress", cid], queryFn: () => get<Progress>(`/api/courses/${cid}/progress`) });
  const level = data?.chapters.flatMap((c) => c.sections).find((s) => s.id === section.id)?.confidence ?? null;
  const set = useMutation({
    mutationFn: (l: Confidence) => send(`/api/courses/${cid}/sections/${section.id}/confidence`, { level: l }, "PUT"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["progress", cid] }),
  });
  return (
    <section className="mt-12 rounded-lg border border-border px-4 py-4" aria-label="How well do you know this Section?">
      <p className="font-medium">How well do you know this Section now?</p>
      <p className="mt-0.5 text-sm text-muted-foreground">Be honest: Progress brings the shaky ones back first.</p>
      <div className="mt-3 grid gap-2 sm:grid-cols-3" role="radiogroup">
        {LEVELS.map(([l, label, hint]) => (
          <button key={l} type="button" role="radio" aria-checked={level === l} disabled={set.isPending} onClick={() => set.mutate(l)}
                  className={cn("rounded-md border border-border px-3 py-2 text-left text-sm hover:border-primary",
                                level === l && (l === "solid" ? "border-ok bg-ok/10" : l === "shaky" ? "border-warn bg-warn/10" : "border-destructive bg-destructive/10"))}>
            <span className="font-medium">{label}</span><span className="block text-xs text-muted-foreground">{hint}</span>
          </button>
        ))}
      </div>
      {(level === "shaky" || level === "lost") && (
        <p className="mt-3 text-sm text-muted-foreground">Try “Explain differently” under the Block that lost you, or{" "}
          <button type="button" onClick={onAsk} className="text-primary underline decoration-dotted underline-offset-4 hover:decoration-solid">ask the tutor</button>.
          Redo its exercises tomorrow rather than rereading.</p>
      )}
      {set.error && <p className="mt-2 text-sm text-destructive">{String(set.error.message)}</p>}
    </section>
  );
}

type Hit = { key: string; icon: React.ReactNode; kind: string; title: string; where: string; go: () => void };

/** Find anything in the Course: Sections, Concepts, Blocks, your notes, and (on Enter) the professor's pages. */
export function SearchPalette({ cid, open, onClose, chapters, notes, go, onCite }: {
  cid: number; open: boolean; onClose: () => void; chapters: Chapter[]; notes: Note[];
  go: (sectionId: number, blockId?: number) => void; onCite: (c: Citation) => void;
}) {
  const [q, setQ] = useState(""), [asked, setAsked] = useState(""), [sel, setSel] = useState(0);
  const list = useRef<HTMLUListElement>(null);
  useEffect(() => { if (open) { setQ(""); setAsked(""); setSel(0); } }, [open]);
  const { data: pages, isFetching } = useQuery({ queryKey: ["search", cid, asked], enabled: !!asked,
    queryFn: () => get<{ source: string; page: number; text: string }[]>(`/api/courses/${cid}/search?q=${encodeURIComponent(asked)}`) });
  const index = useMemo(() => {
    const out: (Hit & { text: string })[] = [];
    const fold = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    for (const c of chapters) for (const s of c.sections) {
      out.push({ key: `s${s.id}`, icon: <BookOpen className="size-4" />, kind: "Section", title: s.title, where: c.title, text: fold(s.title), go: () => go(s.id) });
      for (const t of s.teaches ?? []) out.push({ key: `c${s.id}${t}`, icon: <Lightbulb className="size-4" />, kind: "Concept", title: t, where: s.title, text: fold(t), go: () => go(s.id) });
      for (const b of s.blocks) {
        const { kind, title } = blockLabel(b);
        if (title && b.component !== "prose") out.push({ key: `b${b.id}`, icon: <FileText className="size-4" />, kind, title, where: s.title, text: fold(title), go: () => go(s.id, b.id) });
      }
    }
    for (const n of notes) out.push({ key: `n${n.block_id}`, icon: <NotebookPen className="size-4" />, kind: "Your note", title: n.text.split("\n")[0].slice(0, 110),
      where: n.section, text: fold(n.text), go: () => go(n.section_id, n.block_id) });
    return { out, fold };
  }, [chapters, notes]); // eslint-disable-line react-hooks/exhaustive-deps
  const terms = index.fold(q).split(/\s+/).filter(Boolean);
  const local: Hit[] = terms.length ? index.out.filter((h) => terms.every((t) => h.text.includes(t))).slice(0, 30) : [];
  const material: Hit[] = asked === q.trim() ? (pages ?? []).map((p, i) => ({ key: `p${i}`, icon: <Search className="size-4" />, kind: `${p.source} p.${p.page}`,
    title: p.text.slice(0, 160), where: "Course material", go: () => onCite({ source: p.source, page: p.page }) })) : [];
  const hits = [...local, ...material];
  const pick = (h: Hit) => { onClose(); h.go(); };
  useEffect(() => { list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" }); }, [sel]);
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent showCloseButton={false} className="top-[12%] max-w-xl translate-y-0 gap-0 p-0">
        <DialogHeader className="sr-only"><DialogTitle>Search the Course</DialogTitle><DialogDescription>Sections, Concepts, Blocks, your notes and the course material</DialogDescription></DialogHeader>
        <div className="flex items-center gap-2 border-b border-border px-3">
          <Search className="size-4 shrink-0 text-muted-foreground" />
          <Input autoFocus value={q} onChange={(e) => { setQ(e.target.value); setSel(0); }} placeholder="Find a Section, a Concept, a formula, a note…" aria-label="Search the Course"
                 role="combobox" aria-expanded={hits.length > 0} aria-controls="search-hits"
                 className="h-11 border-0 px-0 shadow-none focus-visible:ring-0 dark:bg-transparent"
                 onKeyDown={(e) => {
                   if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, hits.length - 1)); }
                   if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
                   if (e.key === "Enter") { e.preventDefault(); if (hits[sel]) pick(hits[sel]); else if (q.trim()) setAsked(q.trim()); }
                 }} />
        </div>
        <ul id="search-hits" ref={list} role="listbox" className="max-h-[55vh] overflow-y-auto p-1.5">
          {hits.map((h, i) => (
            <li key={h.key} role="option" aria-selected={i === sel}>
              <button type="button" onClick={() => pick(h)} onMouseMove={() => setSel(i)}
                      className={cn("flex w-full items-start gap-3 rounded-md px-2.5 py-2 text-left", i === sel && "bg-accent")}>
                <span className="mt-0.5 shrink-0 text-muted-foreground">{h.icon}</span>
                <span className="min-w-0 flex-1">
                  <span className="line-clamp-2 text-sm [overflow-wrap:anywhere]"><MdLine>{h.title}</MdLine></span>
                  <span className="block truncate text-xs text-muted-foreground">{h.kind} · {h.where}</span>
                </span>
              </button>
            </li>
          ))}
          {!hits.length && <li className="px-3 py-6 text-center text-sm text-muted-foreground">
            {!q.trim() ? "Type to search this Course." : isFetching ? "Searching the course material…" : asked === q.trim() ? "Nothing found." : "No Section, Concept or Block matches."}</li>}
        </ul>
        {!!q.trim() && asked !== q.trim() && (
          <button type="button" onClick={() => setAsked(q.trim())} className="flex w-full items-center gap-2 border-t border-border px-4 py-2.5 text-left text-sm text-muted-foreground hover:text-foreground">
            <Search className="size-4" />Search the professor's pages for “{q.trim()}”{!hits.length && <kbd className="ml-auto rounded border border-border px-1.5 text-xs">Enter</kbd>}</button>
        )}
        {isFetching && !!hits.length && <p className="border-t border-border px-4 py-2 text-sm text-muted-foreground" role="status">Searching the course material…</p>}
      </DialogContent>
    </Dialog>
  );
}

const KEYS: [string, string][] = [["/ or Ctrl K", "Search the Course"], ["n and p", "Next and previous Section (also ] and [)"], ["t", "Open or close the tutor"],
  ["+ and −", "Larger and smaller text"], ["?", "This list"]];

export function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader><DialogTitle>Keyboard shortcuts</DialogTitle><DialogDescription>They work whenever you are not typing in a field.</DialogDescription></DialogHeader>
        <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 text-sm">
          {KEYS.map(([k, what]) => <div key={k} className="contents"><dt><kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-xs">{k}</kbd></dt><dd>{what}</dd></div>)}
        </dl>
      </DialogContent>
    </Dialog>
  );
}

/** Runs `on(key, event)` for plain key presses outside fields and editors. */
export function useShortcuts(on: (key: string, e: KeyboardEvent) => void) {
  const ref = useRef(on);
  ref.current = on;
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = !!t?.closest?.("input, textarea, select, [contenteditable], .cm-editor, [role=dialog]");
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") return ref.current("search", e);
      if (!typing && !e.ctrlKey && !e.metaKey && !e.altKey) ref.current(e.key, e);
    };
    addEventListener("keydown", h);
    return () => removeEventListener("keydown", h);
  }, []);
}
