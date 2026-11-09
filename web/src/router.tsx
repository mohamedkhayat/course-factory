import { createRootRoute, createRoute, createRouter, Link, Outlet, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Moon, Sun } from "lucide-react";
import { useState } from "react";
import { get, type Course } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Home, Pair, Settings } from "./routes/home";
import { Run } from "./routes/run";
import { Reader } from "./routes/reader";
import { Review } from "./routes/review";
import { Exams, ExamMode } from "./routes/exams";
import { Cards, Focus } from "./routes/practice";
import { Labs, LabView } from "./routes/labs";
import { ComponentsPage } from "./routes/components";

function ThemeToggle() {
  const [theme, setTheme] = useState(document.documentElement.dataset.theme ?? "desk");
  const flip = () => {
    const t = theme === "desk" ? "instrument" : "desk";
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("cf-theme", t); } catch { /* storage blocked */ }
    setTheme(t);
  };
  return (
    <button type="button" onClick={flip} className="grid size-8 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label={theme === "desk" ? "Switch to the dark Instrument theme" : "Switch to the light Study desk theme"}>
      {theme === "desk" ? <Moon className="size-4" /> : <Sun className="size-4" />}
    </button>
  );
}

const NAV = [["read", "Read"], ["exams", "Exams"], ["cards", "Cards"], ["labs", "Labs"], ["focus", "Focus"], ["review", "Review"]] as const;

function CourseNav() {
  const { cid } = useParams({ strict: false }) as { cid?: string };
  const { data: course } = useQuery({ queryKey: ["course", cid], enabled: !!cid, queryFn: () => get<Course>(`/api/courses/${cid}`) });
  if (!cid) return null;
  return (
    <>
      <span className="text-border">/</span>
      <Link to="/c/$cid" params={{ cid }} className="truncate font-medium">{course?.name ?? "…"}</Link>
      <nav className="ml-4 flex gap-1 overflow-x-auto">
        {NAV.map(([to, label]) => (
          <Link key={to} to={`/c/$cid/${to}`} params={{ cid }}
                className="rounded-md px-2.5 py-1 text-sm text-muted-foreground hover:text-foreground"
                activeProps={{ className: "bg-accent !text-foreground" }}>{label}</Link>
        ))}
      </nav>
    </>
  );
}

function Shell() {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-30 flex h-12 items-center gap-2 border-b border-border bg-background/95 px-4 backdrop-blur">
        <Link to="/" className="font-display text-[0.95rem] font-semibold tracking-tight">course-factory</Link>
        <CourseNav />
        <span className="ml-auto flex items-center gap-1">
          <Link to="/components" className={cn("rounded-md px-2.5 py-1 text-sm text-muted-foreground hover:text-foreground")}
                activeProps={{ className: "!text-foreground" }}>Components</Link>
          <Link to="/settings" className="rounded-md px-2.5 py-1 text-sm text-muted-foreground hover:text-foreground"
                activeProps={{ className: "!text-foreground" }}>Settings</Link>
          <ThemeToggle />
        </span>
      </header>
      <main className="flex-1"><Outlet /></main>
    </div>
  );
}

const root = createRootRoute({ component: Shell });
const r = <P extends string>(path: P, component: () => React.ReactNode) => createRoute({ getParentRoute: () => root, path, component });

export const router = createRouter({
  routeTree: root.addChildren([
    r("/", Home), r("/pair", Pair), r("/settings", Settings), r("/components", ComponentsPage),
    r("/c/$cid", Run), r("/c/$cid/read", Reader), r("/c/$cid/review", Review),
    r("/c/$cid/exams", Exams), r("/c/$cid/exams/$eid", ExamMode),
    r("/c/$cid/cards", Cards), r("/c/$cid/focus", Focus),
    r("/c/$cid/labs", Labs), r("/c/$cid/labs/$lid", LabView),
  ]),
});

declare module "@tanstack/react-router" { interface Register { router: typeof router } }
