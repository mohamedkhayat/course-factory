import { MdLine } from "../components/md";
import { cn } from "@/lib/utils";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BlockBody } from "@/components/blocks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { get, send, type Block } from "@/lib/api";
import { errText, Page } from "./home";
import { useCid } from "./run";

type RBlock = Block & { section: string };

/** Mounts its children once they come near the viewport: Review lists hundreds of Blocks full of math and diagrams. */
function Lazy({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || shown) return;
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setShown(true); io.disconnect(); } }, { rootMargin: "1500px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, [shown]);
  return <div ref={ref}>{shown ? children : <div className="h-48" />}</div>;
}

function ReviewBlock({ cid, b }: { cid: number; b: RBlock }) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<"view" | "edit" | "regen">("view");
  const [text, setText] = useState("");
  const done = () => { setMode("view"); qc.invalidateQueries({ queryKey: ["review", cid] }); };
  const act = useMutation({ mutationFn: ({ path, body, method }: { path: string; body?: object; method?: string }) => send(`/api/courses/${cid}/blocks/${b.id}/${path}`, body, method), onSuccess: done });
  const [err, setErr] = useState<string | null>(null);
  const save = () => {
    let data: unknown;
    try { data = JSON.parse(text); } catch { return setErr("That isn't valid JSON."); }
    send(`/api/courses/${cid}/blocks/${b.id}`, { data }, "PUT").then(() => { setErr(null); done(); }, (e) => setErr(errText(e)));
  };
  return (
    <li className="py-5" data-block={b.id}>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">{b.section}</span>
        <Badge variant="outline" className="font-mono">{b.component}</Badge>
        {b.origin === "model_added" && <Badge variant="secondary">model-added</Badge>}
        {b.status === "flagged" && <Badge variant="destructive">flagged</Badge>}
        {b.review_queue && <Badge variant="outline" title="Auto-resolve couldn't fix it: run /review-blocks in Claude Code">in the Review Queue</Badge>}
        {b.previous && <Badge variant="secondary">auto-resolved</Badge>}
      </div>
      {b.flags.length > 0 && <ul className={cn("mb-3 list-disc pl-5 text-sm", b.status === "flagged" ? "text-destructive" : "text-warn")}>{b.flags.map((f, i) => <li key={i}><MdLine>{f}</MdLine></li>)}</ul>}
      {mode === "edit" ? (
        <div className="space-y-2">
          <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={12} className="font-mono text-xs" aria-label="Block data (JSON)" />
          <div className="flex gap-2"><Button size="sm" onClick={save}>Save</Button><Button size="sm" variant="ghost" onClick={() => setMode("view")}>Cancel</Button></div>
        </div>
      ) : <Lazy>
        {b.previous && mode === "view" ? (
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-md border border-dashed border-input p-3 opacity-80"><p className="mb-2 text-xs text-muted-foreground">Before</p>
              <div className="prose-cf"><BlockBody block={{ ...b, ...b.previous }} cid={cid} /></div></div>
            <div className="rounded-md border border-border p-3"><p className="mb-2 text-xs text-muted-foreground">After</p>
              <div className="prose-cf"><BlockBody block={b} cid={cid} /></div></div>
          </div>
        ) : <div className="prose-cf"><BlockBody block={b} cid={cid} /></div>}
      </Lazy>}
      {mode === "regen" && (
        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); act.mutate({ path: "regenerate", body: { note: text } }); }}>
          <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} placeholder="What should change?" aria-label="Note for the model" />
          <Button type="submit" size="sm" disabled={!text.trim() || act.isPending}>{act.isPending ? "Writing…" : "Regenerate"}</Button>
        </form>
      )}
      {(err || act.error) && <p className="mt-2 text-sm text-destructive">{err ?? errText(act.error)}</p>}
      {mode === "view" && (
        <div className="mt-3 flex gap-2">
          {b.status === "flagged" && <Button size="sm" variant="outline" onClick={() => act.mutate({ path: "approve" })}>It's fine</Button>}
          {b.previous && <Button size="sm" variant="ghost" onClick={() => act.mutate({ path: "undo" })}>Undo auto-resolve</Button>}
          <Button size="sm" variant="ghost" onClick={() => { setText(JSON.stringify(b.data, null, 2)); setMode("edit"); }}>Edit</Button>
          <Button size="sm" variant="ghost" onClick={() => { setText(""); setMode("regen"); }}>Regenerate…</Button>
        </div>
      )}
    </li>
  );
}

export function Review() {
  const cid = useCid();
  const qc = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ["review", cid], queryFn: () => get<{ id: number; title: string; blocks: RBlock[] }[]>(`/api/courses/${cid}/review`) });
  const resolve = useMutation({ mutationFn: (chid: number) => send<{ resolved: number[]; queued: number[] }>(`/api/courses/${cid}/chapters/${chid}/auto-resolve`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["review", cid] }) });
  const publish = useMutation({ mutationFn: (chid: number) => send(`/api/courses/${cid}/chapters/${chid}/publish`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["review", cid] }); qc.invalidateQueries({ queryKey: ["run", cid] }); } });
  return (
    <Page title="Review">
      {!data.length && <p className="text-muted-foreground">Nothing waits for review.</p>}
      <FailurePanel cid={cid} />
      {data.map((ch) => {
        const flagged = ch.blocks.filter((b) => b.status === "flagged").length;
        return (
          <section key={ch.id} id={`chapter-${ch.id}`} className="mb-12 scroll-mt-6">
            <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-foreground/30 pb-2">
              <h2 className="font-display text-xl font-semibold">{ch.title}</h2>
              <span className="flex items-center gap-3 text-sm">
                <span className="tabular text-muted-foreground">{flagged ? `${flagged} flagged` : "no flags"} · {ch.blocks.length} Blocks</span>
                {!!flagged && <Button size="sm" variant="outline" disabled={resolve.isPending} onClick={() => resolve.mutate(ch.id)}
                                      title="The local model repairs each flagged Block with its flag as the note, then re-checks it">
                  {resolve.isPending && resolve.variables === ch.id ? "Resolving…" : "Auto-resolve"}</Button>}
                <Button size="sm" disabled={!!flagged || publish.isPending} onClick={() => publish.mutate(ch.id)}>Publish</Button>
              </span>
            </div>
            {publish.error && <p className="mt-2 text-sm text-destructive">{errText(publish.error)}</p>}
            {resolve.data && resolve.variables === ch.id && <p className="mt-2 text-sm text-muted-foreground">
              Resolved {resolve.data.resolved.length}; {resolve.data.queued.length ? `${resolve.data.queued.length} left for the Review Queue (run /review-blocks in Claude Code)` : "nothing left"}.</p>}
            {resolve.error && resolve.variables === ch.id && <p className="mt-2 text-sm text-destructive">{errText(resolve.error)}</p>}
            <ul className="divide-y divide-border">{ch.blocks.map((b) => <ReviewBlock key={b.id} cid={cid} b={b} />)}</ul>
          </section>
        );
      })}
    </Page>
  );
}

type FailureRow = { class: string; count: number; handler: string; what: string | null; examples: string[]; rate: { before: number | null; after: number | null } | null };

/** What keeps going wrong in this Course's generation, and how each kind is handled now (harness/failures.yaml). */
function FailurePanel({ cid }: { cid: number }) {
  const { data = [] } = useQuery({ queryKey: ["failures", cid], queryFn: () => get<FailureRow[]>(`/api/failures?course=${cid}`) });
  if (!data.length) return null;
  const pct = (r: number | null) => (r == null ? "–" : `${Math.round(r * 100)}%`);
  return (
    <details className="mb-10 rounded-md border border-border px-4 py-3 text-sm">
      <summary className="cursor-pointer font-medium">Failure classes <span className="font-normal text-muted-foreground">· what the checks catch most, and what is hardened</span></summary>
      <table className="mt-3 w-full text-left">
        <thead className="text-xs text-muted-foreground"><tr><th className="py-1 font-normal">Class</th><th className="font-normal">Count</th><th className="font-normal">Handled by</th><th className="font-normal">Rate before → after</th></tr></thead>
        <tbody className="divide-y divide-border">
          {data.slice(0, 15).map((f) => (
            <tr key={f.class} title={f.examples[0]}>
              <td className="py-1 font-mono text-xs">{f.class}</td>
              <td className="tabular">{f.count}</td>
              <td className={f.handler === "none" ? "text-muted-foreground" : "text-ok"}>{f.handler === "none" ? "not hardened" : f.handler}</td>
              <td className="tabular text-muted-foreground">{f.rate ? `${pct(f.rate.before)} → ${pct(f.rate.after)}` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-muted-foreground">Run /harden in Claude Code to turn the top class into a Heal or Check.</p>
    </details>
  );
}
