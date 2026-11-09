import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Md } from "@/components/md";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { get, send } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Page } from "./home";
import { useCid } from "./run";

type Card = { id: number; front: string; back: string; due: string; next_interval_seconds: Record<string, number> };
const RATINGS = ["À revoir", "Difficile", "Bien", "Facile"];
const span = (s: number) => (s < 3600 ? `${Math.max(1, Math.round(s / 60))} min` : s < 86400 ? `${Math.round(s / 3600)} h` : `${Math.round(s / 86400)} j`);

export function Cards() {
  const cid = useCid();
  const qc = useQueryClient();
  const { data: due = [], isLoading } = useQuery({ queryKey: ["cards", cid], queryFn: () => get<Card[]>(`/api/courses/${cid}/cards/due`) });
  const [shown, setShown] = useState(false);
  const rate = useMutation({
    mutationFn: ({ id, rating }: { id: number; rating: string }) => send(`/api/courses/${cid}/cards/${id}/review`, { rating }),
    onSuccess: () => { setShown(false); qc.invalidateQueries({ queryKey: ["cards", cid] }); },
  });
  const card = due[0];
  return (
    <Page title="Cards">
      {!isLoading && !card && <p className="text-muted-foreground">No Card is due. Mistakes in quizzes and exams become Cards.</p>}
      {card && (
        <div>
          <p className="tabular mb-3 text-sm text-muted-foreground">{due.length} due</p>
          <div className="rounded-md border border-border bg-card px-6 py-8">
            <div className="prose-cf"><Md>{card.front}</Md></div>
            {shown && <div className="prose-cf mt-6 border-t border-border pt-6"><Md>{card.back}</Md></div>}
          </div>
          <div className="mt-4">
            {!shown ? <Button onClick={() => setShown(true)}>Show the answer</Button> : (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {RATINGS.map((r) => (
                  <Button key={r} variant={r === "À revoir" ? "outline" : "secondary"} className="h-auto flex-col py-2" disabled={rate.isPending}
                          onClick={() => rate.mutate({ id: card.id, rating: r })}>
                    <span>{r}</span><span className="tabular text-xs text-muted-foreground">{span(card.next_interval_seconds[r])}</span>
                  </Button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </Page>
  );
}

type Stats = { daily_goal: number; today_sessions: number; streak: number; heatmap: Record<string, number>; exam_countdown_days?: number | null };

function Heatmap({ heat }: { heat: Record<string, number> }) {
  const days = Array.from({ length: 7 * 18 }, (_, i) => { const d = new Date(); d.setDate(d.getDate() - (7 * 18 - 1 - i)); return d.toLocaleDateString("sv"); });
  const level = (m = 0) => (m === 0 ? "bg-muted" : m < 25 ? "bg-primary/30" : m < 60 ? "bg-primary/60" : "bg-primary");
  return (
    <div className="grid grid-flow-col grid-rows-7 gap-[3px] overflow-x-auto" role="img" aria-label="Minutes studied per day, last 18 weeks">
      {days.map((d) => <span key={d} title={`${d}: ${heat[d] ?? 0} min`} className={cn("size-3 rounded-[2px]", level(heat[d]))} />)}
    </div>
  );
}

/** Pomodoro timer; only time with the page visible counts as active. */
export function Focus() {
  const cid = useCid();
  const qc = useQueryClient();
  const { data: stats } = useQuery({ queryKey: ["stats", cid], queryFn: () => get<Stats>(`/api/stats?course_id=${cid}`) });
  const [work, setWork] = useState(25), [brk, setBrk] = useState(5);
  const [session, setSession] = useState<{ id: number; endsAt: number; phase: "work" | "break" } | null>(null);
  const [now, setNow] = useState(Date.now());
  const active = useRef(0);
  useEffect(() => {
    if (!session) return;
    const t = setInterval(() => {
      setNow(Date.now());
      if (session.phase === "work" && document.visibilityState === "visible") active.current += 1;
      if (active.current % 30 === 0) send(`/api/focus/${session.id}/tick`, { active_seconds: active.current }).catch(() => {});
      if (Date.now() >= session.endsAt) {
        if (session.phase === "work") setSession({ ...session, phase: "break", endsAt: Date.now() + brk * 60_000 });
        else stop();
      }
    }, 1000);
    return () => clearInterval(t);
  }); // re-armed each render so it sees the latest session
  const start = async () => {
    const s = await send<{ id: number }>("/api/focus", { course_id: cid, work_min: work, break_min: brk });
    active.current = 0;
    setSession({ id: s.id, phase: "work", endsAt: Date.now() + work * 60_000 });
  };
  const stop = async () => {
    if (!session) return;
    await send(`/api/focus/${session.id}/tick`, { active_seconds: active.current }).catch(() => {});
    await send(`/api/focus/${session.id}/end`).catch(() => {});
    setSession(null);
    qc.invalidateQueries({ queryKey: ["stats", cid] });
  };
  const goal = useMutation({ mutationFn: (daily_goal: number) => send("/api/settings", { daily_goal }, "PUT"), onSuccess: () => qc.invalidateQueries({ queryKey: ["stats", cid] }) });
  const left = session ? Math.max(0, Math.round((session.endsAt - now) / 1000)) : work * 60;
  return (
    <Page title="Focus">
      <div className="rounded-md border border-border px-6 py-8 text-center">
        <p className="text-sm text-muted-foreground">{session ? (session.phase === "work" ? "Work" : "Break") : "Ready"}</p>
        <p className="tabular font-mono text-6xl" role="timer">{Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}</p>
        {!session ? (
          <div className="mt-5 flex flex-wrap items-center justify-center gap-3 text-sm">
            <label className="flex items-center gap-2">Work <Input type="number" min={1} max={180} value={work} onChange={(e) => setWork(+e.target.value)} className="w-16" /> min</label>
            <label className="flex items-center gap-2">Break <Input type="number" min={0} max={60} value={brk} onChange={(e) => setBrk(+e.target.value)} className="w-16" /> min</label>
            <Button onClick={start}>Start</Button>
          </div>
        ) : <Button className="mt-5" variant="outline" onClick={stop}>Stop</Button>}
      </div>
      {stats && (
        <dl className="mt-8 grid grid-cols-2 gap-6 sm:grid-cols-3">
          <div><dt className="text-sm text-muted-foreground">Streak</dt><dd className="tabular font-display text-2xl font-semibold">{stats.streak} days</dd></div>
          <div><dt className="text-sm text-muted-foreground">Today</dt><dd className="tabular font-display text-2xl font-semibold">{stats.today_sessions} / {stats.daily_goal}
            <span className="ml-2 inline-flex gap-1 align-middle text-sm font-normal">
              <button type="button" aria-label="Lower the daily goal" className="px-1 text-muted-foreground hover:text-foreground" onClick={() => goal.mutate(Math.max(1, stats.daily_goal - 1))}>−</button>
              <button type="button" aria-label="Raise the daily goal" className="px-1 text-muted-foreground hover:text-foreground" onClick={() => goal.mutate(Math.min(20, stats.daily_goal + 1))}>+</button>
            </span></dd></div>
          {stats.exam_countdown_days != null && <div><dt className="text-sm text-muted-foreground">Exam in</dt><dd className="tabular font-display text-2xl font-semibold">{stats.exam_countdown_days} days</dd></div>}
        </dl>
      )}
      {stats && <div className="mt-8"><Heatmap heat={stats.heatmap} /></div>}
    </Page>
  );
}
