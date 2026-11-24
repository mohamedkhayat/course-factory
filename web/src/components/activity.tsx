import { useState } from "react";
import { BookOpen, ChevronRight, Loader2, PenLine, Search, ShieldCheck, Wrench } from "lucide-react";
import type { Citation } from "@/lib/api";
import { cn } from "@/lib/utils";

export type Activity = { kind: "search" | "read" | "write" | "check" | "fix"; label: string; source?: string; page?: number };
const ICON = { search: Search, read: BookOpen, write: PenLine, check: ShieldCheck, fix: Wrench };

const summary = (steps: Activity[]) => {
  const n = (k: Activity["kind"]) => steps.filter((s) => s.kind === k).length;
  return [n("search") && "Searched", n("read") && `read ${n("read")} page${n("read") > 1 ? "s" : ""}`, n("write") && `wrote ${n("write")} Block${n("write") > 1 ? "s" : ""}`,
    n("check") && "checked", n("fix") && "fixed one"].filter(Boolean).join(" · ") || "Answered";
};

/** What the tutor is doing, on one line while it works (the page reads are links), then folded to a summary that opens the steps. */
export function ActivityLine({ steps, live, onCite }: { steps: Activity[]; live: boolean; onCite?: (c: Citation) => void }) {
  const [open, setOpen] = useState(false);
  if (!steps.length && !live) return null;
  const step = (s: Activity, i: number) => {
    const Icon = ICON[s.kind];
    const link = s.source && s.page && onCite;
    return (
      <li key={i} className="flex items-center gap-1.5">
        {live && i === steps.length - 1 ? <Loader2 className="size-3 animate-spin" aria-hidden /> : <Icon className="size-3" aria-hidden />}
        {link ? <button type="button" className="underline decoration-dotted hover:text-foreground" onClick={() => onCite({ source: s.source!, page: s.page! })}>{s.label}</button> : s.label}
      </li>
    );
  };
  if (live) {
    return <ul className="mb-2 space-y-0.5 text-xs text-muted-foreground" role="status" aria-label="What the tutor is doing">
      {steps.length ? steps.slice(-1).map((s, i) => step(s, steps.length - 1 + i - 0)) : <li className="flex items-center gap-1.5"><Loader2 className="size-3 animate-spin" aria-hidden />Thinking…</li>}</ul>;
  }
  return (
    <div className="mb-2 text-xs text-muted-foreground">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="inline-flex items-center gap-1 hover:text-foreground">
        <ChevronRight className={cn("size-3 transition-transform", open && "rotate-90")} aria-hidden />{summary(steps)}</button>
      {open && <ul className="mt-1 space-y-0.5 pl-4">{steps.map(step)}</ul>}
    </div>
  );
}

/** A Block still being written or checked, as a placeholder of its kind: its JSON is never shown. */
export function BlockPlaceholder({ kind, status }: { kind: string | null; status: "writing" | "checking" }) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-dashed border-border px-4 py-6 text-sm text-muted-foreground" role="status">
      <Loader2 className="size-4 animate-spin" aria-hidden />{(kind ?? "Block").replaceAll("_", " ")} — {status === "writing" ? "writing…" : "checking…"}
    </div>
  );
}
