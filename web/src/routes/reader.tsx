import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, MessageCircle, Plus, Send, Trash2, X } from "lucide-react";
import { BlockBody, PageViewer, ReaderBlock } from "@/components/blocks";
import { Md, MdLine } from "@/components/md";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { get, readEvents, send, type Block, type Chapter, type Citation, type Course } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useCid } from "./run";

type Proposal = { action: "add" | "replace"; target: number | null; block: Omit<Block, "id" | "position" | "status" | "flags"> | null;
  flags: { errors: string[]; warnings: string[] }; status: "open" | "accepted" | "dismissed" };
type Msg = { id?: number; role: "learner" | "tutor"; text: string; citations?: Citation[]; proposal?: Proposal | null; error?: boolean };
type Conversation = { id: number; question: string; section_id: number | null; section: string | null; last_at: string };

const PROPOSAL = /```proposal[\s\S]*?(```|$)/;  // the Block JSON shows as a card, not as text

function ProposalCard({ cid, mid, p, onDone }: { cid: number; mid: number; p: Proposal; onDone: (status: Proposal["status"]) => void }) {
  const qc = useQueryClient();
  const act = useMutation({
    mutationFn: (accept: boolean) => send(`/api/courses/${cid}/tutor/messages/${mid}/${accept ? "accept" : "dismiss"}`, {}),
    onSuccess: (_, accept) => { onDone(accept ? "accepted" : "dismissed"); if (accept) qc.invalidateQueries({ queryKey: ["reader", cid] }); },
  });
  const verb = p.action === "replace" ? `Replace Block ${p.target}` : "Add to Section";
  return (
    <div className="mt-3 overflow-hidden rounded-md border border-border bg-background">
      <p className="flex items-center justify-between gap-2 border-b border-border bg-muted/60 px-3 py-1.5 text-xs text-muted-foreground">
        <span>Proposed {p.block?.component.replaceAll("_", " ") ?? "Block"}{p.action === "replace" ? ` · replaces Block ${p.target}` : ""}</span>
        {p.status !== "open" && <span className={cn("font-medium", p.status === "accepted" && "text-ok")}>{p.status}</span>}
      </p>
      {p.block && <div className="prose-cf max-h-80 overflow-y-auto px-3 py-2 text-sm"><BlockBody cid={cid} block={{ ...p.block, id: 0, position: 0, status: "ok", flags: [] }} /></div>}
      {!!p.flags.errors.length && (
        <ul className="space-y-1 border-t border-border px-3 py-2 text-xs text-destructive">
          <li className="font-medium">It fails the Block checks, so it can't be added:</li>
          {p.flags.errors.map((e, i) => <li key={i} className="[overflow-wrap:anywhere]">{e}</li>)}
        </ul>
      )}
      {p.status === "open" && (
        <div className="flex justify-end gap-2 border-t border-border px-3 py-2">
          <Button size="sm" variant="ghost" disabled={act.isPending} onClick={() => act.mutate(false)}>Dismiss</Button>
          {!p.flags.errors.length && <Button size="sm" disabled={act.isPending} onClick={() => act.mutate(true)}>{verb}</Button>}
        </div>
      )}
      {act.error && <p className="px-3 pb-2 text-xs text-destructive">{String(act.error.message)}</p>}
    </div>
  );
}

/** The tutor panel. With `lab`, it coaches on a Lab Step: the learner's current code and last outputs go with each question.
 * In the reader it reopens the Section's latest conversation, and lists past ones to reopen or delete. */
export function Tutor({ cid, sectionId, lab, onCite, onClose, className }: {
  cid: number; sectionId?: number; lab?: () => { lab_step_id: number; code: string; outputs: unknown[] };
  onCite: (c: Citation) => void; onClose: () => void; className?: string;
}) {
  const qc = useQueryClient();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [conv, setConv] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const { data: convs = [] } = useQuery({ queryKey: ["tutor", cid], enabled: !lab,
    queryFn: () => get<Conversation[]>(`/api/courses/${cid}/tutor`) });
  const open = async (id: number | null) => {
    setConv(id); setHistory(false);
    setMsgs(id === null ? [] : await get<Msg[]>(`/api/courses/${cid}/tutor/${id}`));
  };
  const opened = useRef<number | undefined>(undefined);
  useEffect(() => {  // a Section opens on its latest conversation, once the list has loaded
    if (lab || busy || opened.current === sectionId || !qc.getQueryData(["tutor", cid])) return;
    opened.current = sectionId;
    open(convs.find((c) => c.section_id === sectionId)?.id ?? null);
  }, [sectionId, convs]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs]); // braces: scrollIntoView can return a Promise, not a cleanup
  const remove = useMutation({
    mutationFn: (id: number) => send(`/api/courses/${cid}/tutor/${id}`, undefined, "DELETE"),
    onSuccess: (_, id) => { if (id === conv) open(null); qc.invalidateQueries({ queryKey: ["tutor", cid] }); },
  });
  const ask = async () => {
    const question = q.trim();
    if (!question || busy) return;
    setQ(""); setBusy(true); setHistory(false);
    setMsgs((m) => [...m, { role: "learner", text: question }, { role: "tutor", text: "" }]);
    const patch = (f: (m: Msg) => Msg) => setMsgs((all) => [...all.slice(0, -1), f(all[all.length - 1])]);
    try {
      const res = await fetch(`/api/courses/${cid}/tutor`, { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ question, section_id: sectionId ?? null, conversation_id: conv, ...lab?.() }) });
      await readEvents(res, (ev, d) => {
        if (ev === "token") patch((m) => ({ ...m, text: m.text + d.text }));
        if (ev === "done") { setConv(d.conversation_id); patch((m) => ({ ...m, id: d.message_id, citations: d.citations, proposal: d.proposal })); }
        if (ev === "error") patch((m) => ({ ...m, text: d.message, error: true }));
      });
    } catch (e) {
      patch((m) => ({ ...m, text: String(e), error: true }));
    } finally { setBusy(false); if (!lab) qc.invalidateQueries({ queryKey: ["tutor", cid] }); }
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
        <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4 text-[0.95rem]">
          {!msgs.length && <p className="text-sm text-muted-foreground">{lab ? "Ask about your code. The tutor sees it, its output and plots, and coaches you without giving the answer."
            : "Ask about this Section, or ask for a Block to add. Answers come from your course material and cite its pages."}</p>}
          {msgs.map((m, i) => m.role === "learner" ? (
            <p key={i} className="ml-auto w-fit max-w-[90%] whitespace-pre-wrap rounded-lg rounded-br-sm bg-primary/10 px-3 py-2 text-sm [overflow-wrap:anywhere]">{m.text}</p>
          ) : (
            <div key={i} className={cn("min-w-0", m.error && "text-destructive")}>
              {m.text.replace(PROPOSAL, "").trim() ? <Md className="tutor-answer">{m.text.replace(PROPOSAL, "")}</Md>
                : !m.proposal && <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
                    <span className="flex gap-1" aria-hidden>{[0, 1, 2].map((k) => <span key={k} className="size-1.5 animate-pulse rounded-full bg-muted-foreground" style={{ animationDelay: `${k * 150}ms` }} />)}</span>
                    {PROPOSAL.test(m.text) ? "Writing a Block…" : "Thinking…"}</p>}
              {!!m.citations?.length && (
                <p className="mt-2 flex flex-wrap gap-1.5">
                  {m.citations.map((c, k) => <button key={k} type="button" onClick={() => onCite(c)}
                    className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground hover:border-primary hover:text-primary">{c.source} p.{c.page}</button>)}
                </p>
              )}
              {m.proposal && m.id && <ProposalCard cid={cid} mid={m.id} p={m.proposal}
                onDone={(status) => setMsgs((all) => all.map((x) => x === m ? { ...x, proposal: { ...m.proposal!, status } } : x))} />}
            </div>
          ))}
          <div ref={end} />
        </div>
      )}
      <form className="flex items-end gap-2 border-t border-border p-3" onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <Textarea value={q} onChange={(e) => setQ(e.target.value)} rows={2} placeholder={lab ? "Why does this raise a TypeError?" : "Ask about this Section…"} aria-label="Question"
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } }} className="max-h-40 min-h-0 resize-none" />
        <Button type="submit" size="icon" disabled={busy || !q.trim()} aria-label="Ask"><Send className="size-4" /></Button>
      </form>
    </aside>
  );
}

export function Reader() {
  const cid = useCid();
  const { data: chapters = [] } = useQuery({ queryKey: ["reader", cid], queryFn: () => get<Chapter[]>(`/api/courses/${cid}/reader`) });
  const { data: place } = useQuery({ queryKey: ["place", cid], queryFn: () => get<{ section_id: number | null; read: number[] }>(`/api/courses/${cid}/place`) });
  const { data: course } = useQuery({ queryKey: ["course", String(cid)], queryFn: () => get<Course>(`/api/courses/${cid}`) });
  const [sid, setSid] = useState<number | null>(() => Number(new URLSearchParams(location.search).get("section")) || null);
  const [cite, setCite] = useState<Citation | null>(null);
  const [tutor, setTutor] = useState(false);
  const mark = useMutation({ mutationFn: (section_id: number) => send(`/api/courses/${cid}/place`, { section_id }, "PUT") });
  const sections = chapters.flatMap((c) => c.sections.map((s) => ({ ...s, chapter: c })));
  const current = sections.find((s) => s.id === sid) ?? sections.find((s) => s.id === place?.section_id) ?? sections[0];
  useEffect(() => { if (current) mark.mutate(current.id); }, [current?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const read = new Set(place?.read ?? []);
  const i = current ? sections.indexOf(current) : -1;
  const go = (id: number) => { setSid(id); scrollTo({ top: 0 }); };
  if (!chapters.length) return <p className="px-6 py-10 text-muted-foreground">No Chapter is published yet. Publish Chapters from Review.</p>;
  return (
    <div className={cn("grid min-h-[calc(100dvh-3rem)]", tutor ? "lg:grid-cols-[16rem_1fr_24rem]" : "lg:grid-cols-[16rem_1fr]")}>
      <nav className="hidden border-r border-border px-3 py-6 lg:block" aria-label="Chapters">
        <div className="sticky top-18 max-h-[calc(100dvh-6rem)] space-y-5 overflow-y-auto">
          {chapters.map((c) => (
            <div key={c.id}>
              <p className="flex items-baseline justify-between gap-2 px-2 font-display text-sm font-semibold">{c.title}
                {course?.goal === "cram" && <span className="tabular shrink-0 font-sans text-xs font-normal text-muted-foreground">
                  {Math.round(c.exam_weight * 100)}% of exams</span>}</p>
              <ul className="mt-1">
                {c.sections.map((s) => (
                  <li key={s.id}>
                    <button type="button" onClick={() => go(s.id)} aria-current={s.id === current?.id ? "page" : undefined}
                            className={cn("flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-sm text-muted-foreground hover:text-foreground",
                                          s.id === current?.id && "bg-accent text-foreground")}>
                      <span className={cn("size-1.5 shrink-0 rounded-full", read.has(s.id) ? "bg-ok" : "bg-border")} aria-label={read.has(s.id) ? "read" : undefined} />
                      {s.title}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </nav>
      {current && (
        <article className="mx-auto w-full max-w-[44rem] px-5 py-8 sm:px-8">
          <p className="text-sm text-muted-foreground">{current.chapter.title}</p>
          <h1 className="mt-1 font-display text-3xl font-semibold tracking-tight">{current.title}</h1>
          {!!current.teaches?.length && <p className="mt-2 text-sm text-muted-foreground">New here: {current.teaches.join(" · ")}</p>}
          {!!current.objectives?.length && (
            <div className="mt-4 text-sm">
              <p className="font-medium">You'll be able to</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted-foreground">{current.objectives.map((o, i) => <li key={i}><MdLine>{o}</MdLine></li>)}</ul>
            </div>
          )}
          <div className="prose-cf mt-8 space-y-10">
            {current.blocks.map((b) => <ReaderBlock key={b.id} block={b} cid={cid} onCite={setCite} />)}
          </div>
          <div className="mt-14 flex justify-between gap-4 border-t border-border pt-4 text-sm">
            {i > 0 ? <button type="button" onClick={() => go(sections[i - 1].id)} className="text-left hover:text-primary">← {sections[i - 1].title}</button> : <span />}
            {i < sections.length - 1 && <button type="button" onClick={() => go(sections[i + 1].id)} className="text-right hover:text-primary">{sections[i + 1].title} →</button>}
          </div>
        </article>
      )}
      {tutor ? (
        <div className="fixed inset-x-0 bottom-0 top-12 z-20 lg:sticky lg:top-12 lg:h-[calc(100dvh-3rem)]">
          <Tutor cid={cid} sectionId={current?.id} onCite={setCite} onClose={() => setTutor(false)} />
        </div>
      ) : (
        <Button className="fixed bottom-5 right-5 z-20 shadow-md" onClick={() => setTutor(true)}><MessageCircle className="size-4" />Ask the tutor</Button>
      )}
      <PageViewer cid={cid} cite={cite} onClose={() => setCite(null)} />
    </div>
  );
}
