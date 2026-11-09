import { useRef, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { ApiError, duration, get, send, upload, type CourseSummary, type Gpu } from "@/lib/api";
import { cn } from "@/lib/utils";

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

type Stats = { daily_goal: number; today_sessions: number; streak: number };
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

function CourseCard({ c }: { c: CourseSummary }) {
  const line = runLine(c.run);
  const reading = c.run.status === "running" && c.run.pages_read < c.run.pages_total;
  return (
    <Link to="/c/$cid" params={{ cid: String(c.id) }}
          className="group flex flex-col rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary/50">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="font-display text-lg font-semibold tracking-tight group-hover:text-primary">{c.name}</h3>
        {c.exam_countdown_days != null && c.exam_countdown_days >= 0 && (
          <span className="tabular shrink-0 text-sm text-muted-foreground">exam in {c.exam_countdown_days} d</span>
        )}
      </div>
      <p className={cn("mt-1 flex items-center gap-2 text-sm", line.bad ? "text-destructive" : line.needsYou ? "text-primary" : "text-muted-foreground")}>
        {line.busy && <span className="size-2 shrink-0 animate-pulse rounded-full bg-primary" aria-hidden />}
        {line.text}
      </p>
      {reading && <Progress className="mt-3 h-1" value={(100 * c.run.pages_read) / Math.max(1, c.run.pages_total)} />}
      <dl className="mt-4 flex gap-6 text-sm">
        <div><dt className="text-muted-foreground">Chapters</dt><dd className="tabular font-medium">{c.chapters_published} / {c.chapters_total} published</dd></div>
        <div><dt className="text-muted-foreground">Cards due</dt><dd className="tabular font-medium">{c.cards_due}</dd></div>
        {c.goal && <div><dt className="text-muted-foreground">Goal</dt><dd className="font-medium capitalize">{c.goal}</dd></div>}
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

function NewCourse({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [over, setOver] = useState(false);
  const [progress, setProgress] = useState(0);
  const folderInput = useRef<HTMLInputElement>(null), filesInput = useRef<HTMLInputElement>(null);
  const take = (picked: File[]) => {
    const kept = picked.filter((f) => !pathOf(f).split("/").some((part) => part.startsWith(".")));  // no hidden files
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

export function Home() {
  const { data: courses } = useQuery({ queryKey: ["courses"], queryFn: () => get<CourseSummary[]>("/api/courses"), refetchInterval: 5000 });
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: () => get<Stats>("/api/stats") });
  const { data: sys } = useQuery({ queryKey: ["system"], queryFn: () => get<System>("/api/system"), refetchInterval: 5000 });
  const [adding, setAdding] = useState(false);
  const due = courses?.reduce((n, c) => n + c.cards_due, 0) ?? 0;
  return (
    <Page wide>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="font-display text-2xl font-semibold tracking-tight">Courses</h1>
        <Button onClick={() => setAdding(true)}><Plus className="size-4" />New Course</Button>
      </div>
      <dl className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-4">
        {([
          ["Today", stats ? `${stats.today_sessions} / ${stats.daily_goal}` : "…", "Focus Sessions"],
          ["Streak", stats ? `${stats.streak}` : "…", stats?.streak === 1 ? "day" : "days"],
          ["Cards due", courses ? String(due) : "…", "across Courses"],
          ["GPU", sys?.gpu ? `${sys.gpu.util}%` : "—", sys?.gpu ? `${(sys.gpu.mem_used_mb / 1024).toFixed(1)} of ${(sys.gpu.mem_total_mb / 1024).toFixed(0)} GB` : "no NVIDIA GPU seen"],
        ] as const).map(([label, value, sub]) => (
          <div key={label} className="bg-card px-4 py-3">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="tabular font-display text-2xl font-semibold">{value}</dd>
            <dd className="truncate text-xs text-muted-foreground">{sub}</dd>
          </div>
        ))}
      </dl>
      {sys?.model && <p className="mt-2 truncate font-mono text-xs text-muted-foreground">Model: {sys.model}</p>}
      <section className="mt-8">
        {!courses ? (
          <div className="grid gap-4 md:grid-cols-2">{[0, 1].map((i) => <div key={i} className="h-36 animate-pulse rounded-lg bg-muted" />)}</div>
        ) : courses.length ? (
          <div className="grid gap-4 md:grid-cols-2">{courses.map((c) => <CourseCard key={c.id} c={c} />)}</div>
        ) : (
          <div className="rounded-lg border border-dashed border-border px-6 py-12 text-center">
            <p className="font-medium">No Course yet</p>
            <p className="mt-1 text-sm text-muted-foreground">Import the folder with a course's PDFs and notebooks to start.</p>
            <Button className="mt-4" onClick={() => setAdding(true)}><Plus className="size-4" />New Course</Button>
          </div>
        )}
      </section>
      <NewCourse open={adding} onOpenChange={setAdding} />
    </Page>
  );
}

export function Settings() {
  const qc = useQueryClient();
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: () => get<Stats>("/api/stats") });
  const { data: sys } = useQuery({ queryKey: ["system"], queryFn: () => get<System>("/api/system") });
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
          <h2 className="font-medium">Model</h2>
          <p className="mt-1 font-mono text-sm">{sys?.model ?? "…"}</p>
          <p className="mt-1 text-sm text-muted-foreground">Set <code className="font-mono">CF_MODEL</code> before starting the app to use another one (for example <code className="font-mono">…:xhigh</code> for more thinking).</p>
        </section>
        <Pairing />
      </div>
    </Page>
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
