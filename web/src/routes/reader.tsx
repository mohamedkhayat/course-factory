import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { MessageCircle, Send, X } from "lucide-react";
import { PageViewer, ReaderBlock } from "@/components/blocks";
import { Md } from "@/components/md";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { get, readEvents, send, type Chapter, type Citation, type Course } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useCid } from "./run";

type Msg = { role: "learner" | "tutor"; text: string; citations?: Citation[]; error?: boolean };

/** The tutor panel. With `lab`, it coaches on a Lab Step: the learner's current code and last outputs go with each question. */
export function Tutor({ cid, sectionId, lab, onCite, onClose, className }: {
  cid: number; sectionId?: number; lab?: () => { lab_step_id: number; code: string; outputs: unknown[] };
  onCite: (c: Citation) => void; onClose: () => void; className?: string;
}) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [conv, setConv] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs]); // braces: scrollIntoView can return a Promise, not a cleanup
  const ask = async () => {
    const question = q.trim();
    if (!question || busy) return;
    setQ(""); setBusy(true);
    setMsgs((m) => [...m, { role: "learner", text: question }, { role: "tutor", text: "" }]);
    const patch = (f: (m: Msg) => Msg) => setMsgs((all) => [...all.slice(0, -1), f(all[all.length - 1])]);
    try {
      const res = await fetch(`/api/courses/${cid}/tutor`, { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ question, section_id: sectionId ?? null, conversation_id: conv, ...lab?.() }) });
      await readEvents(res, (ev, d) => {
        if (ev === "token") patch((m) => ({ ...m, text: m.text + d.text }));
        if (ev === "done") { setConv(d.conversation_id); patch((m) => ({ ...m, citations: d.citations })); }
        if (ev === "error") patch((m) => ({ ...m, text: d.message, error: true }));
      });
    } catch (e) {
      patch((m) => ({ ...m, text: String(e), error: true }));
    } finally { setBusy(false); }
  };
  return (
    <aside className={cn("flex h-full flex-col border-l border-border bg-card", className)} aria-label="Tutor">
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <p className="font-medium">Tutor</p>
        <Button size="icon" variant="ghost" className="size-7" onClick={onClose} aria-label="Close the tutor"><X className="size-4" /></Button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3 text-[0.95rem]">
        {!msgs.length && <p className="text-sm text-muted-foreground">{lab ? "Ask about your code. The tutor sees it, its output and plots, and coaches you without giving the answer."
          : "Ask about this Section. Answers come from your course material and cite its pages."}</p>}
        {msgs.map((m, i) => (
          <div key={i} className={cn(m.role === "learner" ? "ml-8 rounded-md bg-muted px-3 py-2" : "", m.error && "text-destructive")}>
            {m.text ? <Md>{m.text}</Md> : <span className="text-muted-foreground">Thinking…</span>}
            {!!m.citations?.length && (
              <p className="mt-1 flex flex-wrap gap-2 text-xs">
                {m.citations.map((c, k) => <button key={k} type="button" className="underline decoration-dotted" onClick={() => onCite(c)}>{c.source} p.{c.page}</button>)}
              </p>
            )}
          </div>
        ))}
        <div ref={end} />
      </div>
      <form className="flex gap-2 border-t border-border p-3" onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <Textarea value={q} onChange={(e) => setQ(e.target.value)} rows={2} placeholder={lab ? "Why does this raise a TypeError?" : "Why is the Hessian positive definite here?"} aria-label="Question"
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } }} className="min-h-0 resize-none" />
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
