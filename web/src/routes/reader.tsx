import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, AArrowDown, PanelLeftClose, PanelLeftOpen, AArrowUp, ChevronDown, Clock, Headphones, History, Eraser, EyeOff, Highlighter, Lasso, ImagePlus, Keyboard, List, MessageCircle, NotebookPen, Paperclip, Pencil, Plus, PenLine, Search, Send, Sparkles, Square, Trash2, Undo2, X } from "lucide-react";
import { BlockBody, PageViewer, ReaderBlock, type Style } from "@/components/blocks";
import { ActivityLine, type Activity } from "@/components/activity";
import { RememberedLine, type Remembered } from "@/components/remembered";
import { ContextChips, ContextPicker, ctxLabels, type Ctx } from "@/components/context-picker";
import { Md, MdLine } from "@/components/md";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { appended, DictateButton } from "@/components/dictation";
import { ListenBar } from "@/components/listen-bar";
import { BlockInk, dataUrl, InkPad, inkImage, WriteButton, type Pen, type Stroke } from "@/components/ink";
import type { Snapshot } from "@/components/notebook";

// the panel at the back stays mounted; Excalidraw forces visibility:visible on some controls, so opacity and inert hide them too
const HIDDEN = "invisible pointer-events-none absolute inset-0 opacity-0";
const Notebook = lazy(() => import("@/components/notebook"));
import { ApiError, DROPPED, answerAfterDrop, answerId, exported, get, readEvents, send, stopAnswer, type Block, type Chapter, type Citation, type Course, type Note, type Standing } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AskedText } from "@/components/asked";
import { ConfidenceCheck, InExam, InExamLink, ModeSelect, Outline, blockLabel, type Mode, ReadingBar, SearchPalette, ShortcutsDialog, WarmUp, scrollToBlock, sectionMinutes, useShortcuts } from "./reader-tools";
import { useCid } from "./run";

type Change = { action: "add" | "replace" | "move" | "remove"; target: number | null; after: number | null;
  block: Omit<Block, "id" | "position" | "status" | "flags"> | null; flags: { errors: string[]; warnings: string[] } };
type Proposal = { changes: Change[]; flags: { errors: string[]; warnings: string[] }; status: "open" | "accepted" | "dismissed" | "rolled_back"; can_undo: boolean };
export type Preview = { mid: number; sectionId: number; blocks: (Block & { mark: Mark })[] };
type Mark = "added" | "replaced" | "moved" | "removed" | null;
type Msg = { id?: number; role: "learner" | "tutor"; text: string; images?: string[]; blocks?: string[]; citations?: Citation[]; proposal?: Proposal | null; activity?: Activity[]; remembered?: Remembered | null; error?: boolean; mode?: string | null; anchor?: Citation | null };
type Conversation = { id: number; question: string; section_id: number | null; section: string | null; last_at: string };

const PROPOSAL = /```proposal[\s\S]*?(\n```|$)/g;  // the Block JSON shows as a card, not as text; it ends at a fence on its own line, as a fence inside a Block's text is escaped

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
/** "Explain this step" on a selection in a Block: the selected text, quoted, and the Block's cited page as the anchor (#30). */
export type StepAsk = { text: string; anchor: { source: string; page: number } | null; n: number };
type How = { mode?: "step" | "explain" | "beyond"; anchor?: StepAsk["anchor"] };

/** The selected text inside one reader Block, with where to show the "Explain this step" button. */
function selectedLine(): { text: string; block: number; x: number; y: number } | null {
  const s = window.getSelection();
  if (!s || s.isCollapsed || !s.rangeCount) return null;
  const text = s.toString().replace(/\s+/g, " ").trim();
  const el = (n: Node | null) => (n instanceof Element ? n : n?.parentElement)?.closest<HTMLElement>("[data-block]");
  const a = el(s.anchorNode), b = el(s.focusNode);
  if (text.length < 3 || !a || a !== b) return null;  // one Block at a time
  const r = s.getRangeAt(0).getBoundingClientRect();
  return { text: text.slice(0, 1200), block: Number(a.dataset.block), x: r.left, y: r.bottom };
}

/** A question asked for the learner by a button (type up my notes, work my ink into a Block), with images to go with it. */
export type Say = { text: string; images?: string[]; how?: How; n: number };

export function Tutor({ notes, say, cid, sectionId, lab, explain, step, onCite, onClose, className, preview, onPreview = () => {}, blocks, onBlock, attached = [], onAttached = () => {}, chapters = [], label }: {
  notes?: Snapshot | null; say?: Say | null; label?: React.ReactNode;
  chapters?: Chapter[]; cid: number; sectionId?: number; lab?: () => { lab_step_id: number; code: string; outputs: unknown[] };
  attached?: Block[]; onAttached?: (b: Block[]) => void;
  explain?: Explain | null; step?: StepAsk | null; onCite: (c: Citation) => void; onClose: () => void; className?: string;
  preview?: Preview | null; onPreview?: (p: Preview | null) => void; blocks?: Set<number>; onBlock?: (id: number) => void;
}) {
  const qc = useQueryClient();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  // the question box keeps its own text (typing must not re-render the conversation); state only knows if it is empty
  const qBox = useRef<HTMLTextAreaElement>(null), [hasQ, setHasQ] = useState(false);
  const setQ = (v: string | ((t: string) => string)) => {
    const el = qBox.current; if (!el) return;
    el.value = typeof v === "function" ? v(el.value) : v; setHasQ(!!el.value.trim());
  };
  /** Sections (a Chapter is all of its Sections) the tutor answers from too: for the next answer, or pinned until removed. */
  const [ctx, setCtx] = useState<Ctx>({});
  const [images, setImages] = useState<string[]>([]);  // data: URLs, pasted or picked, sent with the next question
  const addImages = (files: Iterable<File>) => {
    for (const f of files) {
      if (!/^image\/(png|jpeg|webp)$/.test(f.type)) { setTrouble("Images only: PNG, JPEG or WebP."); continue; }
      if (f.size > 8_000_000) { setTrouble(`${f.name || "That image"} is over 8 MB.`); continue; }
      const r = new FileReader();
      r.onload = () => setImages((all) => [...all, String(r.result)].slice(0, 6));
      r.readAsDataURL(f);
    }
  };
  const [conv, setConv] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [pick, setPick] = useState<Mode | "">("");  // the mode of typed questions; Auto leaves it to the server (#30)
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
  useEffect(() => {  // "Explain this step": asked in the open conversation, in Step mode, anchored to the selection's page
    if (!step || busy) return;
    opened.current = sectionId;
    ask(`« ${step.text} »\n\nExplain this step.`, undefined, undefined, { mode: "step", anchor: step.anchor });
  }, [step?.n]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {  // a button asked for the learner, in the open conversation
    if (!say || busy) return;
    opened.current = sectionId;
    ask(say.text, undefined, undefined, say.how ?? {}, say.images);
  }, [say?.n]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {  // a Section opens on its latest conversation, once the list has loaded
    if (lab || busy || opened.current === sectionId || !qc.getQueryData(["tutor", cid])) return;
    opened.current = sectionId;
    open(convs.find((c) => c.section_id === sectionId)?.id ?? null);
  }, [sectionId, convs]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { box.current?.scrollTo({ top: box.current.scrollHeight }); }, [msgs.length]);  // not on each streamed token; the list only: scrollIntoView also scrolled the page, back to the Section's top
  const remove = useMutation({
    mutationFn: (id: number) => send(`/api/courses/${cid}/tutor/${id}`, undefined, "DELETE"),
    onSuccess: (_, id) => { if (id === conv) open(null); qc.invalidateQueries({ queryKey: ["tutor", cid] }); },
  });
  /** `keep`: the messages to ask after (an edited question drops the ones from it on); none kept starts a new conversation. */
  const ask = async (asked?: string, about?: { block_id: number; style: Style }, keep?: Msg[], how: How = {}, pics: string[] = []) => {
    const question = asked ?? qBox.current?.value.trim() ?? "";
    if (!question || busy) return;
    if (!about && asked === undefined) setQ("");
    const fresh = !!about || keep?.length === 0;
    const page = !about && notes ? await notes().catch(() => null) : null;
    const extra = about ? {} : { images: [...new Set([...images, ...pics, ...(page ? [page] : [])])].slice(-6), attached: attached.map((b) => b.id), items: Object.fromEntries(attached.flatMap((b) => b.item ? [[b.id, b.item.id]] : [])), sections: Object.keys(ctx).map(Number) };
    const labels = [...attached.map((b) => b.item?.label ?? (blockLabel(b).title || blockLabel(b).kind)), ...ctxLabels(chapters, ctx)];
    if (!about) { setImages([]); onAttached([]); setCtx(Object.fromEntries(Object.entries(ctx).filter(([, k]) => k))); }
    setBusy(true); setHistory(false); setTrouble("");
    if (fresh) setConv(null);
    setMsgs((m) => [...(about ? [] : keep ?? m), { role: "learner", text: question, images: extra.images, blocks: about ? [] : labels }, { role: "tutor", text: "" }]);
    const patch = (f: (m: Msg) => Msg) => setMsgs((all) => [...all.slice(0, -1), f(all[all.length - 1])]);
    stop.current = new AbortController();
    const answer = answerId();
    let ended = false;
    try {
      const res = await fetch(`/api/courses/${cid}/tutor`, { method: "POST", headers: { "content-type": "application/json" }, signal: stop.current.signal,
        body: JSON.stringify({ answer, question, section_id: sectionId ?? null, conversation_id: fresh ? null : conv, ...lab?.(), ...about, ...extra, ...(asked === undefined && !about && pick ? { mode: pick } : {}), ...how }) });
      await readEvents(res, (ev, d) => {
        if (ev === "token") patch((m) => ({ ...m, text: m.text + d.text }));
        if (ev === "activity") patch((m) => ({ ...m, activity: [...(m.activity ?? []), d] }));
        if (ev === "remembered") patch((m) => ({ ...m, remembered: d }));
        if (ev === "done") { ended = true; setConv(d.conversation_id); setMsgs((all) => [...all.slice(0, -2), { ...all.at(-2)!, id: d.question_id },
          { ...all.at(-1)!, id: d.message_id, citations: d.citations, proposal: d.proposal, activity: d.activity ?? all.at(-1)!.activity, mode: d.mode, anchor: d.anchor }]); }
        if (ev === "error") { ended = true; patch((m) => ({ ...m, text: d.message, error: true })); }
      }, stop.current.signal);
      if (!ended) throw new TypeError("the connection closed before the answer ended");
    } catch (e) {
      let err = e;
      if (!stop.current?.signal.aborted && !(e instanceof ApiError)) {  // a dropped connection: the server writes the answer on, so wait for it
        patch((m) => ({ ...m, text: DROPPED }));
        try { await open(await answerAfterDrop(cid, answer, stop.current!.signal)); return; } catch (e2) { err = e2; }
      }
      if (stop.current?.signal.aborted) { stopAnswer(cid, answer); setMsgs((all) => all.slice(0, -2)); setQ(question); }  // stopped: nothing was kept, the question goes back in the box
      else patch((m) => ({ ...m, text: String(err), error: true }));
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
        {label}<p className="min-w-0 flex-1 truncate text-sm">{!label && <span className="font-medium">Tutor</span>}
          {title && <span className="text-muted-foreground"> · {title}</span>}</p>
        {!lab && <>
          {conv !== null && !busy && <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" title="Copy this conversation into the Course chat and carry on there"
                  onClick={async () => { try { const r = await send<{ conversation_id: number }>(`/api/courses/${cid}/chat/from-tutor/${conv}`); location.assign(`/c/${cid}/chat?conv=${r.conversation_id}`); }
                    catch (e) { setTrouble(String((e as Error).message)); } }} aria-label="Continue in Course chat">
            <ExternalLink className="size-3.5 sm:hidden" aria-hidden /><span className="max-sm:hidden">Continue in Course chat</span></Button>}
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
              <div className="rounded-lg rounded-br-sm bg-primary/10 px-3 py-2 text-sm">
                {!!m.images?.length && <div className="mb-2 flex flex-wrap gap-1.5">{m.images.map((src, k) => <img key={k} src={src} alt={`Image ${k + 1}`} className="max-h-28 rounded border border-border" />)}</div>}
                {!!m.blocks?.length && <p className="mb-1 flex flex-wrap gap-1 text-xs text-muted-foreground">{m.blocks.map((t, k) => <span key={k} className="inline-flex items-center gap-1"><Paperclip className="size-3" />{t}</span>)}</p>}
                <AskedText text={m.text} />
              </div>
            </div>
          )) : (
            <div key={i} className={cn("min-w-0", m.error && "text-destructive")}>
              <ActivityLine steps={m.activity ?? []} live={busy && i === msgs.length - 1} onCite={onCite} />
              {m.text.replace(PROPOSAL, "").trim() ? <div onClick={(e) => {
                  const a = (e.target as HTMLElement).closest<HTMLAnchorElement>('a[href^="#block-"]');
                  if (a && onBlock) { e.preventDefault(); onBlock(Number(a.hash.slice(7))); } }}>
                  <Md className="tutor-answer">{linkBlocks(m.text.replace(PROPOSAL, ""), blocks)}</Md></div>
                : !m.proposal && <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
                    <span className="flex gap-1" aria-hidden>{[0, 1, 2].map((k) => <span key={k} className="size-1.5 animate-pulse rounded-full bg-muted-foreground" style={{ animationDelay: `${k * 150}ms` }} />)}</span>
                    {m.text.includes("```proposal") ? "Writing a Block…" : "Thinking…"}</p>}
              {!!m.citations?.length && (
                <p className="mt-2 flex flex-wrap gap-1.5">
                  {m.citations.map((c, k) => <button key={k} type="button" onClick={() => onCite(c)}
                    className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground hover:border-primary hover:text-primary">{c.source} p.{c.page}</button>)}
                </p>
              )}
              {m.mode === "step" && m.id && !busy && (
                <p className="mt-2 flex flex-wrap gap-1.5">
                  <Button size="sm" variant="outline" onClick={() => ask("More detail on that step.", undefined, undefined, { mode: "explain" })}>More detail</Button>
                  <Button size="sm" variant="ghost" title="The wider theory, marked as not from the course" onClick={() => ask("What is beyond the course here?", undefined, undefined, { mode: "beyond" })}>Beyond the course</Button>
                </p>)}
              {m.mode === "step" && <div className="mt-2"><InExamLink chapters={chapters} anchor={m.anchor} /></div>}
              {m.remembered && <RememberedLine key={m.remembered.id} fact={m.remembered} />}
              {m.proposal && m.id && <ProposalCard cid={cid} mid={m.id} p={m.proposal} sectionId={sectionId} previewing={preview?.mid === m.id} onPreview={onPreview}
                onFix={busy ? undefined : (errors) => ask("Your proposal failed the checks, so it could not be applied. The exact errors:\n"
                  + errors.map((e) => `- ${e}`).join("\n") + "\nFix exactly these and send the corrected proposal, with the same changes otherwise.")}
                onDone={(status, can_undo) => setMsgs((all) => all.map((x) => x === m ? { ...x, proposal: { ...m.proposal!, status, can_undo } } : x))} />}
            </div>
          ))}
          {trouble && <p className="text-xs text-destructive" role="alert">{trouble}</p>}
        </div>
      )}
      {(images.length > 0 || attached.length > 0 || Object.keys(ctx).length > 0) && (
        <ul className="flex flex-wrap gap-2 border-t border-border px-3 pt-3" aria-label="Attached to the next question">
          {images.map((src, i) => (
            <li key={i} className="relative">
              <img src={src} alt={`Image ${i + 1}`} className="size-14 rounded-md border border-border object-cover" />
              <button type="button" aria-label={`Remove image ${i + 1}`} onClick={() => setImages(images.filter((_, k) => k !== i))}
                      className="absolute -right-1.5 -top-1.5 rounded-full border border-border bg-card p-0.5 hover:bg-accent"><X className="size-3" /></button>
            </li>))}
          {attached.map((b) => (
            <li key={b.id} className="flex max-w-[14rem] items-center gap-1 rounded-md border border-border bg-muted/50 py-1 pl-2 pr-1 text-xs">
              <Paperclip className="size-3 shrink-0" /><span className="truncate">{b.item?.label ?? (blockLabel(b).title || blockLabel(b).kind)}</span>
              <button type="button" aria-label="Detach this Block" onClick={() => onAttached(attached.filter((x) => x.id !== b.id))}
                      className="rounded p-0.5 hover:bg-accent"><X className="size-3" /></button>
            </li>))}
          <ContextChips chapters={chapters} ctx={ctx} setCtx={setCtx} />
        </ul>)}
      <form className="flex flex-wrap items-end gap-2 border-t border-border p-3 [ul+&]:border-t-0" onSubmit={(e) => { e.preventDefault(); ask(); }}>
        {!lab && <label className="mb-1 cursor-pointer rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground" title="Add images (or paste them into the box)">
          <ImagePlus className="size-4" aria-hidden /><span className="sr-only">Add images</span>
          <input type="file" multiple accept="image/png,image/jpeg,image/webp" className="sr-only"
                 onChange={(e) => { addImages(e.target.files ?? []); e.target.value = ""; }} />
        </label>}
        {!lab && <WriteButton cid={cid} onImage={(src) => setImages((all) => [...all, src].slice(0, 6))} onText={(said) => setQ((t) => appended(t, said))} />}
        {!lab && chapters.length > 0 && <ContextPicker chapters={chapters} current={sectionId} ctx={ctx} setCtx={setCtx} />}
        <DictateButton cid={cid} onText={(said) => setQ((t) => appended(t, said))} />
        {!lab && <ModeSelect mode={pick} setMode={setPick} />}
        <Textarea ref={qBox} onChange={(e) => setHasQ(!!e.target.value.trim())} rows={2} placeholder={lab ? "Why does this raise a TypeError?" : "Ask about this Section…"} aria-label="Question"
                  onPaste={(e) => { const f = [...e.clipboardData.files]; if (!lab && f.length) { e.preventDefault(); addImages(f); } }}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } }} className="order-first max-h-[min(10rem,25dvh)] min-h-0 basis-full resize-none" />
        {busy ? <Button key="stop" type="button" size="icon" variant="outline" className="ml-auto" aria-label="Stop" title="Stop: the question goes back in the box"
                        onClick={() => stop.current?.abort()}><Square className="size-3.5 fill-current" /></Button>
          : <Button key="ask" type="submit" size="icon" className="ml-auto" disabled={!hasQ} aria-label="Ask"><Send className="size-4" /></Button>}
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
              {cram || c.exam_weight ? `${Math.round(c.exam_weight * 100)}% of exams` : `${c.sections.filter((s) => read.has(s.id)).length}/${c.sections.length}`}</span></p>
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
const INKS = ["#2563eb", "#dc2626", "#16a34a"];  // readable on both themes; black ink vanishes on the dark one
const TYPE_UP = "The image is my handwritten notes on this Section. Type them up as clean Markdown with $LaTeX$, keeping my wording and layout; "
  + "mark anything you can't read as [?]. Then list briefly anything in them that disagrees with the course, citing its pages.";
const RECALL = "The image is what I wrote from memory about this Section, without looking at it (blank-page recall). Compare it with the Section: "
  + "what I got right, what I got wrong (with the correction and its page), and the key points I left out, most important first. Be brief.";
const CIRCLED = "The image is the part of the attached Block I circled. Explain it.";
const INK_IN = "The image is what I wrote by hand over the attached Block, at the same size as the Block on screen. Propose a replacement for this Block "
  + "that works my additions and corrections in and keeps the rest. If something I wrote is wrong, say so and leave it out.";
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
  const [step, setStep] = useState<StepAsk | null>(null), [line, setLine] = useState<ReturnType<typeof selectedLine>>(null);
  useEffect(() => { if (!line) return; const off = () => setLine(null); addEventListener("scroll", off, { once: true, capture: true });
    return () => removeEventListener("scroll", off, { capture: true }); }, [line]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [panel, setPanel] = useState<"search" | "keys" | "contents" | null>(null);
  const [scale, setScale] = useState(() => { try { return Number(localStorage.getItem("cf-read-scale")) || 1; } catch { return 1; } });
  const resize = (by: number) => setScale((s) => {
    const next = SCALES[Math.max(0, Math.min(SCALES.length - 1, SCALES.indexOf(s) + by))] ?? 1;
    try { localStorage.setItem("cf-read-scale", String(next)); } catch { /* storage blocked */ }
    return next;
  });
  const [attached, setAttached] = useState<Block[]>([]);
  const attachBlock = (b: Block, item?: Block["item"]) => { showTutor(); setAttached((a) => [...a.filter((x) => x.id !== b.id), { ...b, item }].slice(-12)); };
  const explainBlock = (block_id: number, style: Style, label: string) => { showTutor(); setExplain((e) => ({ block_id, style, label, n: (e?.n ?? 0) + 1 })); };
  const mark = useMutation({ mutationFn: (section_id: number) => send(`/api/courses/${cid}/place`, { section_id }, "PUT"),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["place", cid] }); qc.invalidateQueries({ queryKey: ["progress", cid] }); } });
  const saveNote = (block_id: number) => (text: string) =>
    send(`/api/courses/${cid}/blocks/${block_id}/note`, { text }, "PUT").then(() => qc.invalidateQueries({ queryKey: ["notes", cid] }));
  const sections = chapters.flatMap((c) => c.sections.map((s) => ({ ...s, chapter: c })));
  const current = sections.find((s) => s.id === sid) ?? sections.find((s) => s.id === place?.section_id) ?? sections[0];
  useEffect(() => { if (current) mark.mutate(current.id); }, [current?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (target && current?.blocks.some((b) => b.id === target)) { scrollToBlock(target); setTarget(null); } }, [target, current?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const [navOpen, setNavOpen] = useState(() => { try { return localStorage.getItem("cf-nav") !== "closed"; } catch { return true; } });
  const flipNav = () => setNavOpen((o) => { try { localStorage.setItem("cf-nav", o ? "closed" : "open"); } catch { /* storage blocked */ } return !o; });
  const [notesOpen, setNotesOpen] = useState(() => { try { return localStorage.getItem("cf-notes") === "open"; } catch { return false; } });
  // one side panel, Notes | Tutor: both stay mounted once opened (the tutor sees the notes, a hidden tutor keeps its answer), `side` is the one in front
  const [side, setSide] = useState<"notes" | "tutor">("tutor");
  const front = tutor && (side === "tutor" || !notesOpen) ? "tutor" : notesOpen ? "notes" : null;
  const showNotes = (on = true) => { setNotesOpen(on); if (on) setSide("notes"); try { localStorage.setItem("cf-notes", on ? "open" : "closed"); } catch { /* storage blocked */ } };
  function showTutor() { setTutor(true); setSide("tutor"); }
  const closePanel = () => { showNotes(false); setTutor(false); setExplain(null); setPreview(null); };
  const panelTabs = !exported && (
    <Tabs value={front ?? "tutor"} onValueChange={(v) => v === "notes" ? showNotes() : showTutor()} className="shrink-0">
      <TabsList className="group-data-[orientation=horizontal]/tabs:h-8" aria-label="Side panel">
        <TabsTrigger value="notes" className="text-xs"><NotebookPen />Notes</TabsTrigger>
        <TabsTrigger value="tutor" className="text-xs"><MessageCircle />Tutor</TabsTrigger>
      </TabsList>
    </Tabs>);
  const [notesStatus, setNotesStatus] = useState("");
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const onSnapshot = useCallback((s: Snapshot | null) => setSnap(() => s), []);
  const [say, setSay] = useState<Say | null>(null);
  const asked = (text: string, images?: string[], how?: How) => { showTutor(); setSay((s) => ({ text, images, how, n: (s?.n ?? 0) + 1 })); };
  const [pen, setPen] = useState<Pen | null>(null);
  const [recall, setRecall] = useState(false);  // blank-page recall: the Section hidden while you write what you remember
  useEffect(() => setRecall(false), [current?.id]);
  const explainStep = (b: Block, text: string) => { const c = b.citations[0];
    showTutor(); setStep((s) => ({ text, anchor: c ? { source: c.source, page: c.page } : null, n: (s?.n ?? 0) + 1 })); };
  const inkKey = ["ink", cid, current?.id];
  const { data: ink = {} } = useQuery({ queryKey: inkKey, enabled: !!current && !exported,
    queryFn: () => get<Record<string, Stroke[]>>(`/api/courses/${cid}/sections/${current!.id}/ink`) });
  const inked = useRef<number[]>([]);  // the Blocks written on, latest last: Undo takes back their last stroke
  const setInk = (bid: number, strokes: Stroke[]) => {
    if (strokes.length > (ink[bid]?.length ?? 0)) inked.current.push(bid);
    qc.setQueryData(inkKey, { ...ink, [bid]: strokes });
    send(`/api/courses/${cid}/blocks/${bid}/ink`, { strokes }, "PUT").catch((e) => setNotesStatus(`Ink not saved: ${(e as Error).message}`));
  };
  const undoInk = () => { const bid = inked.current.pop(); if (bid !== undefined && ink[bid]?.length) setInk(bid, ink[bid].slice(0, -1)); };
  const read = new Set(place?.read ?? []);
  const noteOf = new Map(notes.map((n) => [n.block_id, n.text]));
  const i = current ? sections.indexOf(current) : -1;
  const [listening, setListening] = useState<{ block?: number } | null>(null);
  const go = (id: number, block?: number) => { setPanel(null); setSid(id); if (block) setTarget(block); else scrollTo({ top: 0 }); };
  const previous = i > 0 && sections[i - 1].chapter.id === current?.chapter.id ? sections[i - 1] : null;
  useShortcuts((key, e) => {
    if (key === "search" || key === "/") { e.preventDefault(); setPanel("search"); }
    else if (key === "?") setPanel("keys");
    else if ((key === "]" || key === "n") && i < sections.length - 1) go(sections[i + 1].id);
    else if ((key === "[" || key === "p") && i > 0) go(sections[i - 1].id);
    else if (key === "b" && front !== "notes") flipNav();
    else if (key === "t") { if (front === "tutor") closePanel(); else showTutor(); }
    else if (key === "w" && !exported) { if (front === "notes") closePanel(); else showNotes(); }
    else if (key === "+" || key === "=") resize(1);
    else if (key === "-") resize(-1);
  });
  if (!chapters.length) return <p className="px-6 py-10 text-muted-foreground">No Chapter is published yet. Publish Chapters from Review.</p>;
  const cram = course?.goal === "cram";
  return (
    <div className={cn("grid min-h-[calc(100dvh-var(--hh))]", front === "notes" ? "lg:grid-cols-[minmax(0,1fr)_50vw]"
           : front === "tutor" ? (navOpen ? "lg:grid-cols-[17rem_minmax(0,1fr)_var(--tutor-w)]" : "lg:grid-cols-[minmax(0,1fr)_var(--tutor-w)]")
           : navOpen ? "lg:grid-cols-[17rem_1fr]" : "lg:grid-cols-[1fr]")}
         style={{ "--tutor-w": `${tutorW}px` } as React.CSSProperties}>
      <ReadingBar />
      <nav className={cn("hidden border-r border-border px-3 py-6", front !== "notes" && navOpen && "lg:block")} aria-label="Chapters" id="chapters-nav">
        <div className="sticky top-18 max-h-[calc(100dvh-6rem)] overflow-y-auto">
          <div className="mb-3 flex items-center justify-between pl-2">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Chapters</p>
            <button type="button" className={tool} onClick={flipNav} aria-expanded aria-controls="chapters-nav" aria-label="Hide the Chapters (b)" title="Hide the Chapters (b)">
              <PanelLeftClose className="size-4" /></button>
          </div>
          <ChapterList chapters={chapters} current={current?.id} read={read} cram={cram} go={go}
                       outline={current && <Outline section={current} notes={noteOf} results={results} />} />
        </div>
      </nav>
      {current && (
        <article lang={course?.language === "fr" ? "fr" : course?.language === "en" ? "en" : undefined} className={cn("mx-auto w-full min-w-0 max-w-[44rem] px-5 py-8 sm:px-8", front === "notes" && "pb-[52dvh] lg:pb-8")}>
          <div className="flex items-center gap-1">
            {!navOpen && front !== "notes" && (
              <Button size="sm" variant="outline" className="-ml-1 mr-2 hidden h-8 shrink-0 gap-1.5 lg:inline-flex" onClick={flipNav}
                      aria-expanded={false} aria-controls="chapters-nav" title="Show the Chapters (b)"><PanelLeftOpen className="size-4" />Chapters</Button>)}
            <p className="mr-auto min-w-0 truncate text-sm text-muted-foreground">{current.chapter.title}</p>
            <button type="button" className={cn(tool, front !== "notes" && "lg:hidden")} onClick={() => setPanel("contents")} aria-label="Contents"><List className="size-4" /></button>
            {!exported && <button type="button" className={cn(tool, front === "notes" && "bg-accent text-foreground")} onClick={() => front === "notes" ? closePanel() : showNotes()}
                                  aria-pressed={front === "notes"} aria-label="Your notes beside the Section (w)" title="Your notes beside the Section (w)"><NotebookPen className="size-4" /></button>}
            {!exported && <button type="button" className={cn(tool, pen && "bg-accent text-foreground")} onClick={() => setPen(pen ? null : { tool: "pen", color: INKS[0] })}
                                  aria-pressed={!!pen} aria-label="Write on the Blocks with a pen" title="Write on the Blocks with a pen"><PenLine className="size-4" /></button>}
            {!exported && <button type="button" className={cn(tool, recall && "bg-accent text-foreground")} onClick={() => { setRecall(!recall); setPen(null); scrollTo({ top: 0 }); }}
                                  aria-pressed={recall} aria-label="Blank-page recall: hide the Section and write what you remember" title="Blank-page recall: hide the Section and write what you remember"><EyeOff className="size-4" /></button>}
            {!exported && <button type="button" className={tool} onClick={() => setListening({})} aria-label="Listen to this Section" title="Listen to this Section"><Headphones className="size-4" /></button>}
            <button type="button" className={tool} onClick={() => setPanel("search")} aria-label="Search the Course (/)" title="Search the Course (/)"><Search className="size-4" /></button>
            <button type="button" className={tool} onClick={() => resize(-1)} disabled={scale === SCALES[0]} aria-label="Smaller text" title="Smaller text (−)"><AArrowDown className="size-4" /></button>
            <button type="button" className={tool} onClick={() => resize(1)} disabled={scale === SCALES.at(-1)} aria-label="Larger text" title="Larger text (+)"><AArrowUp className="size-4" /></button>
            <button type="button" className={cn(tool, "hidden sm:grid")} onClick={() => setPanel("keys")} aria-label="Keyboard shortcuts (?)" title="Keyboard shortcuts (?)"><Keyboard className="size-4" /></button>
          </div>
          <h1 className="mt-1 font-display text-3xl font-semibold tracking-tight">{current.title}</h1>
          <p className="mt-2 flex items-center gap-1.5 text-sm text-muted-foreground"><Clock className="size-3.5" />About {sectionMinutes(current)} min, practice included</p>
          <ChapterMap chapter={current.chapter} current={current.id} read={read} go={go} />
          <InExam key={current.id} chapter={current.chapter} open={current.chapter.sections[0]?.id === current.id} />
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
          {line && !exported && (
            <Button size="sm" className="fixed z-30 shadow-md" style={{ left: Math.min(line.x, innerWidth - 180), top: Math.min(line.y + 6, innerHeight - 44) }}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => { const b = current.blocks.find((x) => x.id === line.block); if (b) explainStep(b, line.text);
                      setLine(null); window.getSelection()?.removeAllRanges(); }}>Explain this step</Button>)}
          <div className="prose-cf mt-8 space-y-10" style={{ "--read-scale": scale } as React.CSSProperties}
               onMouseUp={() => setTimeout(() => setLine(selectedLine()))} onKeyUp={() => setLine(selectedLine())}
               onTouchEnd={() => setTimeout(() => setLine(selectedLine()), 300)}>
            {recall ? (
              <section aria-label="Blank-page recall" className="font-sans">
                <p className="mb-2 text-sm text-muted-foreground">The Section is hidden. Write everything you remember of it: definitions, formulas, how the steps go. Then compare.</p>
                <InkPad className="[&_canvas]:h-[60dvh]" label="Compare with the Section"
                        onSave={async (b) => { asked(RECALL, [await dataUrl(b)]); setRecall(false); }} />
                <Button size="sm" variant="ghost" className="mt-2" onClick={() => setRecall(false)}>Show the Section</Button>
              </section>
            ) : preview?.sectionId === current.id ? <PreviewBlocks cid={cid} preview={preview} /> : current.blocks.map((b) => (
              <div key={b.id} className="relative">
                <ReaderBlock block={b} cid={cid} onCite={setCite} onExplain={explainBlock} onAttach={attachBlock} onListen={exported ? undefined : (block) => setListening({ block })} note={noteOf.get(b.id)} onNote={saveNote(b.id)} standing={results[b.id]} />
                {!exported && <BlockInk strokes={ink[b.id] ?? []} pen={pen} onChange={(st) => setInk(b.id, st)}
                                        onAsk={({ text, image }) => { if (text) explainStep(b, text); else if (image) { attachBlock(b); asked(CIRCLED, [image]); } }} />}
                {!pen && !!ink[b.id]?.length && (
                  <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-sans text-xs text-muted-foreground">
                    <span className="flex items-center gap-1"><PenLine className="size-3" />Your ink</span>
                    <button type="button" className="flex items-center gap-1 text-primary hover:underline" title="The tutor proposes this Block rewritten with what you wrote; you preview and apply it"
                            onClick={(e) => { const r = e.currentTarget.closest(".relative")!.getBoundingClientRect();
                              attachBlock(b); asked(INK_IN, [inkImage(ink[b.id], Math.round(r.width), Math.round(r.height))]); }}>
                      <Sparkles className="size-3" />Work it into the Block</button>
                    <button type="button" className="hover:text-foreground" onClick={() => setInk(b.id, [])}>Clear</button>
                  </p>)}
              </div>))}
          </div>
          <ConfidenceCheck cid={cid} section={current} onAsk={() => showTutor()} />
          <div className="mt-8 flex justify-between gap-4 border-t border-border pt-4 text-sm">
            {i > 0 ? <button type="button" onClick={() => go(sections[i - 1].id)} className="text-left hover:text-primary">← {sections[i - 1].title}</button> : <span />}
            {i < sections.length - 1 && <button type="button" onClick={() => go(sections[i + 1].id)} className="text-right hover:text-primary">{sections[i + 1].title} →</button>}
          </div>
        </article>
      )}
      {pen && (
        <div role="toolbar" aria-label="Pen" className="fixed bottom-5 left-1/2 z-30 flex -translate-x-1/2 items-center gap-1 rounded-full border border-border bg-card p-1.5 shadow-md">
          {INKS.map((c) => (
            <button key={c} type="button" aria-label={`Pen, ${c}`} aria-pressed={pen.tool === "pen" && pen.color === c} onClick={() => setPen({ tool: "pen", color: c })}
                    className={cn("grid size-9 place-items-center rounded-full", pen.tool === "pen" && pen.color === c && "bg-accent")}>
              <span className="size-4 rounded-full" style={{ background: c }} /></button>))}
          <button type="button" aria-label="Highlighter" aria-pressed={pen.tool === "hl"} onClick={() => setPen({ ...pen, tool: "hl" })}
                  className={cn("grid size-9 place-items-center rounded-full", pen.tool === "hl" && "bg-accent")}><Highlighter className="size-4" /></button>
          <button type="button" aria-label="Eraser (or the pen's eraser button)" aria-pressed={pen.tool === "erase"} onClick={() => setPen({ ...pen, tool: "erase" })}
                  className={cn("grid size-9 place-items-center rounded-full", pen.tool === "erase" && "bg-accent")}><Eraser className="size-4" /></button>
          <button type="button" aria-label="Circle to ask: go round text, a formula or a figure to ask the tutor about it" title="Circle to ask" aria-pressed={pen.tool === "ask"}
                  onClick={() => setPen({ ...pen, tool: "ask" })} className={cn("grid size-9 place-items-center rounded-full", pen.tool === "ask" && "bg-accent")}><Lasso className="size-4" /></button>
          <button type="button" aria-label="Undo the last stroke" onClick={undoInk} className="grid size-9 place-items-center rounded-full hover:bg-accent"><Undo2 className="size-4" /></button>
          <Button size="sm" variant="ghost" className="rounded-full" onClick={() => setPen(null)}>Done</Button>
        </div>
      )}
      {front ? (
        <div className={cn("fixed inset-x-0 bottom-0 z-20 lg:sticky lg:top-(--hh) lg:h-[calc(100dvh-var(--hh))]", front === "notes" ? "h-[50dvh]" : "top-(--hh)")}>
          {notesOpen && current && (
            <section aria-label="Your notes" inert={front !== "notes"} className={cn("flex h-full flex-col border-t border-border bg-card lg:border-l lg:border-t-0", front !== "notes" && HIDDEN)}>
              <div className="flex items-center gap-1 border-b border-border py-1.5 pl-4 pr-2 text-sm">
                {panelTabs}<p className="min-w-0 truncate text-muted-foreground">{current.title}</p>
                <span className="ml-auto shrink-0 text-xs text-muted-foreground" role="status">{notesStatus}</span>
                <Button size="sm" variant="ghost" className="h-7 shrink-0 px-2 text-xs" disabled={!snap} title="The tutor types up your handwriting and checks it against the course"
                        onClick={async () => { const page = await snap?.(); if (page) asked(TYPE_UP, [page]); else setNotesStatus("Nothing written yet"); }}>
                  <Sparkles className="size-3.5" />Type up</Button>
                <Button size="icon" variant="ghost" className="size-7 shrink-0" onClick={closePanel} aria-label="Close notes and tutor"><X className="size-4" /></Button>
              </div>
              <div className="min-h-0 flex-1">
                <Suspense fallback={<p className="p-4 text-sm text-muted-foreground">Opening your notes…</p>}>
                  <Notebook key={current.id} cid={cid} sectionId={current.id} onSnapshot={onSnapshot} onStatus={setNotesStatus} />
                </Suspense>
              </div>
            </section>
          )}
          {tutor && <>
          {front === "tutor" && <div role="separator" aria-orientation="vertical" aria-label="Resize the tutor" aria-valuenow={tutorW} aria-valuemin={320} tabIndex={0}
               title="Drag to resize the tutor (or use the arrow keys)"
               className="absolute inset-y-0 -left-1 z-10 hidden w-2 cursor-col-resize touch-none transition-colors hover:bg-primary/40 focus-visible:bg-primary/60 focus-visible:outline-none lg:block"
               onPointerDown={(e) => { e.preventDefault(); dragging.current = true; try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* no capture: the drag still follows while over the handle */ } }}
               onPointerMove={(e) => { if (dragging.current) sizeTutor(innerWidth - e.clientX); }}
               onPointerUp={() => { dragging.current = false; }} onPointerCancel={() => { dragging.current = false; }}
               onKeyDown={(e) => { if (e.key === "ArrowLeft") sizeTutor(tutorW + 32); else if (e.key === "ArrowRight") sizeTutor(tutorW - 32); }} />}
          <Tutor className={cn(front !== "tutor" && HIDDEN)} label={panelTabs || undefined} notes={notesOpen ? snap : null} say={say} cid={cid} sectionId={current?.id} explain={explain} step={step} onCite={setCite} preview={preview} onPreview={setPreview}
                 attached={attached} onAttached={setAttached} chapters={chapters}
                 blocks={new Set(sections.flatMap((s) => s.blocks.map((b) => b.id)))}
                 onBlock={(id) => { const s = sections.find((x) => x.blocks.some((b) => b.id === id)); if (!s) return;
                   setPreview(null); if (innerWidth < 1024) setTutor(false); go(s.id, id); }}
                 onClose={closePanel} />
          </>}
        </div>
      ) : !pen && (
        <div className="fixed bottom-5 right-5 z-20 flex gap-2">
          {!exported && <Button variant="outline" className="shadow-md" onClick={() => showNotes()} title="Your notes beside the Section (w)"><NotebookPen className="size-4" />Notes</Button>}
          <Button className="shadow-md" onClick={showTutor} title="Ask the tutor (t)"><MessageCircle className="size-4" />Ask the tutor</Button>
        </div>
      )}
      {listening && current && <ListenBar key={`${current.id}-${listening.block}`} cid={cid} section={current} block={listening.block} next={i < sections.length - 1 ? sections[i + 1] : null}
                                          onNext={() => { setListening({}); go(sections[i + 1].id); }} onClose={() => setListening(null)} />}
      <SearchPalette cid={cid} open={panel === "search"} onClose={() => setPanel(null)} chapters={chapters} notes={notes} go={go} onCite={setCite} />
      <ShortcutsDialog open={panel === "keys"} onClose={() => setPanel(null)} />
      <Dialog open={panel === "contents"} onOpenChange={(o) => !o && setPanel(null)}>
        <DialogContent className="max-h-[85dvh] overflow-y-auto">
          <DialogHeader><DialogTitle>Contents</DialogTitle><DialogDescription>A green dot marks a Section you have opened.</DialogDescription></DialogHeader>
          <ChapterList chapters={chapters} current={current?.id} read={read} cram={cram} go={go} />
        </DialogContent>
      </Dialog>
      <PageViewer cid={cid} cite={cite} onClose={() => setCite(null)}
                  onAsk={exported ? undefined : (img, c) => { setCite(null); asked(`The image is a part of ${c.source}, page ${c.page} that I marked. Explain this step.`, [img], { mode: "step", anchor: { source: c.source, page: c.page } }); }} />
    </div>
  );
}
