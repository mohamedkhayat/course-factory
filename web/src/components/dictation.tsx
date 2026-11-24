import { useRef, useState } from "react";
import { Loader2, Mic, Square } from "lucide-react";
import { send } from "@/lib/api";
import { cn } from "@/lib/utils";

/** A mic button: records with MediaRecorder, uploads to the host, and hands the transcript to the input to be edited before sending.
 * The microphone needs a secure context, so over plain HTTP it says how to get one instead of being a dead button. */
export function DictateButton({ cid, onText, className }: { cid: number; onText: (text: string) => void; className?: string }) {
  const [state, setState] = useState<"idle" | "recording" | "working">("idle");
  const [error, setError] = useState("");
  const rec = useRef<MediaRecorder | null>(null);
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia)
    return <span className={cn("text-xs text-muted-foreground", className)} role="note">Dictation needs HTTPS: open the app through tailscale serve</span>;
  const stop = () => rec.current?.stop();
  const start = async () => {
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks: Blob[] = [];
      const r = new MediaRecorder(stream);
      rec.current = r;
      r.ondataavailable = (e) => chunks.push(e.data);
      r.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setState("working");
        try {
          const body = new FormData();
          body.append("audio", new Blob(chunks, { type: r.mimeType || "audio/webm" }), "dictation.webm");
          onText((await send<{ text: string }>(`/api/courses/${cid}/dictate`, body)).text.trim());
        } catch (e) { setError(String((e as Error).message)); }
        setState("idle");
      };
      r.start();
      setState("recording");
    } catch { setError("The microphone is not available: allow it for this site."); }
  };
  return (
    <>
      <button type="button" disabled={state === "working"} onClick={state === "recording" ? stop : start} aria-pressed={state === "recording"}
              aria-label={state === "recording" ? "Stop dictating" : "Dictate"} title={state === "recording" ? "Stop: the text goes into the box" : "Dictate: speak, then edit the text"}
              className={cn("mb-1 rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground", state === "recording" && "bg-destructive/10 text-destructive", className)}>
        {state === "working" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : state === "recording" ? <Square className="size-4 fill-current" aria-hidden /> : <Mic className="size-4" aria-hidden />}
      </button>
      {error && <span className="text-xs text-destructive" role="alert">{error}</span>}
    </>
  );
}

/** What a dictation adds to what is already typed. */
export const appended = (text: string, said: string) => (text.trim() ? text.replace(/\s*$/, " ") : "") + said;
