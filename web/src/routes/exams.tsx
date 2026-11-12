import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, Eraser, FileText, PenLine, Upload } from "lucide-react";
import { Md } from "@/components/md";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { get, pageUrl, send } from "@/lib/api";
import { cn } from "@/lib/utils";
import { errText, Page } from "./home";
import { useCid } from "./run";

type ExamItem = { id: number; kind: "past_paper" | "mock"; title: string; duration_min: number; chapters: number[]; cohort?: string | null; in_scope?: boolean };
type Question = { id: number; position: number; statement: string; points: number; model_answer?: string; scheme?: { step: string; points: number }[] | null };
type Exam = ExamItem & { total_points: number; questions: Question[] };
type Step = { step: string; points: number; awarded: number; comment: string; page: { source: string; page: number } | null };
type Grade = { total: number; max: number; questions: { question_id: number; position: number; points: number; awarded: number; scheme_derived: boolean; answer: string; files: number[]; steps: Step[] }[] };
type Copy = { id: number; exam_id: number; deadline: string; remaining_seconds: number; answers: Record<string, string>; handed_in_at: string | null; grade: Grade | null; correction?: Exam };

export function Exams() {
  const cid = useCid();
  const nav = useNavigate();
  const { data: exams = [] } = useQuery({ queryKey: ["exams", cid], queryFn: () => get<ExamItem[]>(`/api/courses/${cid}/exams`) });
  const { data: history = [] } = useQuery({ queryKey: ["copies", cid], queryFn: () => get<{ id: number; exam_id: number; exam: string; handed_in_at: string; total: number; max: number }[]>(`/api/courses/${cid}/copies`) });
  const qc = useQueryClient();
  const scope = useMutation({
    mutationFn: (e: ExamItem) => send(`/api/courses/${cid}/exams/${e.id}/scope`, { in_scope: !e.in_scope }, "PUT"),
    onSuccess: () => qc.invalidateQueries(),
  });
  const start = useMutation({
    mutationFn: (eid: number) => send<Copy>(`/api/courses/${cid}/exams/${eid}/copies`),
    onSuccess: (c) => nav({ to: "/c/$cid/exams/$eid", params: { cid: String(cid), eid: String(c.exam_id) }, search: { copy: c.id } as never }),
  });
  const { data: job } = useQuery({
    queryKey: ["job", cid], queryFn: () => get<{ kind?: string; state: string; error?: string }>(`/api/courses/${cid}/job`),
    refetchInterval: (q) => (q.state.data?.state === "running" ? 5000 : false),
  });
  const writing = job?.state === "running";
  const wasWriting = useRef(false);
  useEffect(() => {  // the new Mock exam appears once the job is done
    if (wasWriting.current && !writing) qc.invalidateQueries({ queryKey: ["exams", cid] });
    wasWriting.current = writing;
  }, [writing, cid, qc]);
  const more = useMutation({
    mutationFn: () => send(`/api/courses/${cid}/exams/mock`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", cid] }),
  });
  return (
    <Page title="Exams">
      {!exams.length && <p className="text-muted-foreground">No Exam in this Course yet.</p>}
      <ul className="space-y-3">
        {exams.map((e) => {
          const copies = history.filter((h) => h.exam_id === e.id);
          const best = copies.reduce<number | null>((m, h) => Math.max(m ?? 0, h.max ? h.total / h.max : 0), null);
          const Icon = e.kind === "mock" ? PenLine : FileText;
          return (
            <li key={e.id} className="flex flex-wrap items-center gap-4 rounded-lg border border-border bg-card px-5 py-4">
              <span className={cn("grid size-10 shrink-0 place-items-center rounded-md", e.kind === "mock" ? "bg-primary/10 text-primary" : "bg-warn/15 text-warn")}>
                <Icon className="size-5" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-medium leading-snug">{e.title}</span>
                <span className="tabular mt-0.5 block text-sm text-muted-foreground">
                  {e.kind === "mock" ? "Mock exam" : "Past paper"}{e.cohort ? ` · year ${e.cohort}` : ""} · {e.duration_min} min{e.chapters.length ? ` · ${e.chapters.length} Chapter${e.chapters.length === 1 ? "" : "s"}` : ""}
                  {best != null && <> · best <span className={cn("font-medium", best >= 0.5 ? "text-ok" : "text-destructive")}>{Math.round(best * 100)}%</span></>}
                </span>
              </span>
              {e.kind === "past_paper" && (
                <span className="flex items-center gap-2">
                  {!e.in_scope && <Badge variant="outline" title="Set for another cohort: practice only, it does not weigh the Course">Another cohort · practice only</Badge>}
                  <Button size="sm" variant="ghost" onClick={() => scope.mutate(e)} disabled={scope.isPending}
                    title="Whether this paper counts toward Exam Weight, Question Types and Exam Likelihood">
                    {e.in_scope ? "Not my exam" : "Count it"}
                  </Button>
                </span>
              )}
              <Button size="sm" variant={copies.length ? "outline" : "default"} onClick={() => start.mutate(e.id)} disabled={start.isPending}>
                {copies.length ? "Sit it again" : "Sit it"}
              </Button>
            </li>
          );
        })}
      </ul>
      {start.error && <p className="mt-2 text-sm text-destructive">{errText(start.error)}</p>}
      <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
        <Button size="sm" variant="outline" onClick={() => more.mutate()} disabled={more.isPending || writing}>
          <PenLine className="size-3.5" aria-hidden />{writing && job?.kind === "write_mock_exam" ? "Writing a Mock exam…" : "Write another Mock exam"}
        </Button>
        {writing && <span className="text-muted-foreground">{job?.kind === "write_mock_exam" ? "about a minute or two" : "the Course is busy with another job"}</span>}
        {job?.state === "failed" && job.kind === "write_mock_exam" && <span className="text-destructive">The last Mock exam failed: {job.error}</span>}
        {more.error && <span className="text-destructive">{errText(more.error)}</span>}
      </div>
      {history.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-2 font-medium">Your Copies</h2>
          <ul className="space-y-1 text-sm">
            {history.map((h) => (
              <li key={h.id}>
                <Link to="/c/$cid/exams/$eid" params={{ cid: String(cid), eid: String(h.exam_id) }} search={{ copy: h.id } as never} className="flex justify-between gap-4 hover:text-primary">
                  <span>{h.exam} <span className="text-muted-foreground">· {new Date(h.handed_in_at).toLocaleDateString()}</span></span>
                  <span className="tabular font-medium">{h.total} / {h.max}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </Page>
  );
}

/** Pen-only ink on a canvas (the palm is ignored); exported as a PNG for grading. */
function InkPad({ onSave }: { onSave: (png: Blob) => void }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [dirty, setDirty] = useState(false);
  const last = useRef<{ x: number; y: number } | null>(null);
  useEffect(() => {
    const c = ref.current!;
    const r = c.getBoundingClientRect();
    c.width = r.width * devicePixelRatio; c.height = r.height * devicePixelRatio;
    const g = c.getContext("2d")!;
    g.scale(devicePixelRatio, devicePixelRatio);
    g.fillStyle = "#fff"; g.fillRect(0, 0, r.width, r.height);
    g.lineCap = "round"; g.lineJoin = "round"; g.strokeStyle = "#111";
  }, []);
  const at = (e: React.PointerEvent) => { const r = ref.current!.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
  const draw = (e: React.PointerEvent) => {
    if (!last.current || (e.pointerType === "touch" && e.width > 20)) return;
    const g = ref.current!.getContext("2d")!, p = at(e);
    g.lineWidth = e.pointerType === "pen" ? 1 + e.pressure * 2.5 : 2;
    g.beginPath(); g.moveTo(last.current.x, last.current.y); g.lineTo(p.x, p.y); g.stroke();
    last.current = p; setDirty(true);
  };
  const clear = () => { const c = ref.current!, g = c.getContext("2d")!; g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height); setDirty(false); };
  return (
    <div className="space-y-2">
      <canvas ref={ref} className="h-80 w-full touch-none rounded-md border border-border bg-white" aria-label="Writing area"
              onPointerDown={(e) => { if (e.pointerType === "touch" && e.width > 20) return; ref.current!.setPointerCapture(e.pointerId); last.current = at(e); }}
              onPointerMove={draw} onPointerUp={() => { last.current = null; }} onPointerCancel={() => { last.current = null; }} />
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={!dirty} onClick={() => ref.current!.toBlob((b) => { if (b) { onSave(b); clear(); } }, "image/png")}><Upload className="size-4" />Add this page</Button>
        <Button size="sm" variant="ghost" onClick={clear}><Eraser className="size-4" />Clear</Button>
      </div>
    </div>
  );
}

function Countdown({ deadline, onZero }: { deadline: string; onZero: () => void }) {
  const [left, setLeft] = useState(() => Math.max(0, (Date.parse(deadline) - Date.now()) / 1000));
  useEffect(() => {
    const t = setInterval(() => {
      const l = Math.max(0, (Date.parse(deadline) - Date.now()) / 1000);
      setLeft(l);
      if (l === 0) { clearInterval(t); onZero(); }
    }, 1000);
    return () => clearInterval(t);
  }, [deadline]); // eslint-disable-line react-hooks/exhaustive-deps
  const m = Math.floor(left / 60), s = Math.floor(left % 60);
  return <span className={cn("tabular font-mono text-lg", left < 300 && "text-destructive")} role="timer" aria-label="Time left">{Math.floor(m / 60)}:{String(m % 60).padStart(2, "0")}:{String(s).padStart(2, "0")}</span>;
}

function Sitting({ cid, exam, copy }: { cid: number; exam: Exam; copy: Copy }) {
  const qc = useQueryClient();
  const [answers, setAnswers] = useState(copy.answers);
  const [saved, setSaved] = useState(true);
  const [files, setFiles] = useState<{ index: number; kind: string; question_id: number | null }[]>([]);
  const [ink, setInk] = useState<number | null>(null);
  const [confirm, setConfirm] = useState(false);
  const base = `/api/courses/${cid}/copies/${copy.id}`;
  useEffect(() => {
    if (saved) return;
    const t = setTimeout(() => send(`${base}/answers`, { answers }, "PUT").then(() => setSaved(true), () => {}), 800);
    return () => clearTimeout(t);
  }, [answers, saved, base]);
  const upload = async (file: Blob, kind: string, qid: number) => {
    const f = new FormData();
    f.append("file", file, kind === "ink" ? "ink.png" : (file as File).name ?? "photo");
    f.append("kind", kind); f.append("question_id", String(qid));
    setFiles((await send<{ files: typeof files }>(`${base}/files`, f)).files);
  };
  const handIn = useMutation({
    mutationFn: async () => { await send(`${base}/answers`, { answers }, "PUT").catch(() => {}); await send(`${base}/hand-in`); return send<Copy>(`${base}/grade`); },
    onSuccess: (c) => qc.setQueryData(["copy", cid, copy.id], c),
  });
  return (
    <div>
      <div className="sticky top-12 z-10 -mx-4 mb-6 flex items-center justify-between gap-3 border-b border-border bg-background/95 px-4 py-2 backdrop-blur">
        <span className="text-sm text-muted-foreground">{saved ? "Saved" : "Saving…"}</span>
        <Countdown deadline={copy.deadline} onZero={() => handIn.mutate()} />
        {confirm ? (
          <span className="flex gap-1"><Button size="sm" variant="destructive" onClick={() => handIn.mutate()} disabled={handIn.isPending}>{handIn.isPending ? "Grading…" : "Hand in now"}</Button><Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>Keep going</Button></span>
        ) : <Button size="sm" onClick={() => setConfirm(true)}>Hand in</Button>}
      </div>
      {handIn.error && <p className="mb-4 text-sm text-destructive">{errText(handIn.error)}</p>}
      <div className="exam-sheet rounded-sm border border-border bg-card px-6 py-8 shadow-sm sm:px-10">
        <header className="mb-8 border-b-2 border-double border-foreground/40 pb-4 text-center">
          <h1 className="font-display text-2xl font-semibold">{exam.title}</h1>
          <p className="mt-1 text-sm text-muted-foreground">Durée : {exam.duration_min} min · <span className="tabular">{exam.total_points}</span> points · Documents non autorisés</p>
        </header>
        <ol className="space-y-10">
          {exam.questions.map((q) => {
            const mine = files.filter((f) => f.question_id === q.id).length;
            return (
              <li key={q.id}>
                <div className="flex items-baseline justify-between gap-4">
                  <h2 className="font-semibold">Question {q.position + 1}</h2>
                  <span className="tabular text-sm text-muted-foreground">({q.points} pts)</span>
                </div>
                <div className="prose-cf mt-2"><Md>{q.statement}</Md></div>
                <Textarea className="mt-3 min-h-32 font-serif" placeholder="Typed answer (LaTeX between $…$ is fine)" aria-label={`Answer to question ${q.position + 1}`}
                          value={answers[q.id] ?? ""} onChange={(e) => { setAnswers({ ...answers, [q.id]: e.target.value }); setSaved(false); }} />
                <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                  <Button size="sm" variant="outline" onClick={() => setInk(ink === q.id ? null : q.id)}><PenLine className="size-4" />Write by hand</Button>
                  <label className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border border-input px-3 text-sm hover:bg-accent">
                    <Camera className="size-4" />Photo or PDF
                    <input type="file" accept="image/*,application/pdf" capture="environment" className="sr-only"
                           onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f, f.type === "application/pdf" ? "pdf" : "photo", q.id); e.target.value = ""; }} />
                  </label>
                  {mine > 0 && <span className="text-muted-foreground">{mine} page{mine > 1 && "s"} attached</span>}
                </div>
                {ink === q.id && <div className="mt-3"><InkPad onSave={(b) => upload(b, "ink", q.id)} /></div>}
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

function Graded({ cid, copy }: { cid: number; copy: Copy }) {
  const g = copy.grade!, qs = new Map(copy.correction?.questions.map((q) => [q.id, q]));
  return (
    <div>
      <div className="mb-8 flex items-baseline justify-between border-b border-foreground/30 pb-3">
        <h1 className="font-display text-2xl font-semibold">{copy.correction?.title}</h1>
        <p className="tabular font-display text-3xl font-semibold">{g.total}<span className="text-lg text-muted-foreground"> / {g.max}</span></p>
      </div>
      <ol className="space-y-12">
        {g.questions.map((r) => {
          const q = qs.get(r.question_id);
          return (
            <li key={r.question_id}>
              <div className="flex items-baseline justify-between"><h2 className="font-semibold">Question {r.position + 1}</h2><span className="tabular">{r.awarded} / {r.points}</span></div>
              {q && <div className="prose-cf mt-1 text-muted-foreground"><Md>{q.statement}</Md></div>}
              {r.files.length > 0 && (
                <div className="mt-3 flex gap-2 overflow-x-auto">
                  {r.files.map((i) => <img key={i} src={`/api/courses/${cid}/copies/${copy.id}/files/${i}`} alt="Your handwritten answer" className="h-48 rounded-md border border-border bg-white" />)}
                </div>
              )}
              {r.answer && <details className="mt-2 text-sm"><summary className="cursor-pointer text-muted-foreground">What was read from your answer</summary><div className="mt-1"><Md>{r.answer}</Md></div></details>}
              <table className="mt-3 w-full text-sm">
                <caption className="mb-1 text-left text-xs text-muted-foreground">Marking scheme{r.scheme_derived && <Badge variant="outline" className="ml-2">derived from the model answer</Badge>}</caption>
                <tbody>
                  {r.steps.map((s, i) => (
                    <tr key={i} className="border-t border-border align-top">
                      <td className="py-2 pr-3"><Md className="[&_p]:my-0">{s.step}</Md><p className="text-muted-foreground">{s.comment}</p>
                        {s.page && <a href={pageUrl(cid, s.page.source, s.page.page)} target="_blank" rel="noreferrer" className="text-xs underline decoration-dotted">Revise: {s.page.source} p.{s.page.page}</a>}</td>
                      <td className={cn("tabular whitespace-nowrap py-2 text-right", s.awarded < s.points ? "text-destructive" : "text-ok")}>{s.awarded} / {s.points}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {q?.model_answer && <details className="mt-3 rounded-md border border-border px-3 py-2"><summary className="cursor-pointer text-sm font-medium">Model answer</summary><div className="prose-cf mt-2"><Md>{q.model_answer}</Md></div></details>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function ExamMode() {
  const cid = useCid();
  const { eid } = useParams({ strict: false }) as { eid: string };
  const copyId = Number(new URLSearchParams(location.search).get("copy"));
  const exam = useQuery({ queryKey: ["exam", cid, eid], queryFn: () => get<Exam>(`/api/courses/${cid}/exams/${eid}`) });
  const copy = useQuery({ queryKey: ["copy", cid, copyId], enabled: !!copyId, queryFn: () => get<Copy>(`/api/courses/${cid}/copies/${copyId}`) });
  if (!exam.data || !copy.data) return <Page><p className="text-muted-foreground">{copy.error ? errText(copy.error) : "Loading…"}</p></Page>;
  return (
    <Page>
      {copy.data.grade ? <Graded cid={cid} copy={copy.data} />
        : copy.data.handed_in_at ? <p>Handed in. Grading…</p>
        : <Sitting cid={cid} exam={exam.data} copy={copy.data} />}
    </Page>
  );
}
