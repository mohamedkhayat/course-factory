import { cn } from "@/lib/utils";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BlockBody } from "@/components/blocks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { get, send, type Block } from "@/lib/api";
import { errText, Page } from "./home";
import { useCid } from "./run";

type RBlock = Block & { section: string };

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
      </div>
      {b.flags.length > 0 && <ul className={cn("mb-3 list-disc pl-5 text-sm", b.status === "flagged" ? "text-destructive" : "text-warn")}>{b.flags.map((f, i) => <li key={i}>{f}</li>)}</ul>}
      {mode === "edit" ? (
        <div className="space-y-2">
          <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={12} className="font-mono text-xs" aria-label="Block data (JSON)" />
          <div className="flex gap-2"><Button size="sm" onClick={save}>Save</Button><Button size="sm" variant="ghost" onClick={() => setMode("view")}>Cancel</Button></div>
        </div>
      ) : <div className="prose-cf"><BlockBody block={b} cid={cid} /></div>}
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
  const publish = useMutation({ mutationFn: (chid: number) => send(`/api/courses/${cid}/chapters/${chid}/publish`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["review", cid] }); qc.invalidateQueries({ queryKey: ["run", cid] }); } });
  return (
    <Page title="Review">
      {!data.length && <p className="text-muted-foreground">Nothing waits for review.</p>}
      {data.map((ch) => {
        const flagged = ch.blocks.filter((b) => b.status === "flagged").length;
        return (
          <section key={ch.id} className="mb-12">
            <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-foreground/30 pb-2">
              <h2 className="font-display text-xl font-semibold">{ch.title}</h2>
              <span className="flex items-center gap-3 text-sm">
                <span className="tabular text-muted-foreground">{flagged ? `${flagged} flagged` : "no flags"} · {ch.blocks.length} Blocks</span>
                <Button size="sm" disabled={!!flagged || publish.isPending} onClick={() => publish.mutate(ch.id)}>Publish</Button>
              </span>
            </div>
            {publish.error && <p className="mt-2 text-sm text-destructive">{errText(publish.error)}</p>}
            <ul className="divide-y divide-border">{ch.blocks.map((b) => <ReviewBlock key={b.id} cid={cid} b={b} />)}</ul>
          </section>
        );
      })}
    </Page>
  );
}
