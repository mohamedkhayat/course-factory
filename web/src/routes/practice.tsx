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

type Mistake = { block_id: number; question: number; prompt: string; options: string[]; chosen: number[]; correct: number[]; explanation: string };

function Mistakes({ cid }: { cid: number }) {
  const { data = [] } = useQuery({ queryKey: ["mistakes", cid], queryFn: () => get<Mistake[]>(`/api/courses/${cid}/mistakes`) });
  if (!data.length) return null;
  return (
    <section className="mt-12">
      <h2 className="mb-3 font-medium">Questions you got wrong</h2>
      <ul className="divide-y divide-border border-y border-border">
        {data.map((m) => (
          <li key={`${m.block_id}-${m.question}`} className="py-4">
            <Md>{m.prompt}</Md>
            <p className="mt-1 text-sm"><span className="text-destructive">You chose: {m.chosen.map((i) => m.options[i]).join(", ")}</span>
              <span className="mx-2 text-muted-foreground">·</span><span className="text-ok">Answer: {m.correct.map((i) => m.options[i]).join(", ")}</span></p>
            <div className="mt-1 text-sm text-muted-foreground"><Md>{m.explanation}</Md></div>
          </li>
        ))}
      </ul>
    </section>
  );
}

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
      {!isLoading && !card && (
        <div className="index-card rounded-sm px-8 pb-10 pt-4">
          <p className="h-9 text-xs leading-9 text-muted-foreground">All caught up</p>
          <p className="mt-6 font-display text-xl">No Card is due.</p>
          <p className="mt-1 leading-[1.75rem] text-muted-foreground">Mistakes in quizzes and exams become Cards, and come back here when they are due.</p>
        </div>
      )}
      {card && (
        <div>
          <div className="index-card relative min-h-64 rounded-sm px-8 pb-8 pt-4 sm:px-10">
            <p className="tabular flex h-9 items-center justify-between text-xs text-muted-foreground">
              <span>{shown ? "Answer" : "Question"}</span><span>{due.length} due</span>
            </p>
            <div className="prose-cf mt-6 leading-[1.75rem]"><Md>{card.front}</Md></div>
            {shown && <div className="prose-cf mt-6 border-t border-dashed border-input pt-6 leading-[1.75rem]"><Md>{card.back}</Md></div>}
          </div>
          <div className="mx-auto h-1.5 w-[97%] rounded-b-sm bg-card shadow-[var(--lift)]" aria-hidden />
          {due.length > 2 && <div className="mx-auto h-1.5 w-[94%] rounded-b-sm bg-card shadow-[var(--lift)]" aria-hidden />}
          <div className="mt-6">
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
      <Mistakes cid={cid} />
    </Page>
  );
}

type Stats = { daily_goal: number; today_sessions: number; streak: number; heatmap: Record<string, number>; exam_countdown_days?: number | null };

export function Heatmap({ heat, weeks = 18 }: { heat: Record<string, number>; weeks?: number }) {
  const days = Array.from({ length: 7 * weeks }, (_, i) => { const d = new Date(); d.setDate(d.getDate() - (7 * weeks - 1 - i)); return d.toLocaleDateString("sv"); });
  const level = (m = 0) => (m === 0 ? "bg-muted" : m < 25 ? "bg-primary/30" : m < 60 ? "bg-primary/60" : "bg-primary");
  return (
    <div className="grid grid-flow-col grid-rows-7 gap-[3px] overflow-x-auto" role="img" aria-label={`Minutes studied per day, last ${weeks} weeks`}>
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
  const active = useRef(0), reported = useRef(0);
  const report = () => { const d = active.current - reported.current; reported.current = active.current;
    return send(`/api/focus/${session!.id}/tick`, { active_seconds: d }).catch(() => {}); }; // the server adds deltas
  useEffect(() => {
    if (!session) return;
    const t = setInterval(() => {
      setNow(Date.now());
      if (session.phase === "work" && document.visibilityState === "visible") active.current += 1;
      if (active.current - reported.current >= 30) report();
      if (Date.now() >= session.endsAt) {
        if (session.phase === "work") setSession({ ...session, phase: "break", endsAt: Date.now() + brk * 60_000 });
        else stop();
      }
    }, 1000);
    return () => clearInterval(t);
  }); // re-armed each render so it sees the latest session
  const start = async () => {
    const s = await send<{ id: number }>("/api/focus", { course_id: cid, work_min: work, break_min: brk });
    active.current = 0; reported.current = 0;
    setSession({ id: s.id, phase: "work", endsAt: Date.now() + work * 60_000 });
  };
  const stop = async () => {
    if (!session) return;
    await report();
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
