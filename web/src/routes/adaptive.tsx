import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, Check } from "lucide-react";
import { BlockBody } from "@/components/blocks";
import { Button } from "@/components/ui/button";
import { Progress as Bar } from "@/components/ui/progress";
import { get, type PracticeQueue } from "@/lib/api";
import { cn } from "@/lib/utils";
import { blockLabel } from "./reader-tools";
import { useCid } from "./run";

const KINDS: Record<PracticeQueue["items"][number]["kind"], [string, string]> = {
  missed: ["missed last time", "bg-destructive/15 text-destructive"], weak: ["on weak Concepts", "bg-warn/20 text-foreground"],
  due: ["due for review", "bg-primary/15 text-primary"], new: ["not tried yet", "bg-muted text-muted-foreground"],
};

/** Practice picked from the learner's own results: what was missed, what is weak, what is due again, then what is new. One
 * Block at a time, Sections interleaved. */
export function PracticePage() {
  const cid = useCid();
  const qc = useQueryClient();
  const { data, isFetching, refetch } = useQuery({ queryKey: ["practice-round", cid], staleTime: Infinity, gcTime: 0,
    queryFn: () => get<PracticeQueue>(`/api/courses/${cid}/practice?limit=8`) });
  const [i, setI] = useState(0);
  const [done, setDone] = useState<Set<number>>(new Set());
  useEffect(() => {
    const on = () => { setDone((d) => new Set(d).add(i)); for (const k of ["progress", "practice", "results"]) qc.invalidateQueries({ queryKey: [k, cid] }); };
    addEventListener("cf-attempt", on);
    return () => removeEventListener("cf-attempt", on);
  }, [i, cid, qc]);
  if (!data) return <p className="px-6 py-10 text-muted-foreground" role="status">Choosing what you need…</p>;
  const items = data.items, item = items[i];
  const again = () => { setI(0); setDone(new Set()); refetch(); };
  return (
    <div className="mx-auto w-full max-w-[46rem] px-5 py-8 sm:px-8">
      <h1 className="font-display text-3xl font-semibold tracking-tight">Practice</h1>
      <p className="mt-1 text-muted-foreground">Chosen from your own results: what you missed comes first, then weak Concepts, then what is due again, then what you have not tried.</p>
      <p className="mt-3 flex flex-wrap gap-2 text-xs">
        {(Object.keys(KINDS) as (keyof typeof KINDS)[]).filter((k) => data.counts[k]).map((k) =>
          <span key={k} className={cn("rounded-full px-2 py-0.5 font-medium", KINDS[k][1])}>{data.counts[k]} {KINDS[k][0]}</span>)}
      </p>
      {!items.length ? (
        <p className="mt-8 rounded-lg border border-dashed border-border px-4 py-8 text-center text-muted-foreground">
          Nothing to practise right now. Practice draws on Sections you have opened: read one, or come back when something is due.
          <Link to="/c/$cid/read" params={{ cid: String(cid) }} className="mt-2 block text-primary underline decoration-dotted underline-offset-4">Go to the reader</Link></p>
      ) : !item ? (
        <div className="mt-8 rounded-lg border border-border bg-card px-5 py-8 text-center">
          <Check className="mx-auto size-8 text-ok" aria-hidden />
          <p className="mt-2 font-display text-xl font-semibold">Round done</p>
          <p className="mt-1 text-muted-foreground">You answered {done.size} of {items.length}. What you missed comes back first next round; what you got right waits a few days.</p>
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            <Button onClick={again} disabled={isFetching}>Another round</Button>
            <Button asChild variant="outline"><Link to="/c/$cid/progress" params={{ cid: String(cid) }}>See Progress</Link></Button>
          </div>
        </div>
      ) : (
        <>
          <div className="mt-6 flex items-center gap-3 text-sm text-muted-foreground">
            <span className="tabular shrink-0">{i + 1} of {items.length}</span>
            <Bar value={(i / items.length) * 100} className="h-1.5" aria-label="Place in the round" />
          </div>
          <article key={`${item.block.id}-${i}`} className="mt-4 rounded-lg border border-border bg-card px-5 py-5">
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              <span className={cn("rounded-full px-2 py-0.5 font-medium", KINDS[item.kind][1])}>{item.reason}</span>
              <Link to="/c/$cid/read" params={{ cid: String(cid) }} search={{ section: item.section_id, block: item.block.id } as never}
                    className="text-muted-foreground underline decoration-dotted underline-offset-4 hover:text-foreground">
                {blockLabel(item.block).kind} from “{item.section}”</Link>
            </p>
            <div className="prose-cf mt-4"><BlockBody block={item.block} cid={cid} /></div>
          </article>
          <div className="mt-4 flex items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground">{done.has(i) ? "Recorded." : "Answer it, then move on. Skipping leaves it for next time."}</p>
            <Button onClick={() => setI(i + 1)} variant={done.has(i) ? "default" : "outline"}>
              {i === items.length - 1 ? "Finish" : done.has(i) ? "Next" : "Skip"}<ArrowRight className="size-4" /></Button>
          </div>
        </>
      )}
    </div>
  );
}
