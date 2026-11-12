import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AArrowDown, AArrowUp, ChevronDown, Clock, History, Keyboard, List, MessageCircle, Pencil, Plus, Search, Send, Square, Trash2, Undo2, X } from "lucide-react";
import { BlockBody, PageViewer, ReaderBlock, type Style } from "@/components/blocks";
import { Md, MdLine } from "@/components/md";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { get, readEvents, send, type Block, type Chapter, type Citation, type Course, type Note, type Standing } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ConfidenceCheck, Outline, ReadingBar, SearchPalette, ShortcutsDialog, WarmUp, scrollToBlock, sectionMinutes, useShortcuts } from "./reader-tools";
import { useCid } from "./run";

type Change = { action: "add" | "replace" | "move" | "remove"; target: number | null; after: number | null;
  block: Omit<Block, "id" | "position" | "status" | "flags"> | null; flags: { errors: string[]; warnings: string[] } };
type Proposal = { changes: Change[]; flags: { errors: string[]; warnings: string[] }; status: "open" | "accepted" | "dismissed" | "rolled_back"; can_undo: boolean };
export type Preview = { mid: number; sectionId: number; blocks: (Block & { mark: Mark })[] };
type Mark = "added" | "replaced" | "moved" | "removed" | null;
type Msg = { id?: number; role: "learner" | "tutor"; text: string; citations?: Citation[]; proposal?: Proposal | null; error?: boolean };
type Conversation = { id: number; question: string; section_id: number | null; section: string | null; last_at: string };

const PROPOSAL = /```proposal[\s\S]*?(```|$)/;  // the Block JSON shows as a card, not as text

/** "Block 1234", "blocks 1206, 1207 et 1208" and "(2807)" as links to those Blocks, for ids the Course has (so a year stays a year). */
const linkBlocks = (text: string, known?: Set<number>) => !known ? text : text
  .replace(/\b(blocs?|blocks?)(\s+)(\d{3,6}(?:\s*(?:,|and|et|or|ou|&|\/)\s*\d{3,6})*)/gi,
    (_, w, sp, list: string) => w + sp + list.replace(/\d{3,6}/g, (n) => known.has(+n) ? `[${n}](#block-${n})` : n))
  .replace(/\((\d{3,6})\)/g, (m, n) => known.has(+n) ? `([${n}](#block-${n}))` : m);

const MARK: Record<NonNullable<Mark>, [string, string]> = {
  added: ["Added", "border-ok"], replaced: ["Changed", "border-primary"], moved: ["Moved", "border-warn"], removed: ["Removed", "border-destructive opacity-50"],
};

/** The Section as a tutor proposal would leave it: every Block in order, the changed ones marked. Nothing is written yet. */
function PreviewBlocks({ cid, preview }: { cid: number; preview: Preview }) {
  return <>{preview.blocks.map((b, i) => (
    <div key={i} className={cn(b.mark && "border-l-4 pl-4", b.mark && MARK[b.mark][1])}>
      {b.mark && <p className="mb-2 font-sans text-xs font-medium uppercase tracking-wide text-muted-foreground">{MARK[b.mark][0]}</p>}
      <div className={cn(b.mark === "removed" && "line-through decoration-destructive/60")}><BlockBody cid={cid} block={b} /></div>
    </div>
  ))}</>;
}

function ProposalCard({ cid, mid, p, sectionId, previewing, onPreview, onDone, onFix }: {
  cid: number; mid: number; p: Proposal; sectionId?: number; previewing: boolean; onFix?: (errors: string[]) => void;
  onPreview: (p: Preview | null) => void; onDone: (status: Proposal["status"], can_undo: boolean) => void }) {
  const qc = useQueryClient();
  const act = useMutation({
    mutationFn: (what: "accept" | "dismiss" | "rollback") => send(`/api/courses/${cid}/tutor/messages/${mid}/${what}`, {}),
    onSuccess: (_, what) => {
      onPreview(null);
      onDone(what === "accept" ? "accepted" : what === "dismiss" ? "dismissed" : "rolled_back", what === "accept");
      if (what !== "dismiss") qc.invalidateQueries({ queryKey: ["reader", cid] });
    },
  });
  const look = useMutation({
    mutationFn: () => get<Preview["blocks"]>(`/api/courses/${cid}/tutor/messages/${mid}/preview`),
    onSuccess: (blocks) => { onPreview({ mid, sectionId: sectionId!, blocks }); window.scrollTo({ top: 0, behavior: "smooth" }); },
  });
  const kind = (c: Change) => c.block?.component.replaceAll("_", " ") ?? "Block";
  const show = (id: number, label: string) => <button type="button" className="underline decoration-dotted underline-offset-4 hover:text-foreground" onClick={() => scrollToBlock(id)}>{label}</button>;
  const line = (c: Change) => c.action === "move" ? <>Move {show(c.target!, `this ${kind(c)}`)} {c.after != null ? <>after {show(c.after, "this Block")}</> : "to the start"}</>
    : c.action === "remove" ? <>Remove {show(c.target!, `this ${kind(c)}`)}</>
    : c.action === "replace" ? <>Change {show(c.target!, "this Block")} into a {kind(c)}</>
    : <>Add a {kind(c)} {c.target != null ? <>after {show(c.target, "this Block")}</> : "at the end"}</>;
  const many = p.changes.length > 1;
  return (
    <div className="mt-3 overflow-hidden rounded-md border border-border bg-background">
      <p className="flex items-center justify-between gap-2 border-b border-border bg-muted/60 px-3 py-1.5 text-xs text-muted-foreground">
        <span>{many ? `${p.changes.length} proposed changes` : p.changes.length ? line(p.changes[0]) : "Proposed change"}</span>
        {p.status !== "open" && <span className={cn("font-medium", p.status === "accepted" && "text-ok")}>{p.status.replace("_", " ")}</span>}
      </p>
      {p.changes.map((c, k) => (
        <details key={k} open={!many && c.action !== "remove" && c.action !== "move"} className="border-b border-border last:border-b-0">
          <summary className={cn("cursor-pointer px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground", !many && "sr-only")}>{k + 1}. {line(c)}</summary>
          <div className={cn("prose-cf max-h-[60vh] max-w-none overflow-y-auto px-3 py-2 text-sm", c.action === "remove" && "line-through opacity-60")}>
            {c.block && <BlockBody cid={cid} block={{ ...c.block, id: 0, position: 0, status: "ok", flags: [] }} />}</div>
        </details>
      ))}
      {!!p.flags.errors.length && (
        <ul className="space-y-1 border-t border-border px-3 py-2 text-xs text-destructive">
          <li className="font-medium">It fails the Block checks, so it can't be applied:</li>
          {p.flags.errors.map((e, i) => <li key={i} className="[overflow-wrap:anywhere]">{e}</li>)}
        </ul>
      )}
      {(p.status === "open" || p.can_undo) && (
        <div className="flex flex-wrap justify-end gap-2 border-t border-border px-3 py-2">
          {p.status === "open" ? <>
            <Button size="sm" variant="ghost" disabled={act.isPending} onClick={() => act.mutate("dismiss")}>Dismiss</Button>
            {!!p.flags.errors.length && onFix && <Button size="sm" disabled={act.isPending}
              onClick={() => act.mutate("dismiss", { onSuccess: () => onFix(p.flags.errors) })}>Ask it to fix this</Button>}
            {!p.flags.errors.length && sectionId && <Button size="sm" variant="outline" disabled={look.isPending}
              onClick={() => previewing ? onPreview(null) : look.mutate()}>{previewing ? "Hide preview" : "Preview in the Section"}</Button>}
            {!p.flags.errors.length && <Button size="sm" disabled={act.isPending} onClick={() => act.mutate("accept")}>{many ? "Apply all" : "Apply"}</Button>}
          </> : <Button size="sm" variant="outline" disabled={act.isPending} onClick={() => act.mutate("rollback")}>Undo</Button>}
        </div>
      )}
      {(act.error || look.error) && <p className="px-3 pb-2 text-xs text-destructive">{String((act.error ?? look.error)!.message)}</p>}
    </div>
  );
}

/** The tutor panel. With `lab`, it coaches on a Lab Step: the learner's current code and last outputs go with each question.
 * In the reader it reopens the Section's latest conversation, and lists past ones to reopen or delete. */
export type Explain = { block_id: number; style: Style; label: string; n: number };

export function Tutor({ cid, sectionId, lab, explain, onCite, onClose, className, preview, onPreview = () => {}, blocks, onBlock }: {
  cid: number; sectionId?: number; lab?: () => { lab_step_id: number; code: string; outputs: unknown[] };
  explain?: Explain | null; onCite: (c: Citation) => void; onClose: () => void; className?: string;
  preview?: Preview | null; onPreview?: (p: Preview | null) => void; blocks?: Set<number>; onBlock?: (id: number) => void;
}) {
  const qc = useQueryClient();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [conv, setConv] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const stop = useRef<AbortController | null>(null);
  const [editing, setEditing] = useState<{ at: number; text: string } | null>(null);
  const [trouble, setTrouble] = useState("");
  const { data: convs = [] } = useQuery({ queryKey: ["tutor", cid], enabled: !lab,
    queryFn: () => get<Conversation[]>(`/api/courses/${cid}/tutor`) });
  const open = async (id: number | null) => {
    setConv(id); setHistory(false);
    setMsgs(id === null ? [] : await get<Msg[]>(`/api/courses/${cid}/tutor/${id}`));
  };
  const opened = useRef<number | undefined>(undefined);
  useEffect(() => {  // "Explain this differently" starts its own conversation; before the effect below, so it doesn't reopen another
    if (!explain || busy) return;
    opened.current = sectionId;
    ask(explain.label, { block_id: explain.block_id, style: explain.style });
  }, [explain?.n]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {  // a Section opens on its latest conversation, once the list has loaded
    if (lab || busy || opened.current === sectionId || !qc.getQueryData(["tutor", cid])) return;
    opened.current = sectionId;
    open(convs.find((c) => c.section_id === sectionId)?.id ?? null);
  }, [sectionId, convs]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { box.current?.scrollTo({ top: box.current.scrollHeight }); }, [msgs]);  // the list only: scrollIntoView also scrolled the page, back to the Section's top
  const remove = useMutation({
    mutationFn: (id: number) => send(`/api/courses/${cid}/tutor/${id}`, undefined, "DELETE"),
    onSuccess: (_, id) => { if (id === conv) open(null); qc.invalidateQueries({ queryKey: ["tutor", cid] }); },
  });
  /** `keep`: the messages to ask after (an edited question drops the ones from it on); none kept starts a new conversation. */
  const ask = async (asked?: string, about?: { block_id: number; style: Style }, keep?: Msg[]) => {
    const question = asked ?? q.trim();
    if (!question || busy) return;
    if (!about && asked === undefined) setQ("");
    const fresh = !!about || keep?.length === 0;
    setBusy(true); setHistory(false); setTrouble("");
    if (fresh) setConv(null);
    setMsgs((m) => [...(about ? [] : keep ?? m), { role: "learner", text: question }, { role: "tutor", text: "" }]);
    const patch = (f: (m: Msg) => Msg) => setMsgs((all) => [...all.slice(0, -1), f(all[all.length - 1])]);
    stop.current = new AbortController();
    try {
      const res = await fetch(`/api/courses/${cid}/tutor`, { method: "POST", headers: { "content-type": "application/json" }, signal: stop.current.signal,
        body: JSON.stringify({ question, section_id: sectionId ?? null, conversation_id: fresh ? null : conv, ...lab?.(), ...about }) });
      await readEvents(res, (ev, d) => {
        if (ev === "token") patch((m) => ({ ...m, text: m.text + d.text }));
        if (ev === "done") { setConv(d.conversation_id); setMsgs((all) => [...all.slice(0, -2), { ...all.at(-2)!, id: d.question_id },
          { ...all.at(-1)!, id: d.message_id, citations: d.citations, proposal: d.proposal }]); }
        if (ev === "error") patch((m) => ({ ...m, text: d.message, error: true }));
      });
    } catch (e) {
      if (stop.current?.signal.aborted) { setMsgs((all) => all.slice(0, -2)); setQ(question); }  // stopped: nothing was kept, the question goes back in the box
      else patch((m) => ({ ...m, text: String(e), error: true }));
    } finally { stop.current = null; setBusy(false); if (!lab) qc.invalidateQueries({ queryKey: ["tutor", cid] }); }
  };
  /** Removes the learner's message at `i` and what follows, on the server too; then asks `again` when given. */
  const takeBack = async (i: number, again?: string) => {
    const m = msgs[i];
    try { if (m.id) await send(`/api/courses/${cid}/tutor/messages/${m.id}`, undefined, "DELETE"); }
    catch (e) { setTrouble(String((e as Error).message)); return; }
    setEditing(null);
    const kept = msgs.slice(0, i);
    if (again) ask(again, undefined, kept);
    else { setMsgs(kept); setQ(m.text); if (!kept.length) setConv(null); qc.invalidateQueries({ queryKey: ["tutor", cid] }); }
  };
  const title = convs.find((c) => c.id === conv)?.question;
  return (
    <aside className={cn("flex h-full flex-col border-l border-border bg-card", className)} aria-label="Tutor">
      <div className="flex items-center gap-1 border-b border-border py-1.5 pl-4 pr-2">
        <p className="min-w-0 flex-1 truncate text-sm"><span className="font-medium">Tutor</span>
          {title && <span className="text-muted-foreground"> · {title}</span>}</p>
        {!lab && <>
          <Button size="icon" variant="ghost" className="size-7" aria-label="New conversation" title="New conversation" disabled={busy}
                  onClick={() => open(null)}><Plus className="size-4" /></Button>
          <Button size="icon" variant={history ? "secondary" : "ghost"} className="size-7" aria-label="Past conversations" aria-expanded={history}
                  title="Past conversations" onClick={() => setHistory(!history)}><History className="size-4" /></Button>
        </>}
        <Button size="icon" variant="ghost" className="size-7" onClick={onClose} aria-label="Close the tutor"><X className="size-4" /></Button>
      </div>
      {history ? (
        <ul className="flex-1 divide-y divide-border overflow-y-auto" aria-label="Past conversations">
          {!convs.length && <li className="px-4 py-3 text-sm text-muted-foreground">No conversation yet.</li>}
          {convs.map((c) => (
            <li key={c.id} className={cn("group flex items-start gap-2 px-4 py-2.5 hover:bg-accent/50", c.id === conv && "bg-accent")}>
              <button type="button" className="min-w-0 flex-1 text-left" onClick={() => open(c.id)} disabled={busy}>
                <span className="line-clamp-2 text-sm [overflow-wrap:anywhere]">{c.question}</span>
                <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                  {c.section ?? "No Section"} · {new Date(c.last_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</span>
              </button>
              <Button size="icon" variant="ghost" className="size-7 shrink-0 opacity-60 group-hover:opacity-100" aria-label={`Delete “${c.question}”`}
                      disabled={remove.isPending} onClick={() => remove.mutate(c.id)}><Trash2 className="size-3.5" /></Button>
            </li>
          ))}
        </ul>
      ) : (
        <div ref={box} className="flex-1 space-y-5 overflow-y-auto px-4 py-4 text-[0.95rem]">
          {!msgs.length && <p className="text-sm text-muted-foreground">{lab ? "Ask about your code. The tutor sees it, its output and plots, and coaches you without giving the answer."
            : "Ask about this Section, or ask for a Block to add. Answers come from your course material and cite its pages."}</p>}
          {msgs.map((m, i) => m.role === "learner" ? (editing?.at === i ? (
            <form key={i} className="ml-auto w-full max-w-[90%] space-y-2" onSubmit={(e) => { e.preventDefault(); if (editing.text.trim()) takeBack(i, editing.text.trim()); }}>
              <Textarea value={editing.text} onChange={(e) => setEditing({ at: i, text: e.target.value })} rows={3} aria-label="Edit your question" autoFocus
                        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } if (e.key === "Escape") setEditing(null); }} />
              <p className="text-xs text-muted-foreground">Sending replaces this question and every message after it.</p>
              <div className="flex justify-end gap-2">
                <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                <Button type="submit" size="sm" disabled={!editing.text.trim()}>Send again</Button>
              </div>
            </form>
          ) : (
            <div key={i} className="group ml-auto flex w-fit max-w-[90%] items-start gap-1">
              {!busy && (
                <span className="flex shrink-0 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                  <Button size="icon" variant="ghost" className="size-7" aria-label="Edit and ask again" title="Edit and ask again"
                          onClick={() => setEditing({ at: i, text: m.text })}><Pencil className="size-3.5" /></Button>
                  <Button size="icon" variant="ghost" className="size-7" aria-label="Take this question back" title="Take this question back (removes it and what follows)"
                          onClick={() => takeBack(i)}><Undo2 className="size-3.5" /></Button>
                </span>
              )}
              <p className="whitespace-pre-wrap rounded-lg rounded-br-sm bg-primary/10 px-3 py-2 text-sm [overflow-wrap:anywhere]">{m.text}</p>
            </div>
          )) : (
            <div key={i} className={cn("min-w-0", m.error && "text-destructive")}>
              {m.text.replace(PROPOSAL, "").trim() ? <div onClick={(e) => {
                  const a = (e.target as HTMLElement).closest<HTMLAnchorElement>('a[href^="#block-"]');
                  if (a && onBlock) { e.preventDefault(); onBlock(Number(a.hash.slice(7))); } }}>
                  <Md className="tutor-answer">{linkBlocks(m.text.replace(PROPOSAL, ""), blocks)}</Md></div>
                : !m.proposal && <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
                    <span className="flex gap-1" aria-hidden>{[0, 1, 2].map((k) => <span key={k} className="size-1.5 animate-pulse rounded-full bg-muted-foreground" style={{ animationDelay: `${k * 150}ms` }} />)}</span>
                    {PROPOSAL.test(m.text) ? "Writing a Block…" : "Thinking…"}</p>}
              {!!m.citations?.length && (
                <p className="mt-2 flex flex-wrap gap-1.5">
                  {m.citations.map((c, k) => <button key={k} type="button" onClick={() => onCite(c)}
                    className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground hover:border-primary hover:text-primary">{c.source} p.{c.page}</button>)}
                </p>
              )}
              {m.proposal && m.id && <ProposalCard cid={cid} mid={m.id} p={m.proposal} sectionId={sectionId} previewing={preview?.mid === m.id} onPreview={onPreview}
                onFix={busy ? undefined : (errors) => ask("Your proposal failed the checks, so it could not be applied. The exact errors:\n"
                  + errors.map((e) => `- ${e}`).join("\n") + "\nFix exactly these and send the corrected proposal, with the same changes otherwise.")}
                onDone={(status, can_undo) => setMsgs((all) => all.map((x) => x === m ? { ...x, proposal: { ...m.proposal!, status, can_undo } } : x))} />}
            </div>
          ))}
          {trouble && <p className="text-xs text-destructive" role="alert">{trouble}</p>}
        </div>
      )}
      <form className="flex items-end gap-2 border-t border-border p-3" onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <Textarea value={q} onChange={(e) => setQ(e.target.value)} rows={2} placeholder={lab ? "Why does this raise a TypeError?" : "Ask about this Section…"} aria-label="Question"
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } }} className="max-h-40 min-h-0 resize-none" />
        {busy ? <Button type="button" size="icon" variant="outline" aria-label="Stop" title="Stop: the question goes back in the box"
                        onClick={() => stop.current?.abort()}><Square className="size-3.5 fill-current" /></Button>
          : <Button type="submit" size="icon" disabled={!q.trim()} aria-label="Ask"><Send className="size-4" /></Button>}
      </form>
    </aside>
  );
}

/** Where you are in the Chapter: its big picture (from the Chapter plan) and each Section with what it lets you do. Open on the
 * Chapter's first Section, folded after. */
function ChapterMap({ chapter, current, read, go }: { chapter: Chapter; current: number; read: Set<number>; go: (id: number) => void }) {
  const at = chapter.sections.findIndex((s) => s.id === current);
  return (
    <details key={current} open={at === 0} className="group mt-4 rounded-lg border border-border px-4 py-3 text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-3">
        <span className="shrink-0 font-medium">Section {at + 1} of {chapter.sections.length}</span>
        <Progress value={((at + 1) / chapter.sections.length) * 100} className="h-1.5" aria-label="Place in the Chapter" />
        <span className="shrink-0 text-muted-foreground group-open:hidden">Chapter map</span>
      </summary>
      {/* the model ends its overview with a map of the Sections, in whatever list form it likes: the Section list below is that map */}
      {chapter.overview && <p className="mt-3 text-muted-foreground"><MdLine>{chapter.overview.replace(/\\n/g, "\n").split(/\n+\s*(?:[-*•]\s|\d+[.)]\s|§\s*\d)/)[0].replace(/\n+[^\n]*:\s*$/, "")}</MdLine></p>}
      <ol className="mt-3 space-y-1">
        {chapter.sections.map((s, n) => (
          <li key={s.id}>
            <button type="button" onClick={() => go(s.id)} aria-current={s.id === current ? "step" : undefined}
                    className={cn("flex w-full gap-2 rounded-md px-2 py-1 text-left hover:bg-accent", s.id === current && "bg-accent")}>
              <span className={cn("tabular w-5 shrink-0", read.has(s.id) ? "text-ok" : "text-muted-foreground")}>{n + 1}.</span>
              <span><span className={cn(s.id === current && "font-medium")}>{s.title}</span>
                {s.objectives?.[0] && <span className="block text-muted-foreground"><MdLine>{s.objectives[0]}</MdLine></span>}</span>
            </button>
          </li>
        ))}
      </ol>
    </details>
  );
}

/** Every Chapter with its Sections: the side rail on wide screens, the Contents dialog on narrow ones. */
function ChapterList({ chapters, current, read, cram, go, outline }: {
  chapters: Chapter[]; current?: number; read: Set<number>; cram: boolean; go: (id: number) => void; outline?: React.ReactNode }) {
  const [open, setOpen] = useState(() => { try { return localStorage.getItem("cf-outline") !== "closed"; } catch { return true; } });
  const flip = () => setOpen((o) => { try { localStorage.setItem("cf-outline", o ? "closed" : "open"); } catch { /* storage blocked */ } return !o; });
  return (
    <div className="space-y-5">
      {chapters.map((c) => (
        <div key={c.id}>
          <p className="flex items-baseline justify-between gap-2 px-2 font-display text-sm font-semibold">{c.title}
            <span className="tabular shrink-0 font-sans text-xs font-normal text-muted-foreground">
              {cram ? `${Math.round(c.exam_weight * 100)}% of exams` : `${c.sections.filter((s) => read.has(s.id)).length}/${c.sections.length}`}</span></p>
          <ul className="mt-1">
            {c.sections.map((s) => (
              <li key={s.id}>
                <div className={cn("flex items-start rounded-md text-muted-foreground", s.id === current && "bg-accent text-foreground")}>
                  <button type="button" onClick={() => go(s.id)} aria-current={s.id === current ? "page" : undefined}
                          className="flex min-w-0 flex-1 items-center gap-2 px-2 py-1 text-left text-sm hover:text-foreground">
                    <span className={cn("size-1.5 shrink-0 rounded-full", read.has(s.id) ? "bg-ok" : "bg-border")} aria-label={read.has(s.id) ? "read" : undefined} />
                    {s.title}
                  </button>
                  {s.id === current && outline && (
                    <button type="button" onClick={flip} aria-expanded={open} aria-label="In this Section" title="In this Section"
                            className="grid size-7 shrink-0 place-items-center rounded-md text-muted-foreground hover:text-foreground">
                      <ChevronDown className={cn("size-4 transition-transform", !open && "-rotate-90")} /></button>
                  )}
                </div>
                {s.id === current && open && outline}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

const SCALES = [0.9, 1, 1.1, 1.2, 1.35];
const tool = "grid size-8 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40 disabled:hover:bg-transparent";

export function Reader() {
  const cid = useCid();
  const qc = useQueryClient();
  const { data: chapters = [] } = useQuery({ queryKey: ["reader", cid], queryFn: () => get<Chapter[]>(`/api/courses/${cid}/reader`) });
  const { data: place } = useQuery({ queryKey: ["place", cid], queryFn: () => get<{ section_id: number | null; read: number[] }>(`/api/courses/${cid}/place`) });
  const { data: course } = useQuery({ queryKey: ["course", String(cid)], queryFn: () => get<Course>(`/api/courses/${cid}`) });
  const { data: notes = [] } = useQuery({ queryKey: ["notes", cid], queryFn: () => get<Note[]>(`/api/courses/${cid}/notes`) });
  const { data: results = {} } = useQuery({ queryKey: ["results", cid], queryFn: () => get<Record<string, Standing>>(`/api/courses/${cid}/results`) });
  useEffect(() => {  // an answer anywhere in the Section updates what the reader shows about it
    const on = () => { for (const k of ["results", "progress"]) qc.invalidateQueries({ queryKey: [k, cid] }); };
    addEventListener("cf-attempt", on);
    return () => removeEventListener("cf-attempt", on);
  }, [cid, qc]);
  const url = new URLSearchParams(location.search);
  const [sid, setSid] = useState<number | null>(() => Number(url.get("section")) || null);
  const [target, setTarget] = useState<number | null>(() => Number(url.get("block")) || null);
  const [cite, setCite] = useState<Citation | null>(null);
  const [tutor, setTutor] = useState(false);
  const [tutorW, setTutorW] = useState(() => { try { return Number(localStorage.getItem("cf-tutor-w")) || 384; } catch { return 384; } });
  const dragging = useRef(false);
  const sizeTutor = (w: number) => { const v = Math.round(Math.max(320, Math.min(w, innerWidth * 0.6)));
    setTutorW(v); try { localStorage.setItem("cf-tutor-w", String(v)); } catch { /* private window: the width just isn't kept */ } };
  const [explain, setExplain] = useState<Explain | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [panel, setPanel] = useState<"search" | "keys" | "contents" | null>(null);
  const [scale, setScale] = useState(() => { try { return Number(localStorage.getItem("cf-read-scale")) || 1; } catch { return 1; } });
  const resize = (by: number) => setScale((s) => {
    const next = SCALES[Math.max(0, Math.min(SCALES.length - 1, SCALES.indexOf(s) + by))] ?? 1;
    try { localStorage.setItem("cf-read-scale", String(next)); } catch { /* storage blocked */ }
    return next;
  });
  const explainBlock = (block_id: number, style: Style, label: string) => { setTutor(true); setExplain((e) => ({ block_id, style, label, n: (e?.n ?? 0) + 1 })); };
  const mark = useMutation({ mutationFn: (section_id: number) => send(`/api/courses/${cid}/place`, { section_id }, "PUT"),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["place", cid] }); qc.invalidateQueries({ queryKey: ["progress", cid] }); } });
  const saveNote = (block_id: number) => (text: string) =>
    send(`/api/courses/${cid}/blocks/${block_id}/note`, { text }, "PUT").then(() => qc.invalidateQueries({ queryKey: ["notes", cid] }));
  const sections = chapters.flatMap((c) => c.sections.map((s) => ({ ...s, chapter: c })));
  const current = sections.find((s) => s.id === sid) ?? sections.find((s) => s.id === place?.section_id) ?? sections[0];
  useEffect(() => { if (current) mark.mutate(current.id); }, [current?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (target && current?.blocks.some((b) => b.id === target)) { scrollToBlock(target); setTarget(null); } }, [target, current?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const read = new Set(place?.read ?? []);
  const noteOf = new Map(notes.map((n) => [n.block_id, n.text]));
  const i = current ? sections.indexOf(current) : -1;
  const go = (id: number, block?: number) => { setPanel(null); setSid(id); if (block) setTarget(block); else scrollTo({ top: 0 }); };
  const previous = i > 0 && sections[i - 1].chapter.id === current?.chapter.id ? sections[i - 1] : null;
  useShortcuts((key, e) => {
    if (key === "search" || key === "/") { e.preventDefault(); setPanel("search"); }
    else if (key === "?") setPanel("keys");
    else if ((key === "]" || key === "n") && i < sections.length - 1) go(sections[i + 1].id);
    else if ((key === "[" || key === "p") && i > 0) go(sections[i - 1].id);
    else if (key === "t") setTutor((t) => !t);
    else if (key === "+" || key === "=") resize(1);
    else if (key === "-") resize(-1);
  });
  if (!chapters.length) return <p className="px-6 py-10 text-muted-foreground">No Chapter is published yet. Publish Chapters from Review.</p>;
  const cram = course?.goal === "cram";
  return (
    <div className={cn("grid min-h-[calc(100dvh-3rem)]", tutor ? "lg:grid-cols-[17rem_minmax(0,1fr)_var(--tutor-w)]" : "lg:grid-cols-[17rem_1fr]")}
         style={{ "--tutor-w": `${tutorW}px` } as React.CSSProperties}>
      <ReadingBar />
      <nav className="hidden border-r border-border px-3 py-6 lg:block" aria-label="Chapters">
        <div className="sticky top-18 max-h-[calc(100dvh-6rem)] overflow-y-auto">
          <ChapterList chapters={chapters} current={current?.id} read={read} cram={cram} go={go}
                       outline={current && <Outline section={current} notes={noteOf} results={results} />} />
        </div>
      </nav>
      {current && (
        <article className="mx-auto w-full min-w-0 max-w-[44rem] px-5 py-8 sm:px-8">
          <div className="flex items-center gap-1">
            <p className="mr-auto min-w-0 truncate text-sm text-muted-foreground">{current.chapter.title}</p>
            <button type="button" className={cn(tool, "lg:hidden")} onClick={() => setPanel("contents")} aria-label="Contents"><List className="size-4" /></button>
            <button type="button" className={tool} onClick={() => setPanel("search")} aria-label="Search the Course (/)" title="Search the Course (/)"><Search className="size-4" /></button>
            <button type="button" className={tool} onClick={() => resize(-1)} disabled={scale === SCALES[0]} aria-label="Smaller text" title="Smaller text (−)"><AArrowDown className="size-4" /></button>
            <button type="button" className={tool} onClick={() => resize(1)} disabled={scale === SCALES.at(-1)} aria-label="Larger text" title="Larger text (+)"><AArrowUp className="size-4" /></button>
            <button type="button" className={cn(tool, "hidden sm:grid")} onClick={() => setPanel("keys")} aria-label="Keyboard shortcuts (?)" title="Keyboard shortcuts (?)"><Keyboard className="size-4" /></button>
          </div>
          <h1 className="mt-1 font-display text-3xl font-semibold tracking-tight">{current.title}</h1>
          <p className="mt-2 flex items-center gap-1.5 text-sm text-muted-foreground"><Clock className="size-3.5" />About {sectionMinutes(current)} min, practice included</p>
          <ChapterMap chapter={current.chapter} current={current.id} read={read} go={go} />
          {!!current.teaches?.length && <p className="mt-2 text-sm text-muted-foreground">New here: {current.teaches.join(" · ")}</p>}
          {!!current.objectives?.length && (
            <div className="mt-4 text-sm">
              <p className="font-medium">You'll be able to</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted-foreground">{current.objectives.map((o, i) => <li key={i}><MdLine>{o}</MdLine></li>)}</ul>
            </div>
          )}
          {previous && <WarmUp previous={previous} />}
          {preview?.sectionId === current.id && (
            <div className="sticky top-14 z-10 mt-6 flex flex-wrap items-center gap-3 rounded-md border border-primary/40 bg-card px-4 py-2 text-sm shadow-sm">
              <span className="mr-auto">Preview: the Section with the tutor's changes. Nothing is applied yet; apply or dismiss it in the tutor.</span>
              <Button size="sm" variant="outline" onClick={() => setPreview(null)}>Back to the Section</Button>
            </div>
          )}
          <div className="prose-cf mt-8 space-y-10" style={{ "--read-scale": scale } as React.CSSProperties}>
            {preview?.sectionId === current.id ? <PreviewBlocks cid={cid} preview={preview} /> : current.blocks.map((b) => <ReaderBlock key={b.id} block={b} cid={cid} onCite={setCite} onExplain={explainBlock} note={noteOf.get(b.id)} onNote={saveNote(b.id)} standing={results[b.id]} />)}
          </div>
          <ConfidenceCheck cid={cid} section={current} onAsk={() => setTutor(true)} />
          <div className="mt-8 flex justify-between gap-4 border-t border-border pt-4 text-sm">
            {i > 0 ? <button type="button" onClick={() => go(sections[i - 1].id)} className="text-left hover:text-primary">← {sections[i - 1].title}</button> : <span />}
            {i < sections.length - 1 && <button type="button" onClick={() => go(sections[i + 1].id)} className="text-right hover:text-primary">{sections[i + 1].title} →</button>}
          </div>
        </article>
      )}
      {tutor ? (
        <div className="fixed inset-x-0 bottom-0 top-12 z-20 lg:sticky lg:top-12 lg:h-[calc(100dvh-3rem)]">
          <div role="separator" aria-orientation="vertical" aria-label="Resize the tutor" aria-valuenow={tutorW} aria-valuemin={320} tabIndex={0}
               title="Drag to resize the tutor (or use the arrow keys)"
               className="absolute inset-y-0 -left-1 z-10 hidden w-2 cursor-col-resize touch-none transition-colors hover:bg-primary/40 focus-visible:bg-primary/60 focus-visible:outline-none lg:block"
               onPointerDown={(e) => { e.preventDefault(); dragging.current = true; try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* no capture: the drag still follows while over the handle */ } }}
               onPointerMove={(e) => { if (dragging.current) sizeTutor(innerWidth - e.clientX); }}
               onPointerUp={() => { dragging.current = false; }} onPointerCancel={() => { dragging.current = false; }}
               onKeyDown={(e) => { if (e.key === "ArrowLeft") sizeTutor(tutorW + 32); else if (e.key === "ArrowRight") sizeTutor(tutorW - 32); }} />
          <Tutor cid={cid} sectionId={current?.id} explain={explain} onCite={setCite} preview={preview} onPreview={setPreview}
                 blocks={new Set(sections.flatMap((s) => s.blocks.map((b) => b.id)))}
                 onBlock={(id) => { const s = sections.find((x) => x.blocks.some((b) => b.id === id)); if (!s) return;
                   setPreview(null); if (innerWidth < 1024) setTutor(false); go(s.id, id); }}
                 onClose={() => { setTutor(false); setExplain(null); setPreview(null); }} />
        </div>
      ) : (
        <Button className="fixed bottom-5 right-5 z-20 shadow-md" onClick={() => setTutor(true)}><MessageCircle className="size-4" />Ask the tutor</Button>
      )}
      <SearchPalette cid={cid} open={panel === "search"} onClose={() => setPanel(null)} chapters={chapters} notes={notes} go={go} onCite={setCite} />
      <ShortcutsDialog open={panel === "keys"} onClose={() => setPanel(null)} />
      <Dialog open={panel === "contents"} onOpenChange={(o) => !o && setPanel(null)}>
        <DialogContent className="max-h-[85dvh] overflow-y-auto">
          <DialogHeader><DialogTitle>Contents</DialogTitle><DialogDescription>A green dot marks a Section you have opened.</DialogDescription></DialogHeader>
          <ChapterList chapters={chapters} current={current?.id} read={read} cram={cram} go={go} />
        </DialogContent>
      </Dialog>
      <PageViewer cid={cid} cite={cite} onClose={() => setCite(null)} />
    </div>
  );
}
