import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, Clapperboard, Download, Loader2, Pause, Play, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { exported, get, send } from "@/lib/api";
import { cn } from "@/lib/utils";

type Job = { id: number; kind: string; label: string; course: number | null; state: "queued" | "running"; done: number; total: number;
  step: string; stoppable: boolean; stopping: boolean; background: boolean };
type Lane = { paused: boolean; jobs: Job[] };
const ICON: Record<string, typeof AudioLines> = { listen: AudioLines, video: Clapperboard, install: Download };
const short = (j: Job) => `${j.kind === "video" ? "Video" : j.kind === "listen" ? "Audio" : j.kind === "install" ? "Install" : "Voice"}${j.total ? ` ${j.done}/${j.total}` : ""}`;

/** The media lane in the header: what audio, Video or install is being made, how far it is, with pause and stop. Hidden when idle. */
export function MediaQueue() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["media"], queryFn: () => get<Lane>("/api/media"), enabled: !exported,
    refetchInterval: (q) => (q.state.data?.jobs.length ? 1500 : 8000) });
  const set = (d: Lane) => qc.setQueryData(["media"], d);
  const pause = useMutation({ mutationFn: (paused: boolean) => send<Lane>("/api/media/pause", { paused }), onSuccess: set });
  const stop = useMutation({ mutationFn: (id: number) => send<Lane>(`/api/media/jobs/${id}/stop`), onSuccess: set });
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  if (!data || (!data.jobs.length && !data.paused)) return null;
  const cur = data.jobs.find((j) => j.state === "running");
  return (
    <div ref={box} className="relative">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} aria-label="Media queue"
              className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground">
        {data.paused ? <Pause className="size-3.5" /> : <Loader2 className="size-3.5 animate-spin" />}
        <span className="tabular hidden sm:inline">{data.paused ? "Paused" : cur ? short(cur) : "Queued"}</span>
        {data.jobs.length > 1 && <span className="tabular rounded-full bg-muted px-1.5">+{data.jobs.length - 1}</span>}
      </button>
      {open && (
        <div role="dialog" aria-label="Media queue" className="absolute right-0 top-9 z-40 w-[min(22rem,calc(100vw-2rem))] rounded-lg border border-border bg-card p-2 text-sm shadow-xl">
          <div className="mb-1 flex items-center gap-2 px-1">
            <span className="mr-auto text-xs text-muted-foreground">{data.paused ? "Paused: jobs wait after their current step" : "Audio and Videos, one at a time"}</span>
            <Button size="sm" variant="outline" className="h-7 gap-1 px-2 text-xs" onClick={() => pause.mutate(!data.paused)} disabled={pause.isPending}>
              {data.paused ? <><Play className="size-3" />Resume</> : <><Pause className="size-3" />Pause</>}</Button>
          </div>
          {!data.jobs.length && <p className="px-1 py-2 text-xs text-muted-foreground">Nothing queued.</p>}
          <ul className="max-h-80 divide-y divide-border overflow-y-auto">
            {data.jobs.map((j) => {
              const Icon = ICON[j.kind] ?? AudioLines;
              return (
                <li key={j.id} className={cn("flex items-start gap-2 px-1 py-2", j.state === "queued" && "opacity-70")}>
                  <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium" title={j.label}>{j.label || j.kind}</p>
                    <p className="tabular text-xs text-muted-foreground">
                      {j.stopping ? "Stopping…" : j.state === "queued" ? (j.background ? "Queued, made ahead" : "Queued")
                        : `${j.step || "Working"}${j.total ? ` · ${j.done} of ${j.total}` : ""}`}</p>
                    {j.state === "running" && j.total > 0 && <Progress value={(100 * j.done) / j.total} className="mt-1 h-1.5" aria-label={`${j.label} progress`} />}
                  </div>
                  {j.stoppable && !j.stopping && (
                    <Button size="icon" variant="ghost" className="size-7 shrink-0" aria-label={`Stop ${j.label}`} title="Stop" onClick={() => stop.mutate(j.id)}>
                      <Square className="size-3.5" /></Button>)}
                </li>);
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
