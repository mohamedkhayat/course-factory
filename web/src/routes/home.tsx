import { useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, get, send, type Course } from "@/lib/api";

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
    <section className="mt-12 border-t border-border pt-6">
      <h2 className="font-medium">Use it on a tablet</h2>
      <p className="mt-1 text-sm text-muted-foreground">Open this app's address on the tablet, on the same network, then enter the code.</p>
      {start.data ? <p className="mt-3 font-mono text-3xl tracking-[0.3em] tabular">{start.data.code}</p>
        : <Button className="mt-3" variant="outline" onClick={() => start.mutate()}>Show a pairing code</Button>}
    </section>
  );
}

export function Home() {
  const nav = useNavigate();
  const { data: courses = [] } = useQuery({ queryKey: ["courses"], queryFn: () => get<Course[]>("/api/courses") });
  const [name, setName] = useState(""), [folder, setFolder] = useState("");
  const create = useMutation({
    mutationFn: () => send<Course>("/api/courses", { name, folder }),
    onSuccess: (c) => nav({ to: "/c/$cid", params: { cid: String(c.id) } }),
  });
  return (
    <Page title="Courses">
      {courses.length > 0 && (
        <ul className="divide-y divide-border border-y border-border">
          {courses.map((c) => (
            <li key={c.id}>
              <Link to="/c/$cid" params={{ cid: String(c.id) }} className="flex items-baseline justify-between gap-4 py-3 hover:text-primary">
                <span className="font-medium">{c.name}</span>
                <span className="truncate font-mono text-xs text-muted-foreground">{c.folder}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <form className="mt-8 space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
        <h2 className="font-medium">New Course</h2>
        <p className="text-sm text-muted-foreground">Point it at a folder of PDFs and notebooks. Nothing leaves this machine.</p>
        <div className="grid gap-2 sm:grid-cols-[1fr_2fr]">
          <Input placeholder="Name, e.g. Optimisation" value={name} onChange={(e) => setName(e.target.value)} required aria-label="Course name" />
          <Input placeholder="/home/you/uni/optimisation" value={folder} onChange={(e) => setFolder(e.target.value)} required aria-label="Folder" className="font-mono" />
        </div>
        {create.error && <p className="text-sm text-destructive">{errText(create.error)}</p>}
        <Button type="submit" disabled={create.isPending}>Import the folder</Button>
      </form>
      <Pairing />
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
