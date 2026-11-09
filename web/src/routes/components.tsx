import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CustomComponent } from "@/components/blocks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { get, send } from "@/lib/api";
import { cn } from "@/lib/utils";
import { errText, Page } from "./home";

type Gate = { gate: string; ok: boolean; errors: string[] };
type Comp = { id: number; name: string; description: string; why: string; status: string; reviewed: boolean; made_by_local_model: boolean; gates: Gate[]; has_screenshot: boolean; samples?: unknown[]; blocks?: { id: number }[] };

function Detail({ id }: { id: number }) {
  const qc = useQueryClient();
  const { data: c } = useQuery({ queryKey: ["component", id], queryFn: () => get<Comp>(`/api/components/${id}`) });
  const [note, setNote] = useState("");
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: object }) => send(`/api/components/${id}/${path}`, body),
    onSuccess: () => { setNote(""); qc.invalidateQueries({ queryKey: ["component", id] }); qc.invalidateQueries({ queryKey: ["components"] }); },
  });
  if (!c) return null;
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-mono text-lg">{c.name}</h2>
        <Badge variant={c.status === "approved" ? "default" : c.status === "failed" || c.status === "rejected" ? "destructive" : "secondary"}>{c.status}</Badge>
        {c.made_by_local_model && <Badge variant="outline">{c.reviewed ? "reviewed" : "local model · not reviewed"}</Badge>}
      </div>
      <p className="mt-2">{c.description}</p>
      <p className="mt-1 text-sm text-muted-foreground">Why: {c.why}</p>
      <ul className="mt-4 flex flex-wrap gap-2 text-sm">
        {c.gates.map((g) => <li key={g.gate} className={cn("rounded-md px-2 py-0.5", g.ok ? "bg-ok/12 text-ok" : "bg-destructive/12 text-destructive")} title={g.errors.join("\n")}>{g.ok ? "✓" : "✗"} {g.gate}</li>)}
      </ul>
      {c.gates.filter((g) => !g.ok).map((g) => <pre key={g.gate} className="mt-2 overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs">{g.errors.join("\n")}</pre>)}
      <div className="mt-6 space-y-4">
        {(c.samples ?? []).map((s, i) => (
          <div key={i} className="rounded-md border border-border p-4">
            <p className="mb-2 text-xs text-muted-foreground">Sample {i + 1}</p>
            <CustomComponent block={{ data: s, component: c.name }} comp={c} />
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-muted-foreground">Used by {c.blocks?.length ?? 0} Blocks. Until approved, they show as plain Markdown.</p>
      {act.error && <p className="mt-2 text-sm text-destructive">{errText(act.error)}</p>}
      {c.status === "preview" && (
        <div className="mt-4 flex gap-2">
          <Button onClick={() => act.mutate({ path: "approve" })} disabled={act.isPending}>Approve</Button>
          <Button variant="outline" onClick={() => act.mutate({ path: "reject" })} disabled={act.isPending}>Reject</Button>
        </div>
      )}
      <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); act.mutate({ path: "regenerate", body: { note } }); }}>
        <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="What should change? e.g. label the axes" aria-label="Note for regenerating" />
        <Button type="submit" variant="secondary" disabled={!note.trim() || act.isPending}>{act.isPending ? "Building…" : "Regenerate"}</Button>
      </form>
    </div>
  );
}

export function ComponentsPage() {
  const { data = [] } = useQuery({ queryKey: ["components"], queryFn: () => get<Comp[]>("/api/components") });
  const [sel, setSel] = useState<number | null>(null);
  const id = sel ?? data[0]?.id;
  return (
    <Page title="Components" wide>
      {!data.length ? <p className="text-muted-foreground">No model-made Component yet. The 15 built-in ones cover most Blocks.</p> : (
        <div className="grid gap-8 md:grid-cols-[14rem_1fr]">
          <ul className="space-y-1">
            {data.map((c) => (
              <li key={c.id}><button type="button" onClick={() => setSel(c.id)} aria-current={c.id === id || undefined}
                className={cn("flex w-full justify-between rounded-md px-2 py-1.5 text-left text-sm", c.id === id ? "bg-accent" : "hover:bg-accent/60")}>
                <span className="truncate font-mono">{c.name}</span><span className="text-xs text-muted-foreground">{c.status}</span></button></li>
            ))}
          </ul>
          {id && <Detail id={id} />}
        </div>
      )}
    </Page>
  );
}
