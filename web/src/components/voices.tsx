import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { get, send } from "@/lib/api";

export type Voice = {
  id: string; name: string; repo: string; revision: string; licence: string; size_mb: number; custom_code: boolean; languages: string[]; note: string;
  speakers: Record<string, string[]>; speaker: Record<string, string | null>; installed: boolean; selected: boolean; default: boolean;
  install: { state: "running" | "failed"; log: string[] } | null;
};
export type Voices = { voices: Voice[]; selected: string; fallback: Record<string, string>; gpu: boolean;
  reads: Record<string, { voice: string | null; fallback: boolean; sample: string; error?: string }> };

const size = (mb: number) => (mb >= 1000 ? `${(mb / 1000).toFixed(1)} GB` : `${mb} MB`);
const LANGS: Record<string, string> = { en: "English", fr: "French" };

/** Settings: which Voice reads Listen, its speaker per language, a preview, and the explicit Install and Remove. */
export function VoiceSettings() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["voices"], queryFn: () => get<Voices>("/api/voices"),
    refetchInterval: (q) => (q.state.data?.voices.some((v) => v.install?.state === "running") ? 2000 : false) });
  const [confirming, setConfirming] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [playing, setPlaying] = useState("");
  const done = { onSuccess: (r: unknown) => { qc.setQueryData(["voices"], r); setMessage(""); }, onError: (e: Error) => setMessage(e.message) };
  const change = useMutation({ mutationFn: (body: object) => send<Voices>("/api/voices", body, "PUT"), ...done });
  const install = useMutation({ mutationFn: (id: string) => send<Voices>(`/api/voices/${id}/install`, { confirm: true }), ...done });
  const remove = useMutation({ mutationFn: (id: string) => send(`/api/voices/${id}`, undefined, "DELETE").then(() => get<Voices>("/api/voices")), ...done });
  const preview = async (id: string, language: string) => {
    setPlaying(`${id}/${language}`);
    try {
      const r = await fetch(`/api/voices/${id}/preview`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ language }) });
      if (!r.ok) throw new Error((await r.json()).detail);
      await new Audio(URL.createObjectURL(await r.blob())).play();
    } catch (e) { setMessage(String((e as Error).message)); }
    setPlaying("");
  };
  return (
    <section className="border-t border-border pt-6">
      <h2 className="font-medium">Voices</h2>
      <p className="mt-1 text-sm text-muted-foreground">Listen reads a Section aloud with a local Voice, on the CPU. Nothing is downloaded until you install a Voice.</p>
      {message && <p className="mt-2 text-sm text-destructive" role="alert">{message}</p>}
      <ul className="mt-3 space-y-3">
        {data?.voices.map((v) => (
          <li key={v.id} className="rounded-md border border-border p-3" aria-label={`Voice ${v.name}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{v.name}</span>
              {v.default && <span className="rounded bg-muted px-1.5 text-xs">default</span>}
              {v.selected && <span className="flex items-center gap-1 rounded bg-primary/10 px-1.5 text-xs text-primary"><Check className="size-3" aria-hidden />reads Listen</span>}
              <span className="text-xs text-muted-foreground">{size(v.size_mb)} · {v.languages.map((l) => LANGS[l] ?? l).join(", ")}</span>
              <div className="ml-auto flex gap-2">
                {v.installed ? <>
                  {!v.selected && <Button size="sm" variant="outline" onClick={() => change.mutate({ voice: v.id })}>Use {v.name}</Button>}
                  <Button size="sm" variant="ghost" onClick={() => remove.mutate(v.id)}>Remove</Button>
                </> : v.install?.state === "running" ? <span className="flex items-center gap-1 text-sm text-muted-foreground"><Loader2 className="size-3.5 animate-spin" aria-hidden />Installing…</span>
                  : confirming === v.id ? <>
                    <span className="self-center text-sm">Download about {size(v.size_mb)}?</span>
                    <Button size="sm" onClick={() => { setConfirming(null); install.mutate(v.id); }}>Download {size(v.size_mb)}</Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>Cancel</Button>
                  </> : <Button size="sm" variant="outline" onClick={() => setConfirming(v.id)}>Install · {size(v.size_mb)}</Button>}
              </div>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">Licence: {v.licence}{v.custom_code ? " · runs the model's own code, reviewed at this revision" : ""}</p>
            <p className="mt-1 text-xs text-muted-foreground">{v.note}</p>
            {v.install?.state === "failed" && <p className="mt-1 text-xs text-destructive" role="alert">Install failed: {v.install.log.at(-1)}</p>}
            {v.installed && <div className="mt-2 flex flex-wrap items-center gap-3">
              {v.languages.map((l) => (
                <div key={l} className="flex items-center gap-2 text-sm">
                  <span className="text-muted-foreground">{LANGS[l] ?? l}</span>
                  {(v.speakers[l]?.length ?? 0) > 1 && (
                    <Select value={v.speaker[l] ?? undefined} onValueChange={(name) => change.mutate({ speakers: { [v.id]: { [l]: name } } })}>
                      <SelectTrigger size="sm" aria-label={`${v.name} speaker for ${LANGS[l] ?? l}`} className="w-32 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>{v.speakers[l].map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}</SelectContent>
                    </Select>)}
                  {v.speakers[l]?.length === 1 && <span className="text-xs">{v.speakers[l][0]}</span>}
                  <Button size="sm" variant="ghost" disabled={playing === `${v.id}/${l}`} aria-label={`Preview ${v.name} in ${LANGS[l] ?? l}`} onClick={() => preview(v.id, l)}>
                    {playing === `${v.id}/${l}` ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Play className="size-3.5" aria-hidden />}Preview
                  </Button>
                </div>))}
            </div>}
          </li>))}
      </ul>
      {data && <ul className="mt-3 space-y-1 text-sm text-muted-foreground">
        {Object.entries(data.reads).map(([l, r]) => (
          <li key={l}>{LANGS[l]}: {r.voice ? <>read by {data.voices.find((v) => v.id === r.voice)?.name}{r.fallback && " (fallback: the chosen Voice does not read it)"}</> : <span className="text-destructive">{r.error}</span>}</li>))}
      </ul>}
      {data && <label className="mt-3 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={data.gpu} onChange={(e) => change.mutate({ gpu: e.target.checked })} />
        Use the GPU for Voices (off: it is shared with the model; Voices installed with the CPU build of torch stay on the CPU)
      </label>}
    </section>
  );
}

type Video = { name: string; version: string; licence: string; size_mb: number; note: string; installed: boolean; install: { state: "running" | "failed"; log: string[] } | null };

/** Settings: video rendering (Manim) is its own environment, installed on an explicit click that shows its size. */
export function VideoSettings() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["video-settings"], queryFn: () => get<Video>("/api/video"), refetchInterval: (q) => (q.state.data?.install?.state === "running" ? 2000 : false) });
  const [confirming, setConfirming] = useState(false);
  const [message, setMessage] = useState("");
  const done = { onSuccess: (r: Video) => { qc.setQueryData(["video-settings"], r); setMessage(""); }, onError: (e: Error) => setMessage(e.message) };
  const install = useMutation({ mutationFn: () => send<Video>("/api/video/install", { confirm: true }), ...done });
  const remove = useMutation({ mutationFn: () => send("/api/video", undefined, "DELETE").then(() => get<Video>("/api/video")), ...done });
  return (
    <section className="border-t border-border pt-6">
      <h2 className="font-medium">Video rendering</h2>
      <p className="mt-1 text-sm text-muted-foreground">Videos are drawn by code from fixed templates and narrated by the chosen Voice, on the CPU, in the background. Nothing is downloaded until you install it.</p>
      {message && <p className="mt-2 text-sm text-destructive" role="alert">{message}</p>}
      {data && <div className="mt-3 rounded-md border border-border p-3" aria-label="Video rendering">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{data.name} {data.version}</span>
          <span className="text-xs text-muted-foreground">{size(data.size_mb)} · {data.licence}</span>
          <div className="ml-auto flex gap-2">
            {data.installed ? <Button size="sm" variant="ghost" onClick={() => remove.mutate()}>Remove</Button>
              : data.install?.state === "running" ? <span className="flex items-center gap-1 text-sm text-muted-foreground"><Loader2 className="size-3.5 animate-spin" aria-hidden />Installing…</span>
                : confirming ? <>
                  <span className="self-center text-sm">Download about {size(data.size_mb)}?</span>
                  <Button size="sm" onClick={() => { setConfirming(false); install.mutate(); }}>Download {size(data.size_mb)}</Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>Cancel</Button>
                </> : <Button size="sm" variant="outline" onClick={() => setConfirming(true)}>Install video rendering · {size(data.size_mb)}</Button>}
          </div>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{data.note}</p>
        {data.install?.state === "failed" && <p className="mt-1 text-xs text-destructive" role="alert">Install failed: {data.install.log.at(-1)}</p>}
      </div>}
    </section>
  );
}
