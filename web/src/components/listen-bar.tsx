import { useEffect, useRef, useState, type PointerEvent } from "react";
import { ChevronDown, ChevronUp, GripHorizontal, Loader2, Pause, Play, RotateCcw, RotateCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { readEvents } from "@/lib/api";
import { cn } from "@/lib/utils";

type Sentence = { n: number; block_id: number | null; start: number; end: number; text: string; language: string };
const SPEEDS = [0.75, 1, 1.25, 1.5, 1.75, 2];
const MARK = ["ring-2", "ring-primary/40", "rounded-md"];
const PLACE = "cf-listen-place";  // where the learner last dragged the widget, per browser
type Place = { x: number; y: number };
const clampTo = (p: Place, el: HTMLElement | null): Place => {
  const w = el?.offsetWidth ?? 320, h = el?.offsetHeight ?? 120;
  return { x: Math.max(8, Math.min(innerWidth - w - 8, p.x)), y: Math.max(8, Math.min(innerHeight - h - 8, p.y)) };
};
const stored = (): Place | null => { try { return JSON.parse(localStorage.getItem(PLACE) ?? "null"); } catch { return null; } };

/** Listen: the Section read aloud, in a small widget the learner drags anywhere. The server streams sentence clips as a background job makes them; one <audio> plays them in
 * turn (so the lock screen's controls work through the Media Session API). The sentence being read is highlighted in the
 * transcript, and its Block in the article. With `block`, it starts at that Block and pauses at its end. */
export function ListenBar({ cid, section, block, next, onNext, onClose }: {
  cid: number; section: { id: number; title: string }; block?: number; next: { id: number; title: string } | null; onNext: () => void; onClose: () => void;
}) {
  const [only, setOnly] = useState(block);  // the Block being listened to alone, until the learner keeps going
  const [blockDone, setBlockDone] = useState(false);
  const [open, setOpen] = useState(false);  // the transcript
  const [place, setPlace] = useState<Place | null>(stored);
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef<{ dx: number; dy: number } | null>(null);
  const [sentences, setSentences] = useState<Sentence[]>([]);
  const [clips, setClips] = useState<Record<number, { url: string; duration: number }>>({});
  const [voice, setVoice] = useState("");
  const [flagged, setFlagged] = useState(0);
  const [cur, setCur] = useState(0);
  const [playing, setPlaying] = useState(true);  // opening Listen is the click that starts it
  const [waiting, setWaiting] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [error, setError] = useState("");
  const [finished, setFinished] = useState(false);
  const audio = useRef<HTMLAudioElement>(null);
  const line = useRef<HTMLLIElement>(null);
  const clip = clips[cur];
  const total = sentences.length;

  useEffect(() => {  // the stream: the script, then a clip as each sentence is spoken
    const abort = new AbortController();
    fetch(`/api/courses/${cid}/sections/${section.id}/listen${block ? `?block=${block}` : ""}`, { method: "POST", signal: abort.signal })
      .then((res) => readEvents(res, (event, d) => {
        if (event === "script") {
          setSentences(d.sentences); setVoice(d.voice); setFlagged(d.flagged.length);
          if (block) setCur(Math.max(0, (d.sentences as Sentence[]).findIndex((x) => x.block_id === block)));
        }
        else if (event === "clip") setClips((c) => ({ ...c, [d.n]: { url: d.url, duration: d.duration } }));
        else if (event === "error") setError(d.message);
      }))
      .catch((e) => { if (!abort.signal.aborted) setError(String(e.message ?? e)); });
    return () => abort.abort();
  }, [cid, section.id, block]);
  useEffect(() => { if (place) setPlace(clampTo(place, box.current)); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {  // the current clip plays when it is there; until then the bar says it is waiting
    const a = audio.current;
    if (!a || !clip) { setWaiting(true); return; }
    setWaiting(false);
    if (a.getAttribute("src") !== clip.url) a.src = clip.url;
    a.playbackRate = speed;
    if (playing) a.play().catch(() => setPlaying(false));
  }, [clip?.url, cur]);
  useEffect(() => { if (audio.current) audio.current.playbackRate = speed; }, [speed]);
  useEffect(() => {  // the transcript follows the reading, and so does the Block in the article
    line.current?.scrollIntoView({ block: "nearest" });
    const id = sentences[cur]?.block_id;
    const el = id ? document.querySelector<HTMLElement>(`[data-block="${id}"]`) : null;
    el?.classList.add(...MARK);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
    return () => el?.classList.remove(...MARK);
  }, [cur, sentences]);

  const jump = (n: number) => { setFinished(false); setBlockDone(false); setCur(Math.max(0, Math.min(total - 1, n))); };
  const skip = (seconds: number) => {  // across the neighbouring clips that are made (listening from a Block, earlier ones may not be yet)
    const a = audio.current;
    if (!a || !clips[cur]) return;
    let n = cur, t = a.currentTime + seconds;
    while (t < 0 && clips[n - 1]) { n--; t += clips[n].duration; }
    while (t > clips[n].duration && clips[n + 1]) { t -= clips[n].duration; n++; }
    t = Math.max(0, Math.min(clips[n].duration, t));
    if (n === cur) a.currentTime = t; else { jump(n); setTimeout(() => { if (audio.current) audio.current.currentTime = t; }, 50); }
  };
  const keepGoing = () => { setOnly(undefined); jump(cur + 1); setPlaying(true); };
  const toggle = () => {
    const a = audio.current;
    if (!a) return;
    if (finished) { jump(0); setPlaying(true); return; }
    if (blockDone) { keepGoing(); return; }
    if (a.paused) { setPlaying(true); a.play().catch(() => setPlaying(false)); } else { a.pause(); setPlaying(false); }
  };
  const ended = () => {
    if (only && sentences[cur + 1]?.block_id !== only) { setPlaying(false); setBlockDone(true); }  // the Block alone is over
    else if (cur < total - 1) setCur(cur + 1); else { setPlaying(false); setFinished(true); }
  };

  useEffect(() => {  // lock-screen and headset controls
    if (!("mediaSession" in navigator)) return;
    const s = navigator.mediaSession;
    s.metadata = new MediaMetadata({ title: section.title, artist: "Listen", album: "course-factory" });
    s.setActionHandler("play", toggle); s.setActionHandler("pause", toggle);
    s.setActionHandler("seekbackward", () => skip(-10)); s.setActionHandler("seekforward", () => skip(10));
    s.setActionHandler("previoustrack", () => jump(cur - 1)); s.setActionHandler("nexttrack", () => jump(cur + 1));
  });
  useEffect(() => () => {
    audio.current?.pause();
    if ("mediaSession" in navigator) { navigator.mediaSession.metadata = null; for (const a of ["play", "pause", "seekbackward", "seekforward", "previoustrack", "nexttrack"] as const) navigator.mediaSession.setActionHandler(a, null); }
  }, []);

  const grab = (e: PointerEvent) => {
    if ((e.target as HTMLElement).closest("button,select")) return;
    const r = box.current!.getBoundingClientRect();
    drag.current = { dx: e.clientX - r.left, dy: e.clientY - r.top };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const move = (e: PointerEvent) => { if (drag.current) setPlace(clampTo({ x: e.clientX - drag.current.dx, y: e.clientY - drag.current.dy }, box.current)); };
  const drop = () => { if (drag.current && place) { try { localStorage.setItem(PLACE, JSON.stringify(place)); } catch { /* private window */ } } drag.current = null; };

  return (
    <div ref={box} role="region" aria-label="Listen" style={place ? { left: place.x, top: place.y } : undefined}
         className={cn("fixed z-30 w-[min(20rem,calc(100vw-1rem))] rounded-lg border border-border bg-card text-sm shadow-xl", !place && "bottom-4 right-4")}>
      <audio ref={audio} onEnded={ended} onPlay={() => setPlaying(true)} onPause={() => { if (!audio.current?.ended) setPlaying(false); }} />
      <div onPointerDown={grab} onPointerMove={move} onPointerUp={drop} onPointerCancel={drop} title="Drag to move"
           className="flex cursor-grab touch-none select-none items-center gap-1 rounded-t-lg border-b border-border bg-muted/50 py-0.5 pl-2 pr-0.5 active:cursor-grabbing">
        <GripHorizontal className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-xs font-medium" title={voice ? `${section.title} · Voice: ${voice}` : section.title}>
          {only ? "This Block · " : ""}{section.title}</span>
        <Button size="icon" variant="ghost" className="size-6" aria-label="Close Listen" onClick={onClose}><X className="size-3.5" /></Button>
      </div>
      <div className="flex items-center gap-0.5 px-1.5 py-1">
        <Button size="icon" variant="ghost" className="size-8" aria-label="Back 10 seconds" onClick={() => skip(-10)}><RotateCcw className="size-4" /></Button>
        <Button size="icon" className="size-8" aria-label={playing ? "Pause" : "Play"} onClick={toggle} disabled={!clip && !finished}>
          {waiting && playing ? <Loader2 className="size-4 animate-spin" /> : playing ? <Pause className="size-4" /> : <Play className="size-4" />}
        </Button>
        <Button size="icon" variant="ghost" className="size-8" aria-label="Forward 10 seconds" onClick={() => skip(10)}><RotateCw className="size-4" /></Button>
        <span className="tabular ml-1 text-xs text-muted-foreground">{total ? `${Math.min(cur + 1, total)}/${total}` : "…"}</span>
        <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="Speed"
                className="ml-auto rounded border border-input bg-background px-1 py-0.5 text-xs">
          {SPEEDS.map((s) => <option key={s} value={s}>{s}x</option>)}
        </select>
        <Button size="icon" variant="ghost" className="size-7" aria-expanded={open} aria-label={open ? "Hide the transcript" : "Show the transcript"}
                onClick={() => setOpen(!open)}>{open ? <ChevronDown className="size-4" /> : <ChevronUp className="size-4" />}</Button>
      </div>
      {(error || flagged > 0 || blockDone || (finished && next)) && <div className="space-y-1 px-2 pb-1.5 text-xs">
        {error && <p className="text-destructive" role="alert">{error}</p>}
        {flagged > 0 && <p className="text-muted-foreground">{flagged} formula{flagged > 1 ? "s" : ""} said as "the formula on screen" (sent to the Review Queue).</p>}
        {blockDone && <p>End of the Block. <Button size="sm" variant="outline" className="h-6 px-2 text-xs" onClick={keepGoing} disabled={cur >= total - 1}>Keep listening</Button></p>}
        {finished && next && <p>End of the Section. <Button size="sm" className="h-6 px-2 text-xs" onClick={onNext}>Next: {next.title}</Button></p>}
      </div>}
      {open && <ol className="max-h-48 overflow-y-auto border-t border-border px-1 py-1" aria-label="Transcript">
        {sentences.map((s, n) => (
          <li key={n} ref={n === cur ? line : undefined} aria-current={n === cur ? "true" : undefined}>
            <button type="button" disabled={!clips[n]} onClick={() => { setOnly(undefined); jump(n); setPlaying(true); }}
                    className={cn("w-full rounded px-1 py-0.5 text-left text-xs", n === cur ? "bg-primary/15 font-medium" : "text-muted-foreground hover:bg-accent disabled:opacity-60")}>{s.text}</button>
          </li>))}
      </ol>}
    </div>
  );
}
