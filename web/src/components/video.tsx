import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Loader2, Video as VideoIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { exported, get, send } from "@/lib/api";
import { Md } from "./md";

type State = { state: "ready" | "rendering" | "failed" | "pending" | "invalid"; note: string; narration: string[]; caption: string;
  url: string | null; poster: string | null; captions: string | null; error: string | null };

/** A narrated Video: a poster and its narration as text until Manim has rendered it, then a player with captions. */
export function VideoBlock({ data, cid, block }: { data: { narration: string[]; caption?: string }; cid: number; block: { id: number } }) {
  const qc = useQueryClient();
  const key = ["video", block.id];
  const { data: v } = useQuery({ queryKey: key, enabled: !exported, queryFn: () => get<State>(`/api/courses/${cid}/blocks/${block.id}/video`),
    refetchInterval: (q) => (q.state.data?.state === "rendering" ? 2000 : false) });
  const retry = useMutation({ mutationFn: () => send<State>(`/api/courses/${cid}/blocks/${block.id}/video/retry`, {}), onSuccess: (r) => qc.setQueryData(key, r) });
  const narration = v?.narration ?? data.narration;
  const [cue, setCue] = useState("");
  // the captions are read under the picture, not drawn over it: a slide fills the frame and an overlay would hide its text
  const follow = (t: TextTrack) => { t.mode = "hidden"; t.oncuechange = () => setCue([...(t.activeCues ?? [])].map((c) => (c as VTTCue).text).join(" ")); };
  if (v?.state === "ready" && v.url) return (
    <figure>
      <video controls preload="metadata" poster={v.poster ?? undefined} src={v.url} className="w-full rounded-md border border-border bg-black" aria-label="Video">
        <track kind="captions" default src={v.captions ?? undefined} label="Captions" ref={(el) => { if (el) follow(el.track); }} />
      </video>
      <p className="mt-1 min-h-[2.75rem] text-sm leading-snug" aria-live="polite">{cue}</p>
      {(v.caption || data.caption) && <figcaption className="mt-1 text-sm text-muted-foreground"><Md>{v.caption || data.caption || ""}</Md></figcaption>}
      <details className="mt-2 text-sm"><summary className="cursor-pointer text-muted-foreground">Narration</summary>
        {narration.map((n, i) => <Md key={i}>{n}</Md>)}</details>
    </figure>);
  return (
    <div className="rounded-md border border-border p-3" aria-label="Video, not rendered yet">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        {v?.state === "rendering" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <VideoIcon className="size-4" aria-hidden />}
        <span>{v?.state === "rendering" ? "Rendering this Video in the background. Meanwhile, its narration:" : "Video not rendered yet. Its narration:"}</span>
      </div>
      <div className="mt-2">{narration.map((n, i) => <Md key={i}>{n}</Md>)}</div>
      {v?.note && <p className="mt-2 text-xs text-muted-foreground">{v.note}</p>}
      {v?.state === "failed" && <div className="mt-2 flex items-center gap-2 text-xs text-destructive" role="alert">
        <span>The render failed and is in the Review Queue: {v.error?.split("\n")[0]}</span>
        <Button size="sm" variant="outline" onClick={() => retry.mutate()}>Retry</Button></div>}
    </div>);
}
