import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Popover } from "radix-ui";
import { FileDown, FileText, GraduationCap, ImagePlus, Paperclip, Pencil, Plus, RefreshCw, Send, Square, SquareTerminal, Trash2, Undo2, X } from "lucide-react";
import { ActivityLine, BlockPlaceholder, type Activity } from "@/components/activity";
import { RememberedLine, type Remembered } from "@/components/remembered";
import { BlockBody, PageViewer } from "@/components/blocks";
import { ContextChips, ContextPicker, ctxLabels, type Ctx } from "@/components/context-picker";
import { Md } from "@/components/md";
import { WriteButton } from "@/components/ink";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { appended, DictateButton } from "@/components/dictation";
import { ApiError, DROPPED, answerAfterDrop, answerId, get, readEvents, send, stopAnswer, type Block, type Chapter, type Citation } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AskedText } from "@/components/asked";
import { blockLabel, InExamLink, ModeSelect, type Mode } from "./reader-tools";
import { useCid } from "./run";

type Saved = { block_id: number; section_id: number; section: string };
type Part =
  | { type: "md"; text: string }
  | { type: "block"; kind: string; block: { component: string; data: unknown; citations: Citation[] }; saved: Saved | null }
  | { type: "summary"; right: string[]; review: { concept: string; section_id: number | null; section: string | null }[] };
type Msg = { id?: number; role: "learner" | "tutor"; text: string; images?: string[]; labels?: string[]; parts?: Part[] | null; citations?: Citation[];
  activity?: Activity[]; remembered?: Remembered | null; error?: boolean; live?: Record<number, { status: "writing" | "checking"; kind: string | null }>;
  mode?: Mode | null; anchor?: Citation | null };
type Conv = { id: number; question: string; last_at: string };
type Drill = { chapters: number[]; minutes: number; started: string; stopped: boolean };
type Suggest = { section_id: number | null; after_block_id: number | null; sections: { id: number; title: string; chapter: string; blocks: { id: number; component: string }[] }[] };

/** A Block of an answer as the Section renderers take it: its practice is recorded against Concepts until it is saved into a Section. */
const asBlock = (m: Msg, i: number, p: Extract<Part, { type: "block" }>): Block => ({
  id: p.saved?.block_id ?? -(Number(m.id ?? 0) * 100 + i + 1), position: 0, component: p.block.component, data: p.block.data, citations: p.block.citations ?? [],
  origin: "model_added", status: "ok", flags: [], from_chat: true, ...(p.saved || !m.id ? {} : { chat: { mid: m.id, part: i } }),
});

const labelOf = (b: Block) => blockLabel(b).title || blockLabel(b).kind;

type Doc = { name: string; pages: number };

/** Picks whole source documents (every page) for the tutor to answer from; they stay until removed. */
function DocPicker({ docs, picked, setPicked }: { docs: Doc[]; picked: string[]; setPicked: (d: string[]) => void }) {
  const pages = docs.filter((d) => picked.includes(d.name)).reduce((n, d) => n + d.pages, 0);
  return (
    <Popover.Root>
      <Popover.Trigger className="relative mb-1 rounded-md p-1.5 text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                       aria-label={picked.length ? `Whole documents: ${picked.length} selected` : "Add whole documents for the tutor to read"} title="Add whole documents (every page) for the tutor to read">
        <FileText className="size-4" aria-hidden />
        {picked.length > 0 && <span className="tabular absolute -right-0.5 -top-0.5 grid min-w-4 place-items-center rounded-full bg-primary px-1 text-[10px] leading-4 text-primary-foreground">{picked.length}</span>}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="top" align="start" sideOffset={8} collisionPadding={12} aria-label="Whole documents"
                         className="z-50 flex max-h-[min(28rem,var(--radix-popover-content-available-height))] w-[min(24rem,calc(100vw-1.5rem))] flex-col rounded-md border border-border bg-card text-sm shadow-md outline-none">
          <ul className="min-h-0 flex-1 overflow-y-auto py-1">
            {docs.map((d) => (
              <li key={d.name}><label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 hover:bg-accent/60">
                <input type="checkbox" checked={picked.includes(d.name)} className="size-4 shrink-0 cursor-pointer accent-primary"
                       onChange={() => setPicked(picked.includes(d.name) ? picked.filter((x) => x !== d.name) : [...picked, d.name])} />
                <span className="min-w-0 flex-1 break-words">{d.name}</span>
                <span className="tabular shrink-0 text-xs text-muted-foreground">{d.pages} p.</span></label></li>))}
          </ul>
          <div className="flex items-center gap-2 border-t border-border p-2">
            <p className="tabular flex-1 pl-1 text-xs text-muted-foreground" aria-live="polite">{picked.length ? `${picked.length} selected, ${pages} pages (up to 300 in all)` : "None selected"}</p>
            {picked.length > 0 && <Button size="sm" variant="ghost" onClick={() => setPicked([])}>Clear</Button>}
            <Popover.Close asChild><Button size="sm">Done</Button></Popover.Close>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

/** Picks Blocks of any Section to ask about, as the reader's attach button does for the Section tutor. */
function AttachPicker({ chapters, attached, onAttach }: { chapters: Chapter[]; attached: Block[]; onAttach: (b: Block) => void }) {
  const sections = chapters.flatMap((c) => c.sections.map((s) => ({ ...s, chapter: c.title })));
  const [sid, setSid] = useState<number | null>(null);
  const section = sections.find((s) => s.id === (sid ?? sections[0]?.id));
  return (
    <Popover.Root>
      <Popover.Trigger asChild><button type="button" title="Attach Blocks to ask about" className="mb-1 rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground">
        <Paperclip className="size-4" aria-hidden /><span className="sr-only">Attach Blocks</span></button></Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="top" align="start" sideOffset={8} collisionPadding={12} aria-label="Attach Blocks"
                         className="z-50 w-[min(24rem,calc(100vw-1.5rem))] space-y-2 rounded-md border border-border bg-card p-3 text-sm shadow-md outline-none">
          <select className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm" aria-label="Section" value={section?.id ?? ""}
                  onChange={(e) => setSid(Number(e.target.value))}>
            {sections.map((s) => <option key={s.id} value={s.id}>{s.chapter} · {s.title}</option>)}</select>
          <ul className="max-h-64 space-y-0.5 overflow-y-auto">
            {section?.blocks.map((b) => { const on = attached.some((x) => x.id === b.id); return (
              <li key={b.id}><button type="button" disabled={on} onClick={() => onAttach(b)}
                className="flex w-full items-baseline gap-2 rounded px-2 py-1.5 text-left hover:bg-accent disabled:opacity-50">
                <span className="shrink-0 text-xs text-muted-foreground">{blockLabel(b).kind}</span>
                <span className="min-w-0 flex-1 truncate">{blockLabel(b).title}</span>{on && <span className="text-xs">attached</span>}</button></li>); })}
            {!section?.blocks.length && <li className="px-2 py-1.5 text-muted-foreground">No Blocks in this Section.</li>}
          </ul>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function SaveButton({ cid, mid, part, onSaved, named }: { cid: number; mid: number; part: number; onSaved: (s: Saved) => void; named: (id: number, component: string) => string }) {
  const [open, setOpen] = useState(false);
  const { data: sug } = useQuery({ queryKey: ["chat-suggest", cid, mid, part], enabled: open, staleTime: 0,
    queryFn: () => get<Suggest>(`/api/courses/${cid}/chat/messages/${mid}/parts/${part}/suggest`) });
  const [sec, setSec] = useState<number | null>(null), [after, setAfter] = useState<string | null>(null), [err, setErr] = useState("");
  const secId = sec ?? sug?.section_id ?? sug?.sections[0]?.id ?? null;
  const target = sug?.sections.find((s) => s.id === secId);
  const last = target?.blocks.at(-1)?.id ?? null;
  const place = after ?? String(sec === null && sug?.after_block_id != null ? sug.after_block_id : last ?? "");
  const save = useMutation({
    mutationFn: () => send<{ saved: Saved }>(`/api/courses/${cid}/chat/messages/${mid}/parts/${part}/save`, { section_id: secId, after_block_id: place === "" ? null : Number(place) }),
    onSuccess: (r) => { setOpen(false); onSaved(r.saved); },
    onError: (e) => setErr(String((e as Error).message)),
  });
  const sel = "w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm";
  return (
    <Popover.Root open={open} onOpenChange={(o) => { setOpen(o); if (!o) { setSec(null); setAfter(null); setErr(""); } }}>
      <Popover.Trigger asChild><Button size="sm" variant="outline"><FileDown className="size-3.5" />Save to Section</Button></Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="top" align="start" sideOffset={8} collisionPadding={12} aria-label="Save to Section"
                         className="z-50 w-[min(22rem,calc(100vw-1.5rem))] space-y-3 rounded-md border border-border bg-card p-3 text-sm shadow-md outline-none">
          {!sug ? <p className="text-muted-foreground">Finding the Section…</p> : <>
            <label className="block space-y-1"><span className="text-xs text-muted-foreground">Section</span>
              <select className={sel} value={secId ?? ""} onChange={(e) => { setSec(Number(e.target.value)); setAfter(""); }}>
                {sug.sections.map((s) => <option key={s.id} value={s.id}>{s.chapter} · {s.title}</option>)}</select></label>
            <label className="block space-y-1"><span className="text-xs text-muted-foreground">Place</span>
              <select className={sel} value={place} onChange={(e) => setAfter(e.target.value)}>
                <option value="">At the start</option>
                {target?.blocks.map((b, i) => <option key={b.id} value={b.id}>After {i + 1}. {named(b.id, b.component)}{b.id === last ? " (the end)" : ""}</option>)}</select></label>
            {err && <p className="text-xs text-destructive" role="alert">{err}</p>}
            <div className="flex justify-end"><Button size="sm" disabled={secId === null || save.isPending} onClick={() => { setErr(""); save.mutate(); }}>Save</Button></div>
          </>}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

type BlockPart = Extract<Part, { type: "block" }>;

/** Rewrites one Block of an answer, optionally following the learner's instructions. */
function RegenButton({ cid, mid, part, onDone }: { cid: number; mid: number; part: number; onDone: (p: BlockPart) => void }) {
  const [open, setOpen] = useState(false), [note, setNote] = useState(""), [err, setErr] = useState("");
  const redo = useMutation({
    mutationFn: () => send<BlockPart>(`/api/courses/${cid}/chat/messages/${mid}/parts/${part}/regenerate`, { note }),
    onSuccess: (p) => { setOpen(false); setNote(""); onDone(p); },
    onError: (e) => setErr(String((e as Error).message)),
  });
  return (
    <Popover.Root open={open} onOpenChange={(o) => { if (!redo.isPending) { setOpen(o); setErr(""); } }}>
      <Popover.Trigger asChild><Button size="sm" variant="outline"><RefreshCw className={cn("size-3.5", redo.isPending && "animate-spin")} />Regenerate</Button></Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="top" align="start" sideOffset={8} collisionPadding={12} aria-label="Regenerate this Block"
                         className="z-50 w-[min(22rem,calc(100vw-1.5rem))] space-y-3 rounded-md border border-border bg-card p-3 text-sm shadow-md outline-none">
          <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); setErr(""); redo.mutate(); }}>
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} autoFocus disabled={redo.isPending}
                      placeholder="Optional: what should change? e.g. harder questions, a worked example in 2D" aria-label="Instructions for regenerating" />
            {err && <p className="text-xs text-destructive" role="alert">{err}</p>}
            <div className="flex justify-end"><Button type="submit" size="sm" disabled={redo.isPending}>{redo.isPending ? "Regenerating…" : "Regenerate"}</Button></div>
          </form>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

type Picked = { mid: number; part: number; text: string; x: number; y: number };
type MdPart = Extract<Part, { type: "md" }>;

/** The text the learner selected inside one text part of an answer, with where to show the Rewrite bar. */
function picked(): Picked | null {
  const s = window.getSelection();
  if (!s || s.isCollapsed || !s.rangeCount) return null;
  const text = s.toString().trim();
  const el = (n: Node | null) => (n instanceof Element ? n : n?.parentElement)?.closest<HTMLElement>("[data-md-part]");
  const a = el(s.anchorNode), b = el(s.focusNode);
  if (!text || !a || a !== b) return null;  // one part at a time
  const r = s.getRangeAt(0).getBoundingClientRect();
  return { mid: Number(a.dataset.mid), part: Number(a.dataset.part), text, x: r.left, y: r.bottom };
}

/** Asks how to rewrite the selected passage; the rewrite itself runs in the conversation, shown on the passage's text. */
function RewriteBar({ at, onGo, onClose }: { at: Picked; onGo: (note: string) => void; onClose: () => void }) {
  const [asking, setAsking] = useState(false), [note, setNote] = useState("");
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", esc); return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  return (
    <div role="dialog" aria-label="Rewrite the selected text" onMouseUp={(e) => e.stopPropagation()}
         style={{ left: Math.max(8, Math.min(at.x, window.innerWidth - 360)), top: Math.min(at.y + 6, window.innerHeight - (asking ? 200 : 48)) }}
         className="fixed z-50 rounded-md border border-border bg-card p-1.5 text-sm shadow-md">
      {!asking ? (
        <Button size="sm" variant="ghost" onMouseDown={(e) => e.preventDefault()} onClick={() => setAsking(true)}><RefreshCw className="size-3.5" />Rewrite</Button>
      ) : (
        <form className="w-[min(22rem,calc(100vw-1.5rem))] space-y-2 p-1.5" onSubmit={(e) => { e.preventDefault(); onGo(note); }}>
          <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} autoFocus
                    placeholder="Optional: how? e.g. simpler, with an example, step by step" aria-label="Instructions for rewriting" />
          <div className="flex justify-end gap-2">
            <Button type="button" size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" size="sm">Rewrite</Button></div>
        </form>)}
    </div>
  );
}

export function Chat() {
  const cid = useCid(), qc = useQueryClient();
  const [conv, setConv] = useState<number | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [drill, setDrill] = useState<Drill | null>(null);
  // the question box keeps its own text (typing must not re-render the conversation); state only knows if it is empty
  const qBox = useRef<HTMLTextAreaElement>(null), [hasQ, setHasQ] = useState(false);
  const setQ = (v: string | ((t: string) => string)) => {
    const el = qBox.current; if (!el) return;
    el.value = typeof v === "function" ? v(el.value) : v; setHasQ(!!el.value.trim());
  };
  const [busy, setBusy] = useState(false), [trouble, setTrouble] = useState("");
  const [ctx, setCtx] = useState<Ctx>({}), [images, setImages] = useState<string[]>([]), [attached, setAttached] = useState<Block[]>([]);
  const [docs, setDocs] = useState<string[]>([]), [shell, setShell] = useState(false), [mode, setMode] = useState<Mode | "">("");
  const [editing, setEditing] = useState<{ at: number; text: string } | null>(null);
  const [cite, setCite] = useState<Citation | null>(null);
  const [list, setList] = useState(false);
  const [quiz, setQuiz] = useState<{ chapters: number[]; minutes: number } | null>(null);
  const [toast, setToast] = useState<{ mid: number; part: number; saved: Saved } | null>(null);
  const stop = useRef<AbortController | null>(null), box = useRef<HTMLDivElement>(null);
  const { data: chapters = [] } = useQuery({ queryKey: ["reader", cid], queryFn: () => get<Chapter[]>(`/api/courses/${cid}/reader`) });
  const { data: sources = [] } = useQuery({ queryKey: ["map", cid], queryFn: () => get<Doc[]>(`/api/courses/${cid}/map`) });
  const { data: convs = [], error: listError } = useQuery({ queryKey: ["chat", cid], queryFn: () => get<Conv[]>(`/api/courses/${cid}/chat`) });
  const hidden = String((listError as Error | null)?.message ?? "").includes("hidden during an exam");

  const open = async (id: number | null) => {
    setConv(id); setList(false); setEditing(null); setTrouble("");
    if (id === null) { setMsgs([]); setDrill(null); return; }
    try {
      const r = await get<{ drill: Drill | null; messages: Msg[] }>(`/api/courses/${cid}/chat/${id}`);
      setMsgs(r.messages.map((m) => ({ ...m, parts: m.parts ?? undefined }))); setDrill(r.drill);
    } catch (e) { setTrouble(String((e as Error).message)); }
  };
  useEffect(() => { const c = Number(new URLSearchParams(location.search).get("conv")); if (c) open(c); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { box.current?.scrollTo({ top: box.current.scrollHeight }); }, [msgs.length]);  // a new message, not each streamed token: reading above stays put
  useEffect(() => { if (!toast) return; const t = setTimeout(() => setToast(null), 12000); return () => clearTimeout(t); }, [toast]);
  const remove = useMutation({
    mutationFn: (id: number) => send(`/api/courses/${cid}/chat/${id}`, undefined, "DELETE"),
    onSuccess: (_, id) => { if (id === conv) open(null); qc.invalidateQueries({ queryKey: ["chat", cid] }); },
  });

  const addImages = (files: Iterable<File>) => {
    for (const f of files) {
      if (!/^image\/(png|jpeg|webp)$/.test(f.type)) { setTrouble("Images only: PNG, JPEG or WebP."); continue; }
      if (f.size > 8_000_000) { setTrouble(`${f.name || "That image"} is over 8 MB.`); continue; }
      const r = new FileReader();
      r.onload = () => setImages((all) => [...all, String(r.result)].slice(0, 6));
      r.readAsDataURL(f);
    }
  };

  /** `keep`: the messages to ask after (an edited question drops the ones from it on). */
  const ask = async (asked?: string, o: { keep?: Msg[]; drill?: { chapters: number[]; minutes: number }; stopDrill?: boolean; mode?: Mode } = {}) => {
    const question = asked ?? qBox.current?.value.trim() ?? "";
    if (!question || busy) return;
    const fresh = o.keep?.length === 0 || !!o.drill, history = o.keep ?? msgs;
    if (asked === undefined) setQ("");
    const labels = [...attached.map(labelOf), ...ctxLabels(chapters, ctx), ...docs.map((d) => `Document: ${d}`), ...(shell ? ["Course files"] : [])];
    const sent = { images, attached: attached.map((b) => b.id), sections: Object.keys(ctx).map(Number), sources: docs, shell };
    setImages([]); setAttached([]); setCtx(Object.fromEntries(Object.entries(ctx).filter(([, k]) => k)));
    setBusy(true); setList(false); setTrouble(""); setQuiz(null);
    if (fresh) setConv(null);
    setMsgs([...(fresh ? [] : history), { role: "learner", text: question, images: sent.images, labels }, { role: "tutor", text: "", activity: [], live: {} }]);
    const patch = (f: (m: Msg) => Msg) => setMsgs((all) => [...all.slice(0, -1), f(all[all.length - 1])]);
    stop.current = new AbortController();
    const answer = answerId();
    let ended = false;
    try {
      const res = await fetch(`/api/courses/${cid}/chat`, { method: "POST", headers: { "content-type": "application/json" }, signal: stop.current.signal,
        body: JSON.stringify({ answer, question, conversation_id: fresh ? null : conv, ...sent, drill: o.drill, stop_drill: o.stopDrill ?? false, mode: o.mode ?? (mode || null) }) });
      await readEvents(res, (ev, d) => {
        if (ev === "token") patch((m) => ({ ...m, text: m.text + d.text }));
        if (ev === "activity") patch((m) => ({ ...m, activity: [...(m.activity ?? []), d] }));
        if (ev === "remembered") patch((m) => ({ ...m, remembered: d }));
        if (ev === "block") patch((m) => ({ ...m, live: { ...m.live, [d.index]: { status: d.status, kind: d.kind } } }));
        if (ev === "done") { ended = true;
          setConv(d.conversation_id);
          setMsgs((all) => [...all.slice(0, -2), { ...all.at(-2)!, id: d.question_id },
            { ...all.at(-1)!, id: d.message_id, citations: d.citations, parts: d.parts, activity: d.activity, remembered: all.at(-1)!.remembered, live: undefined, mode: d.mode, anchor: d.anchor }]);
          open(d.conversation_id);
        }
        if (ev === "error") { ended = true; patch((m) => ({ ...m, text: d.message, error: true, live: undefined })); }
      }, stop.current.signal);
      if (!ended) throw new TypeError("the connection closed before the answer ended");
    } catch (e) {
      let err = e;
      if (!stop.current?.signal.aborted && !(e instanceof ApiError)) {  // a dropped connection: the server writes the answer on, so wait for it
        patch((m) => ({ ...m, text: DROPPED }));
        try { await open(await answerAfterDrop(cid, answer, stop.current!.signal)); return; } catch (e2) { err = e2; }
      }
      if (stop.current?.signal.aborted) { stopAnswer(cid, answer); setMsgs((all) => all.slice(0, -2)); setQ(question); }
      else patch((m) => ({ ...m, text: String(err), error: true, live: undefined }));
    } finally { stop.current = null; setBusy(false); qc.invalidateQueries({ queryKey: ["chat", cid] }); }
  };
  const takeBack = async (i: number, again?: string) => {
    const m = msgs[i];
    try { if (m.id) await send(`/api/courses/${cid}/chat/messages/${m.id}`, undefined, "DELETE"); }
    catch (e) { setTrouble(String((e as Error).message)); return; }
    setEditing(null);
    const kept = msgs.slice(0, i);
    if (again) ask(again, { keep: kept });
    else { setMsgs(kept); setQ(m.text); if (!kept.length) setConv(null); qc.invalidateQueries({ queryKey: ["chat", cid] }); }
  };
  const retry = () => { const i = msgs.length - 2; if (i >= 0) takeBack(i, msgs[i].text); };
  const [pick, setPick] = useState<Picked | null>(null);
  const [rewriting, setRewriting] = useState<string[]>([]);  // "mid-part" of the text parts being rewritten
  const rewrite = async (at: Picked, note: string) => {
    const key = `${at.mid}-${at.part}`;
    setPick(null); window.getSelection()?.removeAllRanges(); setRewriting((r) => [...r, key]);
    try { setPart(at.mid, at.part, await send<MdPart>(`/api/courses/${cid}/chat/messages/${at.mid}/parts/${at.part}/rewrite`, { selection: at.text, note })); }
    catch (e) { setTrouble(`Couldn't rewrite it: ${(e as Error).message}`); }
    finally { setRewriting((r) => r.filter((x) => x !== key)); }
  };
  const setPart = (mid: number, part: number, np: Part) =>
    setMsgs((all) => all.map((m) => m.id === mid && m.parts ? { ...m, parts: m.parts.map((p, i) => i === part ? np : p) } : m));
  const setSaved = (mid: number, part: number, saved: Saved | null) =>
    setMsgs((all) => all.map((m) => m.id === mid && m.parts ? { ...m, parts: m.parts.map((p, i) => i === part && p.type === "block" ? { ...p, saved } : p) } : m));
  const undo = async () => {
    if (!toast) return;
    try { await send(`/api/courses/${cid}/chat/messages/${toast.mid}/parts/${toast.part}/undo`); setSaved(toast.mid, toast.part, null); qc.invalidateQueries({ queryKey: ["reader", cid] }); setToast(null); }
    catch (e) { setTrouble(String((e as Error).message)); setToast(null); }
  };

  const byId = new Map(chapters.flatMap((c) => c.sections.flatMap((s) => s.blocks)).map((b) => [b.id, b]));
  const named = (id: number, component: string) => { const b = byId.get(id); return b ? labelOf(b) : component.replaceAll("_", " "); };
  const drilling = !!drill && !drill.stopped;
  const title = convs.find((c) => c.id === conv)?.question;
  if (hidden) return <p className="mx-auto max-w-xl px-4 py-16 text-center text-muted-foreground">The Course chat is hidden while an exam is running.</p>;

  const answer = (m: Msg, i: number) => (
    <div key={i} className={cn("min-w-0", m.error && "text-destructive")}>
      <ActivityLine steps={m.activity ?? []} live={busy && i === msgs.length - 1} onCite={setCite} />
      {m.parts ? m.parts.map((p, k) => p.type === "md" ? (
        rewriting.includes(`${m.id}-${k}`) ? (
          <div key={k} aria-busy="true">
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status"><RefreshCw className="size-3.5 animate-spin" />Rewriting the selected text…</p>
            <Md className="tutor-answer pointer-events-none animate-pulse opacity-60">{p.text}</Md></div>)
        : <div key={k} {...(m.id && !busy ? { "data-md-part": "", "data-mid": m.id, "data-part": k } : {})}><Md className="tutor-answer">{p.text}</Md></div>)
        : p.type === "block" ? (
          <div key={k} className="my-4 rounded-lg border border-border p-4">
            <BlockBody key={JSON.stringify(p.block.data)} block={asBlock(m, k, p)} cid={cid} />
            <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3 text-xs text-muted-foreground">
              <span>Model-added · from the chat</span>
              {p.saved ? <a className="underline" href={`/c/${cid}/read?section=${p.saved.section_id}`}>Saved in {p.saved.section}</a>
                : m.id && <>
                  <SaveButton cid={cid} mid={m.id} part={k} named={named} onSaved={(s) => { setSaved(m.id!, k, s); setToast({ mid: m.id!, part: k, saved: s }); qc.invalidateQueries({ queryKey: ["reader", cid] }); }} />
                  <RegenButton cid={cid} mid={m.id} part={k} onDone={(np) => setPart(m.id!, k, np)} /></>}
            </div>
          </div>)
        : (
          <div key={k} className="my-4 rounded-lg border border-border bg-muted/40 p-4 text-sm">
            <p className="font-medium">Drill summary</p>
            {!p.right.length && !p.review.length && <p className="mt-1 text-muted-foreground">No answers were recorded in this Drill.</p>}
            {p.right.length > 0 && <p className="mt-1">Went right: {p.right.join(", ")}</p>}
            {p.review.length > 0 && <ul className="mt-1 list-disc pl-5">{p.review.map((r) => <li key={r.concept}>Review {r.concept}{r.section_id && <> in <a className="underline" href={`/c/${cid}/read?section=${r.section_id}`}>{r.section}</a></>}</li>)}</ul>}
          </div>)
      ) : (
        <>
          {m.text.trim() ? <Md className="tutor-answer">{m.text}</Md> : !Object.keys(m.live ?? {}).length && !m.error && null}
          {Object.entries(m.live ?? {}).map(([k, v]) => v.status === "dropped" as string ? null : <div key={k} className="my-4"><BlockPlaceholder kind={v.kind} status={v.status} /></div>)}
        </>
      )}
      {m.remembered && <RememberedLine key={m.remembered.id} fact={m.remembered} />}
      {m.error && <Button size="sm" variant="outline" className="mt-2" onClick={retry}>Retry</Button>}
      {m.mode === "step" && m.id && !busy && (
        <p className="mt-2 flex flex-wrap gap-1.5">
          <Button size="sm" variant="outline" onClick={() => ask("More detail on that step.", { mode: "explain" })}>More detail</Button>
          <Button size="sm" variant="ghost" title="The wider theory, marked as not from the course" onClick={() => ask("What is beyond the course here?", { mode: "beyond" })}>Beyond the course</Button>
        </p>)}
      {m.mode === "step" && <div className="mt-2"><InExamLink chapters={chapters} anchor={m.anchor} /></div>}
      {!!m.citations?.length && <p className="mt-2 flex flex-wrap gap-1.5">{m.citations.map((c, k) => <button key={k} type="button" onClick={() => setCite(c)}
        className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground hover:border-primary hover:text-primary">{c.source} p.{c.page}</button>)}</p>}
    </div>
  );

  return (
    <div className="mx-auto flex h-[calc(100dvh-var(--hh))] w-full max-w-6xl gap-0 md:gap-4 md:px-4">
      <aside className={cn("w-full shrink-0 flex-col border-r border-border bg-card md:flex md:w-64 md:border-r-0", list ? "flex" : "hidden")} aria-label="Conversations">
        <div className="flex items-center justify-between px-4 py-3"><span className="text-sm font-medium">Conversations</span>
          <Button size="icon" variant="ghost" className="size-7" aria-label="New conversation" disabled={busy} onClick={() => open(null)}><Plus className="size-4" /></Button></div>
        <ul className="flex-1 divide-y divide-border overflow-y-auto">
          {!convs.length && <li className="px-4 py-3 text-sm text-muted-foreground">No conversation yet.</li>}
          {convs.map((c) => (
            <li key={c.id} className={cn("group flex items-start gap-2 px-4 py-2.5 hover:bg-accent/50", c.id === conv && "bg-accent")}>
              <button type="button" className="min-w-0 flex-1 text-left" disabled={busy} onClick={() => open(c.id)}>
                <span className="line-clamp-2 text-sm [overflow-wrap:anywhere]">{c.question}</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">{new Date(c.last_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</span></button>
              <Button size="icon" variant="ghost" className="size-7 shrink-0 opacity-60 group-hover:opacity-100" aria-label={`Delete “${c.question}”`}
                      disabled={remove.isPending} onClick={() => remove.mutate(c.id)}><Trash2 className="size-3.5" /></Button>
            </li>))}
        </ul>
      </aside>
      <section className={cn("min-w-0 flex-1 flex-col md:flex", list ? "hidden" : "flex")} aria-label="Course chat">
        <div className="flex items-center gap-2 border-b border-border px-4 py-2">
          <p className="min-w-0 flex-1 truncate text-sm"><span className="font-medium">Course chat</span>{title && <span className="text-muted-foreground"> · {title}</span>}</p>
          <Button size="sm" variant="ghost" className="md:hidden" onClick={() => setList(true)}>Conversations</Button>
          {drilling ? <Button size="sm" variant="outline" disabled={busy} onClick={() => ask("Stop the Drill and show me the summary.", { stopDrill: true })}>Stop Drill</Button>
            : <Button size="sm" variant="outline" disabled={busy} onClick={() => setQuiz(quiz ? null : { chapters: [], minutes: 15 })}><GraduationCap className="size-3.5" />Quiz me</Button>}
        </div>
        {quiz && (
          <form className="space-y-2 border-b border-border bg-muted/30 px-4 py-3 text-sm" onSubmit={(e) => { e.preventDefault(); ask("Quiz me.", { drill: quiz }); }}>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
              <span className="text-muted-foreground">Chapters</span>
              {chapters.map((c) => <label key={c.id} className="flex items-center gap-1.5"><input type="checkbox" className="accent-primary" checked={quiz.chapters.includes(c.id)}
                onChange={() => setQuiz({ ...quiz, chapters: quiz.chapters.includes(c.id) ? quiz.chapters.filter((x) => x !== c.id) : [...quiz.chapters, c.id] })} />{c.title}</label>)}
              {!quiz.chapters.length && <span className="text-xs text-muted-foreground">(none picked: the whole Course)</span>}
            </div>
            <label className="flex items-center gap-2">Minutes <input type="number" min={1} max={180} value={quiz.minutes} aria-label="Minutes"
              onChange={(e) => setQuiz({ ...quiz, minutes: Math.max(1, Math.min(180, Number(e.target.value) || 15)) })} className="w-20 rounded-md border border-border bg-background px-2 py-1" /></label>
            <Button type="submit" size="sm">Start</Button>
          </form>)}
        <div ref={box} className="flex-1 space-y-5 overflow-y-auto px-4 py-4 text-[0.95rem]"
             onMouseUp={() => setTimeout(() => setPick(picked()))} onScroll={() => setPick(null)}>
          {pick && <RewriteBar key={`${pick.mid}-${pick.part}-${pick.text}`} at={pick} onClose={() => setPick(null)} onGo={(note) => rewrite(pick, note)} />}
          {!msgs.length && <p className="text-sm text-muted-foreground">Ask anything about the Course. Answers come from your material and cite its pages; a Block drawn here can be saved into a Section.</p>}
          {msgs.map((m, i) => m.role === "learner" ? (editing?.at === i ? (
            <form key={i} className="ml-auto w-full max-w-[90%] space-y-2" onSubmit={(e) => { e.preventDefault(); if (editing.text.trim()) takeBack(i, editing.text.trim()); }}>
              <Textarea value={editing.text} onChange={(e) => setEditing({ at: i, text: e.target.value })} rows={3} aria-label="Edit your question" autoFocus />
              <p className="text-xs text-muted-foreground">Sending replaces this question and every message after it.</p>
              <div className="flex justify-end gap-2"><Button type="button" size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                <Button type="submit" size="sm" disabled={!editing.text.trim()}>Send again</Button></div>
            </form>
          ) : (
            <div key={i} className="group ml-auto flex w-fit max-w-[90%] items-start gap-1">
              {!busy && m.id && <span className="flex shrink-0 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                <Button size="icon" variant="ghost" className="size-7" aria-label="Edit and ask again" onClick={() => setEditing({ at: i, text: m.text })}><Pencil className="size-3.5" /></Button>
                <Button size="icon" variant="ghost" className="size-7" aria-label="Take this question back" onClick={() => takeBack(i)}><Undo2 className="size-3.5" /></Button></span>}
              <div className="rounded-lg rounded-br-sm bg-primary/10 px-3 py-2 text-sm">
                {!!m.images?.length && <div className="mb-2 flex flex-wrap gap-1.5">{m.images.map((src, k) => <img key={k} src={src} alt={`Image ${k + 1}`} className="max-h-28 rounded border border-border" />)}</div>}
                {!!m.labels?.length && <p className="mb-1 text-xs text-muted-foreground">{m.labels.join(" · ")}</p>}
                <AskedText text={m.text} /></div>
            </div>
          )) : answer(m, i))}
          {drilling && !busy && msgs.at(-1)?.role === "tutor" && !msgs.at(-1)?.error &&
            <Button size="sm" variant="outline" onClick={() => ask("Next question.")}>Next question</Button>}
          {trouble && <p className="text-xs text-destructive" role="alert">{trouble}</p>}
        </div>
        {(images.length > 0 || attached.length > 0 || Object.keys(ctx).length > 0 || docs.length > 0) && (
          <ul className="flex flex-wrap gap-2 border-t border-border px-3 pt-3" aria-label="Attached to the next question">
            {images.map((src, i) => (
              <li key={i} className="relative"><img src={src} alt={`Image ${i + 1}`} className="size-14 rounded-md border border-border object-cover" />
                <button type="button" aria-label={`Remove image ${i + 1}`} onClick={() => setImages(images.filter((_, k) => k !== i))}
                        className="absolute -right-1.5 -top-1.5 rounded-full border border-border bg-card p-0.5 hover:bg-accent"><X className="size-3" /></button></li>))}
            {attached.map((b) => (
              <li key={b.id} className="flex max-w-[14rem] items-center gap-1 rounded-md border border-border bg-muted/50 py-1 pl-2 pr-1 text-xs">
                <Paperclip className="size-3 shrink-0" /><span className="truncate">{labelOf(b)}</span>
                <button type="button" aria-label="Detach this Block" onClick={() => setAttached(attached.filter((x) => x.id !== b.id))}
                        className="rounded p-0.5 hover:bg-accent"><X className="size-3" /></button>
              </li>))}
            <ContextChips chapters={chapters} ctx={ctx} setCtx={setCtx} />
            {docs.map((d) => (
              <li key={d} className="flex max-w-full items-center gap-1 rounded-md border border-border bg-muted/50 py-1 pl-2 pr-1 text-xs">
                <FileText className="size-3 shrink-0" aria-hidden /><span className="min-w-0 truncate">{d}</span>
                <button type="button" aria-label={`Remove ${d}`} onClick={() => setDocs(docs.filter((x) => x !== d))} className="rounded p-0.5 hover:bg-accent"><X className="size-3" /></button>
              </li>))}
          </ul>)}
        <form className="flex flex-wrap items-end gap-2 border-t border-border p-3 [ul+&]:border-t-0" onSubmit={(e) => { e.preventDefault(); ask(); }}>
          <label className="mb-1 cursor-pointer rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground" title="Add images (or paste them into the box)">
            <ImagePlus className="size-4" aria-hidden /><span className="sr-only">Add images</span>
            <input type="file" multiple accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={(e) => { addImages(e.target.files ?? []); e.target.value = ""; }} /></label>
          <WriteButton cid={cid} onImage={(src) => setImages((all) => [...all, src].slice(0, 6))} onText={(said) => setQ((t) => appended(t, said))} />
          {chapters.length > 0 && <AttachPicker chapters={chapters} attached={attached} onAttach={(b) => setAttached((a) => [...a, b].slice(-12))} />}
          {chapters.length > 0 && <ContextPicker chapters={chapters} ctx={ctx} setCtx={setCtx} />}
          {sources.length > 0 && <DocPicker docs={sources} picked={docs} setPicked={setDocs} />}
          <button type="button" aria-pressed={shell} onClick={() => setShell(!shell)}
                  title={shell ? "Course files on: the tutor can run commands (ls, grep, python) on a read-only copy of the Course's files. Click to turn off."
                    : "Let the tutor run commands (ls, grep, python) on a read-only copy of the Course's files"}
                  className={cn("mb-1 rounded-md p-1.5 outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring", shell ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground")}>
            <SquareTerminal className="size-4" aria-hidden /><span className="sr-only">Course files</span></button>
          <DictateButton cid={cid} onText={(said) => setQ((t) => appended(t, said))} />
          <ModeSelect mode={mode} setMode={setMode} disabled={drilling} />
          <Textarea ref={qBox} onChange={(e) => setHasQ(!!e.target.value.trim())} rows={2} placeholder="Ask about the Course…" aria-label="Question" className="order-first max-h-[min(10rem,25dvh)] min-h-0 basis-full resize-none"
                    onPaste={(e) => { const f = [...e.clipboardData.files]; if (f.length) { e.preventDefault(); addImages(f); } }}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } }} />
          {busy ? <Button key="stop" type="button" size="icon" variant="outline" className="ml-auto" aria-label="Stop" title="Stop: the question goes back in the box" onClick={() => stop.current?.abort()}><Square className="size-3.5 fill-current" /></Button>
            : <Button key="ask" type="submit" size="icon" className="ml-auto" disabled={!hasQ} aria-label="Ask"><Send className="size-4" /></Button>}
        </form>
      </section>
      {toast && (
        <div role="status" className="fixed bottom-24 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-md border border-border bg-card px-4 py-2 text-sm shadow-md">
          <span>Saved in {toast.saved.section}</span>
          <Button size="sm" variant="ghost" onClick={undo}>Undo</Button>
        </div>)}
      <PageViewer cid={cid} cite={cite} onClose={() => setCite(null)} />
    </div>
  );
}
