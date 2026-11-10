import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, BookOpen, ClipboardList, Cpu, Flame, FolderOpen, Hand, Layers, Loader2, Plus, Timer, TriangleAlert, Trash2, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ApiError, duration, get, send, upload, type CourseSummary, type Gpu } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Heatmap } from "./practice";

export function Page({ title, children, wide }: { title?: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={wide ? "mx-auto max-w-6xl px-4 py-8 sm:px-6" : "mx-auto max-w-3xl px-4 py-8 sm:px-6"}>
      {title && <h1 className="mb-6 font-display text-2xl font-semibold tracking-tight">{title}</h1>}
      {children}
    </div>
  );
}

export const errText = (e: unknown) => (e instanceof ApiError ? (typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail)) : String(e));

function Pairing() {
  const me = useQuery({ queryKey: ["me"], queryFn: () => get<{ id: string; label: string }>("/api/pairing/me") });
  const start = useMutation({ mutationFn: () => send<{ code: string; expires_at: number }>("/api/pairing/start") });
  if (me.data?.id !== "host") return null;
  return (
    <section className="border-t border-border pt-6">
      <h2 className="font-medium">Use it on a tablet</h2>
      <p className="mt-1 text-sm text-muted-foreground">Open this app's address on the tablet, on the same network, then enter the code.</p>
      {start.data ? <p className="mt-3 font-mono text-3xl tracking-[0.3em] tabular">{start.data.code}</p>
        : <Button className="mt-3" variant="outline" onClick={() => start.mutate()}>Show a pairing code</Button>}
    </section>
  );
}

type Stats = { daily_goal: number; today_sessions: number; streak: number; heatmap: Record<string, number> };
type System = { model: string | null; gpu: Gpu | null };

/** What a Course's Run is doing, in a few words, and whether it needs the owner. */
function runLine(r: CourseSummary["run"]): { text: string; needsYou?: boolean; busy?: boolean; bad?: boolean } {
  if (r.status === "failed") return { text: "Stopped. Open it to retry", bad: true };
  if (r.gate === "found") return { text: "Waiting for you: check what was found", needsYou: true };
  if (r.gate === "outline") return { text: "Waiting for you: fix the outline", needsYou: true };
  if (r.gate === "chapter_review") return { text: "Chapters ready for your review", needsYou: true };
  if (r.status === "running" && !r.active) return { text: "Paused: the app restarted. Open it to resume", needsYou: true };
  if (r.status === "running") {
    const eta = r.seconds_left != null ? ` · ${duration(r.seconds_left)} left` : "";
    return { text: (r.pages_read < r.pages_total ? `Reading pages ${r.pages_read} of ${r.pages_total}` : "Generating") + eta, busy: true };
  }
  return { text: r.status === "done" ? "Ready" : "Not started" };
}

/** A Course's colour: hues spread by the golden angle, so neighbouring ids never look alike. */
export const courseHue = (id: number) => Math.round((id * 137.508 + 25) % 360);

export function Cover({ id, name, className }: { id: number; name: string; className?: string }) {
  return (
    <span aria-hidden style={{ "--hue": courseHue(id) } as React.CSSProperties}
          className={cn("cover grid shrink-0 place-items-center rounded-md font-display font-semibold", className)}>
      {name.trim().charAt(0).toUpperCase() || "?"}
    </span>
  );
}

function CourseCard({ c }: { c: CourseSummary }) {
  const line = runLine(c.run);
  const reading = c.run.status === "running" && c.run.pages_read < c.run.pages_total;
  return (
    <Link to="/c/$cid" params={{ cid: String(c.id) }} style={{ "--hue": courseHue(c.id) } as React.CSSProperties}
          className="lift group flex flex-col rounded-lg border border-border bg-card p-5 hover:border-transparent">
      <div className="flex items-start gap-4">
        <Cover id={c.id} name={c.name} className="size-12 text-2xl" />
        <div className="min-w-0 flex-1">
          <h3 className="truncate font-display text-xl font-semibold tracking-tight group-hover:underline group-hover:decoration-1">{c.name}</h3>
          <p className={cn("mt-0.5 flex items-center gap-2 text-sm", line.bad ? "text-destructive" : line.needsYou ? "cover-ink font-medium" : "text-muted-foreground")}>
            {line.busy && <span className="cover size-2 shrink-0 animate-pulse rounded-full" aria-hidden />}
            {line.text}
          </p>
        </div>
      </div>
      <div className="mt-5">
        {reading || !c.chapters_total ? (
          <Progress className="h-1.5" value={(100 * c.run.pages_read) / Math.max(1, c.run.pages_total)} aria-label="Pages read" />
        ) : (
          <ol className="flex gap-1" aria-label={`${c.chapters_published} of ${c.chapters_total} Chapters published`}>
            {Array.from({ length: c.chapters_total }, (_, i) => (
              <li key={i} className={cn("h-1.5 flex-1 rounded-full", i < c.chapters_published ? "cover" : "bg-muted")} />
            ))}
          </ol>
        )}
      </div>
      <dl className="mt-4 grid grid-cols-3 gap-3 text-sm">
        <div><dt className="text-xs text-muted-foreground">Chapters</dt><dd className="tabular font-medium">{c.chapters_published} / {c.chapters_total}</dd></div>
        <div><dt className="text-xs text-muted-foreground">Cards due</dt><dd className="tabular font-medium">{c.cards_due}</dd></div>
        <div><dt className="text-xs text-muted-foreground">Exam</dt>
          <dd className="tabular font-medium">{c.exam_countdown_days == null ? "—" : c.exam_countdown_days < 0 ? "Passed" : c.exam_countdown_days === 0 ? "Today" : `in ${c.exam_countdown_days} d`}</dd></div>
      </dl>
    </Link>
  );
}

/** Walks dropped folders (the drag-and-drop API hands over entries, not files). Keeps each file's path inside the drop. */
async function droppedFiles(items: DataTransferItemList): Promise<File[]> {
  const out: File[] = [];
  const walk = async (entry: FileSystemEntry | null, path: string): Promise<void> => {
    if (!entry) return;
    if (entry.isFile) {
      const f = await new Promise<File>((ok, no) => (entry as FileSystemFileEntry).file(ok, no));
      out.push(new File([f], path + f.name, { type: f.type }));
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      for (;;) {  // readEntries returns at most ~100 entries per call
        const batch = await new Promise<FileSystemEntry[]>((ok, no) => reader.readEntries(ok, no));
        if (!batch.length) break;
        for (const e of batch) await walk(e, `${path}${entry.name}/`);
      }
    }
  };
  await Promise.all([...items].map((i) => walk(i.webkitGetAsEntry(), "")));
  return out;
}

const pathOf = (f: File) => f.webkitRelativePath || f.name;
const mb = (n: number) => `${(n / 1024 / 1024).toFixed(n < 10 * 1024 * 1024 ? 1 : 0)} MB`;

const JUNK = new Set(["__pycache__", "node_modules", "site-packages", "venv"]);  // tooling, not course material

function NewCourse({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [over, setOver] = useState(false);
  const [progress, setProgress] = useState(0);
  const folderInput = useRef<HTMLInputElement>(null), filesInput = useRef<HTMLInputElement>(null);
  const take = (picked: File[]) => {
    const kept = picked.filter((f) => !pathOf(f).split("/").some((part) => part.startsWith(".") || JUNK.has(part)));  // same rule as the server
    setFiles(kept);
    if (!name && kept[0]) setName(pathOf(kept[0]).includes("/") ? pathOf(kept[0]).split("/")[0] : "");
  };
  const create = useMutation({
    mutationFn: () => {
      const body = new FormData();
      body.append("name", name.trim());
      for (const f of files) body.append("files", f, pathOf(f));
      return upload<{ id: number }>("/api/courses/upload", body, setProgress);
    },
    onSuccess: (c) => nav({ to: "/c/$cid", params: { cid: String(c.id) } }),
  });
  const size = files.reduce((n, f) => n + f.size, 0);
  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>New Course</DialogTitle>
          <DialogDescription>Pick the folder with the course's PDFs, notebooks and data. The files are copied; the originals are never touched, and nothing leaves this machine.</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <div
            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)}
            onDrop={async (e) => { e.preventDefault(); setOver(false); take(await droppedFiles(e.dataTransfer.items)); }}
            className={cn("grid place-items-center gap-3 rounded-lg border border-dashed px-4 py-8 text-center transition-colors",
                          over ? "border-primary bg-primary/5" : "border-border")}>
            <FolderOpen className="size-6 text-muted-foreground" aria-hidden />
            {files.length ? (
              <p className="text-sm"><span className="font-medium">{files.length} files</span> · {mb(size)}
                <span className="mt-1 block max-w-xs truncate font-mono text-xs text-muted-foreground">{files.slice(0, 3).map(pathOf).join(", ")}{files.length > 3 ? ", …" : ""}</span></p>
            ) : <p className="text-sm text-muted-foreground">Drop a folder here, or</p>}
            <div className="flex flex-wrap justify-center gap-2">
              <Button type="button" variant={files.length ? "outline" : "default"} onClick={() => folderInput.current?.click()}>Choose a folder</Button>
              <Button type="button" variant="outline" onClick={() => filesInput.current?.click()}>Choose files</Button>
            </div>
            <input ref={folderInput} type="file" className="sr-only" tabIndex={-1} aria-label="Folder"
                   {...{ webkitdirectory: "", directory: "" }} multiple onChange={(e) => take([...(e.target.files ?? [])])} />
            <input ref={filesInput} type="file" className="sr-only" tabIndex={-1} aria-label="Files" multiple
                   accept=".pdf,.ipynb,.csv,.txt,.json,.xlsx,.py" onChange={(e) => take([...(e.target.files ?? [])])} />
          </div>
          <label className="block space-y-1.5 text-sm">
            <span className="font-medium">Name</span>
            <Input placeholder="e.g. Optimisation" value={name} onChange={(e) => setName(e.target.value)} required aria-label="Course name" />
          </label>
          {create.isPending && <div className="space-y-1"><Progress value={progress * 100} /><p className="tabular text-xs text-muted-foreground">Copying {Math.round(progress * 100)}%</p></div>}
          {create.error && <p className="text-sm text-destructive">{errText(create.error)}</p>}
          <DialogFooter>
            <Button type="submit" disabled={!files.length || !name.trim() || create.isPending}>Import {files.length ? `${files.length} files` : ""}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

type Todo = { key: string; to: string; cid: number; icon: LucideIcon; title: string; detail: string; urgent?: boolean; busy?: boolean };

/** What to do next, most pressing first: Runs waiting for the owner, then due Cards, a near exam, reading. */
function todos(courses: CourseSummary[]): Todo[] {
  const out: Todo[] = [];
  for (const c of courses) {
    const line = runLine(c.run);
    if (line.needsYou || line.bad) out.push({ key: `run${c.id}`, to: "/c/$cid", cid: c.id, icon: line.bad ? TriangleAlert : Hand, title: line.text, detail: c.name, urgent: true });
    else if (line.busy) out.push({ key: `run${c.id}`, to: "/c/$cid", cid: c.id, icon: Loader2, title: line.text, detail: c.name, busy: true });
    if (c.cards_due) out.push({ key: `cards${c.id}`, to: "/c/$cid/cards", cid: c.id, icon: Layers, title: `Review ${c.cards_due} Card${c.cards_due === 1 ? "" : "s"}`, detail: c.name });
    if (c.run.status === "done" && c.exam_countdown_days != null && c.exam_countdown_days >= 0 && c.exam_countdown_days <= 30)
      out.push({ key: `exam${c.id}`, to: "/c/$cid/exams", cid: c.id, icon: ClipboardList, title: "Sit a Mock exam", detail: `${c.name} · exam ${c.exam_countdown_days ? `in ${c.exam_countdown_days} days` : "today"}` });
    if (c.chapters_published) out.push({ key: `read${c.id}`, to: "/c/$cid/read", cid: c.id, icon: BookOpen, title: "Keep reading", detail: `${c.name} · ${c.chapters_published} Chapter${c.chapters_published === 1 ? "" : "s"}` });
  }
  const rank = (t: Todo) => (t.urgent ? 0 : t.busy ? 4 : t.key.startsWith("cards") ? 1 : t.key.startsWith("exam") ? 2 : 3);
  return out.sort((a, b) => rank(a) - rank(b)).slice(0, 5);
}

/** The hub's opening line, written from what is going on. */
function Headline({ courses, due }: { courses: CourseSummary[]; due: number }) {
  const exam = courses.filter((c) => c.exam_countdown_days != null && c.exam_countdown_days >= 0)
    .sort((a, b) => a.exam_countdown_days! - b.exam_countdown_days!)[0];
  const waiting = courses.find((c) => runLine(c.run).needsYou);
  if (!courses.length) return <>Turn a folder of course material into something you can <span className="mark">study</span>.</>;
  return (
    <>
      {exam ? <>The {exam.name} exam is <span className="mark whitespace-nowrap">{exam.exam_countdown_days === 0 ? "today" : `in ${exam.exam_countdown_days} day${exam.exam_countdown_days === 1 ? "" : "s"}`}</span>. </>
        : waiting ? <>{waiting.name} is <span className="mark">waiting for you</span>. </> : null}
      {due ? <>{due} Card{due === 1 ? " is" : "s are"} due.</> : exam || waiting ? <>Nothing is due.</> : <>Nothing is due. <span className="mark">Read ahead</span>.</>}
    </>
  );
}

const greeting = (h = new Date().getHours()) => (h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening");

function UpNext({ items }: { items: Todo[] }) {
  if (!items.length) return null;
  return (
    <section aria-labelledby="next-h">
      <h2 id="next-h" className="mb-3 font-display text-lg font-semibold">Up next</h2>
      <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-card">
        {items.map(({ key, to, cid, icon: Icon, title, detail, urgent, busy }) => (
          <li key={key} style={{ "--hue": courseHue(cid) } as React.CSSProperties}>
            <Link to={to} params={{ cid: String(cid) }} className="group flex items-center gap-4 px-4 py-3.5 transition-colors hover:bg-accent/60">
              <span className={cn("grid size-9 shrink-0 place-items-center rounded-md", urgent ? "cover" : "cover-wash cover-ink")}>
                <Icon className={cn("size-[1.1rem]", busy && "animate-spin")} aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{title}</span>
                <span className="block truncate text-sm text-muted-foreground">{detail}</span>
              </span>
              <ArrowRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" aria-hidden />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function StudyPanel({ stats, focusCid }: { stats?: Stats; focusCid?: number }) {
  const minutes = stats ? Object.values(stats.heatmap ?? {}).reduce((n, m) => n + m, 0) : 0;
  return (
    <section aria-labelledby="study-h" className="rounded-lg border border-border bg-card p-5">
      <h2 id="study-h" className="font-display text-lg font-semibold">Your study</h2>
      <div className="mt-4 flex items-end justify-between gap-4">
        <div>
          <p className="text-xs text-muted-foreground">Today</p>
          <p className="tabular mt-1 flex items-center gap-1.5" aria-label={stats ? `${stats.today_sessions} of ${stats.daily_goal} Focus Sessions` : undefined}>
            {stats ? Array.from({ length: stats.daily_goal }, (_, i) => (
              <span key={i} className={cn("size-3.5 rounded-full border", i < stats.today_sessions ? "border-primary bg-primary" : "border-input")} />
            )) : <span className="h-3.5 w-20 animate-pulse rounded bg-muted" />}
          </p>
          <p className="tabular mt-1.5 text-sm">{stats ? `${stats.today_sessions} of ${stats.daily_goal} Focus Sessions` : "…"}</p>
        </div>
        <div className="text-right">
          <p className="text-xs text-muted-foreground">Streak</p>
          <p className="tabular flex items-center justify-end gap-1 font-display text-3xl font-semibold leading-tight">
            <Flame className={cn("size-6", stats?.streak ? "text-warn" : "text-muted-foreground/50")} aria-hidden />{stats?.streak ?? "…"}
          </p>
          <p className="text-sm text-muted-foreground">{stats?.streak === 1 ? "day" : "days"}</p>
        </div>
      </div>
      <div className="mt-5 border-t border-border pt-4">
        {stats ? <Heatmap heat={stats.heatmap ?? {}} weeks={17} /> : <div className="h-[6.5rem] animate-pulse rounded bg-muted" />}
        <p className="tabular mt-2 text-xs text-muted-foreground">{minutes ? `${minutes >= 120 ? `${Math.round(minutes / 60)} h` : `${minutes} min`} studied in 17 weeks` : "Focus Sessions fill this in, one square a day"}</p>
      </div>
      {focusCid != null && (
        <Link to="/c/$cid/focus" params={{ cid: String(focusCid) }} className="mt-4 block">
          <Button variant="outline" className="w-full"><Timer className="size-4" />Start a Focus Session</Button>
        </Link>
      )}
    </section>
  );
}

function Machine({ sys }: { sys?: System }) {
  if (!sys) return null;
  const g = sys.gpu;
  return (
    <footer className="mt-14 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-border pt-4 text-xs text-muted-foreground">
      <span className="flex items-center gap-2"><Cpu className="size-3.5" aria-hidden />{g ? g.name.replace(/^NVIDIA (GeForce )?/, "") : "No NVIDIA GPU seen"}</span>
      {g && <>
        <span className="tabular flex items-center gap-2">Busy
          <span className="h-1 w-16 overflow-hidden rounded-full bg-muted"><span className="block h-full rounded-full bg-primary transition-[width] duration-700" style={{ width: `${g.util}%` }} /></span>{g.util}%</span>
        <span className="tabular flex items-center gap-2">Memory
          <span className="h-1 w-16 overflow-hidden rounded-full bg-muted"><span className="block h-full rounded-full bg-primary/70 transition-[width] duration-700" style={{ width: `${(100 * g.mem_used_mb) / g.mem_total_mb}%` }} /></span>
          {(g.mem_used_mb / 1024).toFixed(1)} of {(g.mem_total_mb / 1024).toFixed(0)} GB</span>
      </>}
      {sys.model && <span className="truncate font-mono">{sys.model}</span>}
    </footer>
  );
}

/** Deletes a Course for good, after the owner confirms. The folder it came from stays untouched. */
export function DeleteCourse({ cid, name, busy }: { cid: number; name: string; busy?: boolean }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const del = useMutation({
    mutationFn: () => send(`/api/courses/${cid}`, undefined, "DELETE"),
    onSuccess: () => { qc.removeQueries({ predicate: (q) => q.queryKey[1] === cid || q.queryKey[1] === String(cid) });
      qc.invalidateQueries({ queryKey: ["courses"] }); nav({ to: "/" }); },
  });
  return (
    <>
      <Button variant="ghost" size="sm" className="text-muted-foreground hover:bg-destructive/10 hover:text-destructive" onClick={() => setOpen(true)}>
        <Trash2 className="size-4" />Delete Course
      </Button>
      <Dialog open={open} onOpenChange={(o) => !del.isPending && setOpen(o)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete {name}?</DialogTitle>
            <DialogDescription>
              Its Chapters, Cards, Exams and your Copies, Labs, tutor conversations and the copied Sources are deleted. This can't be undone.
              The folder you imported from is not touched, and your Focus Sessions still count toward the Streak.
            </DialogDescription>
          </DialogHeader>
          {busy && <p className="text-sm text-warn">The Run is working on this Course right now. Delete it once the Run stops or waits for you.</p>}
          {del.error && <p className="text-sm text-destructive">{errText(del.error)}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={del.isPending}>Keep it</Button>
            <Button variant="destructive" onClick={() => del.mutate()} disabled={del.isPending || busy}>{del.isPending ? "Deleting…" : "Delete Course"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

export function Home() {
  const { data: courses } = useQuery({ queryKey: ["courses"], queryFn: () => get<CourseSummary[]>("/api/courses"), refetchInterval: 5000 });
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: () => get<Stats>("/api/stats") });
  const { data: sys } = useQuery({ queryKey: ["system"], queryFn: () => get<System>("/api/system"), refetchInterval: 5000 });
  const [adding, setAdding] = useState(false);
  const due = courses?.reduce((n, c) => n + c.cards_due, 0) ?? 0;
  const next = courses ? todos(courses) : [];
  const focusCid = courses?.filter((c) => c.chapters_published).sort((a, b) => (a.exam_countdown_days ?? 1e9) - (b.exam_countdown_days ?? 1e9))[0]?.id;
  const today = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  return (
    <Page wide>
      <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-5 pt-4 sm:pt-8">
        <div className="max-w-3xl">
          <h1 className="font-display text-3xl font-semibold leading-[1.15] tracking-tight sm:text-[2.6rem]">
            {courses ? <Headline courses={courses} due={due} /> : <span className="inline-block h-10 w-96 max-w-full animate-pulse rounded bg-muted align-middle" />}
          </h1>
          <p className="mt-3 text-muted-foreground">{greeting()}. It's {today}.</p>
        </div>
        <Button size="lg" onClick={() => setAdding(true)}><Plus className="size-4" />New Course</Button>
      </header>

      {courses && courses.length > 0 && (
        <div className="mt-10 grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="min-w-0">
            {next.length ? <UpNext items={next} /> : (
              <p className="rounded-lg border border-dashed border-border px-5 py-6 text-muted-foreground">You're all caught up. New Cards come from quiz and exam mistakes.</p>
            )}
          </div>
          <StudyPanel stats={stats} focusCid={focusCid} />
        </div>
      )}

      <section className="mt-12" aria-labelledby="courses-h">
        <h2 id="courses-h" className="mb-3 font-display text-lg font-semibold">Courses</h2>
        {!courses ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{[0, 1].map((i) => <div key={i} className="h-44 animate-pulse rounded-lg bg-muted" />)}</div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {courses.map((c) => <CourseCard key={c.id} c={c} />)}
            <button type="button" onClick={() => setAdding(true)}
                    className={cn("group grid place-items-center gap-2 rounded-lg border border-dashed border-input p-5 text-center text-muted-foreground transition-colors hover:border-primary hover:bg-primary/5 hover:text-foreground",
                                  courses.length ? "min-h-44" : "min-h-56 md:col-span-2 xl:col-span-3")}>
              <span className="grid size-12 place-items-center rounded-full border border-dashed border-current transition-transform group-hover:scale-105"><FolderOpen className="size-5" aria-hidden /></span>
              <span><span className="block font-medium text-foreground">Import a folder</span>
                <span className="text-sm">PDFs, notebooks and data. Nothing leaves this machine.</span></span>
            </button>
          </div>
        )}
      </section>
      <Machine sys={sys} />
      <NewCourse open={adding} onOpenChange={setAdding} />
    </Page>
  );
}

export function Settings() {
  const qc = useQueryClient();
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: () => get<Stats>("/api/stats") });
  const goal = useMutation({ mutationFn: (daily_goal: number) => send("/api/settings", { daily_goal }, "PUT"), onSuccess: () => qc.invalidateQueries({ queryKey: ["stats"] }) });
  return (
    <Page title="Settings">
      <div className="space-y-8">
        <section>
          <h2 className="font-medium">Daily Goal</h2>
          <p className="mt-1 text-sm text-muted-foreground">Focus Sessions a day that keep the Streak going.</p>
          <div className="mt-3 flex items-center gap-3">
            <Button variant="outline" size="icon" aria-label="Lower the daily goal" disabled={!stats || stats.daily_goal <= 1} onClick={() => stats && goal.mutate(stats.daily_goal - 1)}>−</Button>
            <span className="tabular w-8 text-center font-display text-2xl font-semibold">{stats?.daily_goal ?? "…"}</span>
            <Button variant="outline" size="icon" aria-label="Raise the daily goal" disabled={!stats || stats.daily_goal >= 20} onClick={() => stats && goal.mutate(stats.daily_goal + 1)}>+</Button>
          </div>
        </section>
        <section className="border-t border-border pt-6">
          <h2 className="font-medium">Models</h2>
          <p className="mt-1 text-sm text-muted-foreground">A change applies to the next call of that step, also mid-run. Less thinking is faster.</p>
          <StepModels />
        </section>
        <Pairing />
      </div>
    </Page>
  );
}

type StepModels = { default: string; default_from: Source; steps: { step: string; model: string; from: Source }[] };
type Source = "settings" | "env" | "default";
type Available = { id: string; thinking: boolean }[];
const LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh"];
const STEP_NOTES: Record<string, string> = {
  repair_block: "narrow fixes; low thinking is usually enough", judge_grounding: "checks Blocks against their pages; low is usually enough",
  write_section: "the main cost of a run", read_page: "one call per page",
};
const SOURCES: Record<Source, string> = { settings: "set here", env: "from an env variable", default: "built-in default" };

/** A model and its thinking level, as one "provider/model:level" id; "" is "use the default". */
function ModelPicker({ label, value, inherited, available, onChange }: {
  label: string; value: string; inherited?: string; available: Available; onChange: (model: string) => void;
}) {
  const [typed, setTyped] = useState(value);
  useEffect(() => setTyped(value), [value]);
  const level = LEVELS.find((l) => value.endsWith(`:${l}`));
  const model = level ? value.slice(0, -level.length - 1) : value;
  const thinks = available.find((m) => m.id === model)?.thinking ?? !!level;
  if (!available.length) return (  // the backend can't list its models: type one
    <Input value={typed} onChange={(e) => setTyped(e.target.value)} onBlur={() => typed !== value && onChange(typed.trim())} aria-label={`Model for ${label}`}
           placeholder={inherited ? `default: ${inherited}` : "provider/model:level"} className="h-8 w-72 font-mono text-xs" />
  );
  const ids = [...available.map((m) => m.id), ...(model && !available.some((m) => m.id === model) ? [model] : [])];
  return (
    <div className="flex gap-2">
      <Select value={model || "default"} onValueChange={(v) => onChange(v === "default" ? "" : available.find((m) => m.id === v)?.thinking ? `${v}:${level ?? "medium"}` : v)}>
        <SelectTrigger size="sm" aria-label={`Model for ${label}`} className="w-56 font-mono text-xs"><SelectValue /></SelectTrigger>
        <SelectContent>
          {inherited !== undefined && <SelectItem value="default">Default · {inherited.split("/").pop()}</SelectItem>}
          {ids.map((id) => <SelectItem key={id} value={id} className="font-mono text-xs">{id.split("/").pop()}</SelectItem>)}
        </SelectContent>
      </Select>
      {model && thinks && (
        <Select value={level ?? "medium"} onValueChange={(l) => onChange(`${model}:${l}`)}>
          <SelectTrigger size="sm" aria-label={`Thinking for ${label}`} className="w-28 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>{LEVELS.map((l) => <SelectItem key={l} value={l}>{l}</SelectItem>)}</SelectContent>
        </Select>
      )}
    </div>
  );
}

/** The default model, then each Model step's own model and thinking level; the next call of that step uses it, no restart. */
function StepModels() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["models"], queryFn: () => get<StepModels>("/api/models") });
  const { data: available = [], isFetched } = useQuery({ queryKey: ["models", "available"], queryFn: () => get<Available>("/api/models/available"), staleTime: 60_000 });
  const set = useMutation({ mutationFn: (b: { step: string; model: string }) => send<StepModels>("/api/models", b, "PUT"),
                            onSuccess: (d) => { qc.setQueryData(["models"], d); qc.invalidateQueries({ queryKey: ["system"] }); } });
  if (!data || !isFetched) return <p className="mt-4 text-sm text-muted-foreground">Listing the backend's models…</p>;  // pi takes a few seconds
  return (
    <div className="mt-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border border-border px-3 py-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">Default for all steps</p>
          <p className="text-xs text-muted-foreground">{SOURCES[data.default_from]}</p>
        </div>
        <ModelPicker label="all steps" value={data.default} available={available} onChange={(model) => set.mutate({ step: "default", model })} />
      </div>
      <h3 className="mt-5 text-sm font-medium">Per step</h3>
      <ul className="mt-1 divide-y divide-border">
        {data.steps.map((s) => (
          <li key={s.step} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2">
            <div className="min-w-0 flex-1">
              <p className="text-sm capitalize">{s.step.replaceAll("_", " ")}</p>
              <p className="text-xs text-muted-foreground">{[s.from === "env" && `${s.model} · from an env variable`, STEP_NOTES[s.step]].filter(Boolean).join(" · ")}</p>
            </div>
            <ModelPicker label={s.step.replaceAll("_", " ")} value={s.from === "settings" ? s.model : ""} inherited={data.default} available={available}
                         onChange={(model) => set.mutate({ step: s.step, model })} />
          </li>
        ))}
      </ul>
      {set.error && <p className="mt-2 text-sm text-destructive">{errText(set.error)}</p>}
    </div>
  );
}

export function Pair() {
  const [code, setCode] = useState("");
  const claim = useMutation({ mutationFn: () => send("/api/pairing/claim", { code, label: "Tablet" }), onSuccess: () => location.assign("/") });
  return (
    <Page title="Pair this device">
      <form className="max-w-sm space-y-3" onSubmit={(e) => { e.preventDefault(); claim.mutate(); }}>
        <p className="text-sm text-muted-foreground">On the computer running course-factory, choose “Show a pairing code”, then type it here.</p>
        <Input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
               className="h-14 text-center font-mono text-2xl tracking-[0.4em]" aria-label="Pairing code" />
        {claim.error && <p className="text-sm text-destructive">{errText(claim.error)}</p>}
        <Button type="submit" className="w-full" disabled={code.length !== 6 || claim.isPending}>Pair</Button>
      </form>
    </Page>
  );
}
