import { useEffect, useRef, useState } from "react";
import { BookOpen, Pin, Search, X } from "lucide-react";
import { Popover } from "radix-ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Chapter } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Section id -> kept (true: every answer until removed) or for the next answer only (false). */
export type Ctx = Record<number, boolean>;

function Check({ checked, indeterminate, label, onChange }: { checked: boolean; indeterminate?: boolean; label: string; onChange: () => void }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { if (ref.current) ref.current.indeterminate = !!indeterminate; }, [indeterminate]);
  return <input ref={ref} type="checkbox" checked={checked} onChange={onChange} aria-label={label} className="size-4 shrink-0 cursor-pointer accent-primary" />;
}

/** Pick Chapters (all their Sections) and Sections for the tutor to answer from. */
export function ContextPicker({ chapters, current, ctx, setCtx }: { chapters: Chapter[]; current?: number; ctx: Ctx; setCtx: (c: Ctx) => void }) {
  const [find, setFind] = useState("");
  const f = find.trim().toLowerCase();
  const n = Object.keys(ctx).length;
  const setMany = (ids: number[], on: boolean) => {
    const next = { ...ctx };
    for (const id of ids) { if (on) next[id] ??= false; else delete next[id]; }
    setCtx(next);
  };
  const shown = chapters.map((c) => {
    const all = !f || c.title.toLowerCase().includes(f);
    return { c, secs: c.sections.filter((s) => all || s.title.toLowerCase().includes(f)) };
  }).filter((x) => x.secs.length);
  return (
    <Popover.Root onOpenChange={(o) => !o && setFind("")}>
      <Popover.Trigger className="relative mb-1 rounded-md p-1.5 text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                       aria-label={n ? `Context for the tutor: ${n} Section${n > 1 ? "s" : ""} selected` : "Add Chapters or Sections as context for the tutor"} title="Add Chapters or Sections for the tutor to answer from">
        <BookOpen className="size-4" aria-hidden />
        {n > 0 && <span className="tabular absolute -right-0.5 -top-0.5 grid min-w-4 place-items-center rounded-full bg-primary px-1 text-[10px] leading-4 text-primary-foreground">{n}</span>}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="top" align="start" sideOffset={8} collisionPadding={12} aria-label="Context for the tutor"
                         className="z-50 flex max-h-[min(28rem,var(--radix-popover-content-available-height))] w-[min(22rem,calc(100vw-1.5rem))] flex-col rounded-md border border-border bg-card text-sm shadow-md outline-none">
          <div className="border-b border-border p-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input value={find} onChange={(e) => setFind(e.target.value)} placeholder="Filter Chapters and Sections" aria-label="Filter Chapters and Sections" className="h-8 pl-8" />
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto py-1">
            {shown.length === 0 && <p className="px-3 py-4 text-center text-muted-foreground">Nothing matches “{find}”.</p>}
            {shown.map(({ c, secs }) => {
              const ids = c.sections.map((s) => s.id), on = ids.filter((id) => id in ctx).length;
              return (
                <div key={c.id} role="group" aria-label={c.title} className="py-1">
                  <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 font-medium hover:bg-accent/60">
                    <Check label={`Whole Chapter: ${c.title}`} checked={on === ids.length} indeterminate={on > 0 && on < ids.length} onChange={() => setMany(ids, on < ids.length)} />
                    <span className="min-w-0 flex-1">{c.title}</span>
                    <span className="tabular shrink-0 text-xs font-normal text-muted-foreground">{on ? `${on}/` : ""}{ids.length}</span>
                  </label>
                  {secs.map((s) => (
                    <label key={s.id} className="flex cursor-pointer items-center gap-2 py-1.5 pl-9 pr-3 hover:bg-accent/60">
                      <Check label={s.title} checked={s.id in ctx} onChange={() => setMany([s.id], !(s.id in ctx))} />
                      <span className="min-w-0 flex-1">{s.title}</span>
                      {s.id === current && <span className="shrink-0 rounded bg-primary/10 px-1.5 text-xs text-primary">Open now</span>}
                    </label>))}
                </div>);
            })}
          </div>
          <div className="flex items-center gap-2 border-t border-border p-2">
            <p className="tabular flex-1 pl-1 text-xs text-muted-foreground" aria-live="polite">{n ? `${n} Section${n > 1 ? "s" : ""} selected` : "None selected"}</p>
            {n > 0 && <Button size="sm" variant="ghost" onClick={() => setCtx({})}>Clear</Button>}
            <Popover.Close asChild><Button size="sm">Done</Button></Popover.Close>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

/** One chip per Section, or one per Chapter when all of it is selected. Pinned = every answer; otherwise the next answer only. */
export function ContextChips({ chapters, ctx, setCtx }: { chapters: Chapter[]; ctx: Ctx; setCtx: (c: Ctx) => void }) {
  const chips = chapters.flatMap((c) => {
    const ids = c.sections.map((s) => s.id);
    if (ids.length && ids.every((id) => id in ctx)) return [{ key: `c${c.id}`, label: `Chapter: ${c.title}`, ids }];
    return c.sections.filter((s) => s.id in ctx).map((s) => ({ key: `s${s.id}`, label: s.title, ids: [s.id] }));
  });
  const patch = (ids: number[], v: (id: number) => boolean | undefined) => {
    const next = { ...ctx };
    for (const id of ids) { const k = v(id); if (k === undefined) delete next[id]; else next[id] = k; }
    setCtx(next);
  };
  return <>{chips.map(({ key, label, ids }) => {
    const keep = ids.every((id) => ctx[id]);
    return (
      <li key={key} className="flex max-w-full items-center gap-1 rounded-md border border-border bg-muted/50 py-1 pl-2 pr-1 text-xs">
        <BookOpen className="size-3 shrink-0" aria-hidden /><span className="min-w-0 truncate">{label}</span>
        <button type="button" aria-pressed={keep} aria-label={`${label}: ${keep ? "kept for every answer" : "next answer only"}. Toggle`}
                title={keep ? "Kept: the tutor uses it for every answer until you remove it. Click for next answer only." : "Next answer only: dropped after you send. Click to keep it for every answer."}
                onClick={() => patch(ids, () => !keep)}
                className={cn("flex shrink-0 items-center gap-1 rounded px-1 py-0.5 hover:bg-accent", keep ? "text-primary" : "text-muted-foreground")}>
          <Pin className={cn("size-3", keep && "fill-current")} aria-hidden />{keep ? "Kept" : "Next answer"}</button>
        <button type="button" aria-label={`Remove ${label}`} onClick={() => patch(ids, () => undefined)} className="rounded p-0.5 hover:bg-accent"><X className="size-3" /></button>
      </li>);
  })}</>;
}

/** The labels the question shows for what was selected, as the chips do. */
export function ctxLabels(chapters: Chapter[], ctx: Ctx): string[] {
  return chapters.flatMap((c) => {
    const ids = c.sections.map((s) => s.id);
    return ids.length && ids.every((id) => id in ctx) ? [`Chapter: ${c.title}`] : c.sections.filter((s) => s.id in ctx).map((s) => s.title);
  });
}
