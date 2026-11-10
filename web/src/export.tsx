/** The standalone viewer of an exported Course: content, practice and Exams, no server and no model. */
import "@fontsource-variable/source-serif-4";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "./index.css";
import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BlockBody } from "@/components/blocks";
import { Md } from "@/components/md";
import { exported, type ExportedExam } from "@/lib/api";
import { cn } from "@/lib/utils";
import { SheetView } from "./routes/cram";

const { course, chapters, exams } = exported!;
const sections = chapters.flatMap((c) => c.sections.map((s) => ({ ...s, chapter: c })));
type Place = { section: number } | { exam: number } | { sheet: true };

function ExamView({ exam }: { exam: ExportedExam }) {
  return (
    <>
      <p className="text-sm text-muted-foreground">{exam.kind === "mock" ? "Mock exam" : "Past paper"} · {exam.duration_min} min</p>
      <h1 className="mt-1 font-display text-3xl font-semibold tracking-tight">{exam.title}</h1>
      <ol className="prose-cf mt-8 space-y-10">
        {exam.questions.map((q, i) => (
          <li key={q.id}>
            <p className="mb-1 text-sm text-muted-foreground">Question {i + 1} · {q.points} pt</p>
            <Md>{q.statement}</Md>
            <details className="mt-3 rounded-md border border-border/80">
              <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground">Model answer</summary>
              <div className="border-t border-border/80 px-3 py-2">
                <Md>{q.model_answer}</Md>
                {!!q.scheme?.length && <ul className="mt-2 text-sm text-muted-foreground">
                  {q.scheme.map((s, k) => <li key={k} className="flex justify-between gap-4"><Md>{s.step}</Md><span className="tabular shrink-0">{s.points} pt</span></li>)}
                </ul>}
              </div>
            </details>
          </li>
        ))}
      </ol>
    </>
  );
}

function Viewer() {
  const [place, setPlace] = useState<Place>(sections.length ? { section: 0 } : { exam: 0 });
  const go = (p: Place) => { setPlace(p); scrollTo({ top: 0 }); };
  const navItem = (p: Place, label: string, active: boolean) => (
    <li key={label + JSON.stringify(p)}>
      <button type="button" onClick={() => go(p)} aria-current={active ? "page" : undefined}
              className={cn("w-full rounded-md px-2 py-1 text-left text-sm text-muted-foreground hover:text-foreground", active && "bg-accent text-foreground")}>{label}</button>
    </li>
  );
  const i = "section" in place ? place.section : -1;
  const current = sections[i];
  return (
    <div className="grid min-h-dvh lg:grid-cols-[16rem_1fr]">
      <nav className="border-b border-border px-3 py-6 lg:border-b-0 lg:border-r" aria-label="Contents">
        <div className="space-y-5 lg:sticky lg:top-6 lg:max-h-[calc(100dvh-3rem)] lg:overflow-y-auto">
          <p className="px-2 font-display text-lg font-semibold">{course.name}</p>
          {chapters.map((c) => (
            <div key={c.id}>
              <p className="px-2 font-display text-sm font-semibold">{c.title}</p>
              <ul className="mt-1">{c.sections.map((s) => { const k = sections.findIndex((x) => x.id === s.id); return navItem({ section: k }, s.title, k === i); })}</ul>
            </div>
          ))}
          {!!exported!.cheatsheet?.items.length && <ul>{navItem({ sheet: true }, "Cheat Sheet", "sheet" in place)}</ul>}
          {!!exams.length && (
            <div>
              <p className="px-2 font-display text-sm font-semibold">Exams</p>
              <ul className="mt-1">{exams.map((e, k) => navItem({ exam: k }, e.title, "exam" in place && place.exam === k))}</ul>
            </div>
          )}
        </div>
      </nav>
      <article className="mx-auto w-full max-w-[44rem] px-5 py-8 sm:px-8">
        {"sheet" in place ? <SheetView sheet={exported!.cheatsheet} cid={0} /> : "exam" in place ? (exams[place.exam] ? <ExamView exam={exams[place.exam]} /> : <p className="text-muted-foreground">This Course is empty.</p>) : current && (
          <>
            <p className="text-sm text-muted-foreground">{current.chapter.title}</p>
            <h1 className="mt-1 font-display text-3xl font-semibold tracking-tight">{current.title}</h1>
            <div className="prose-cf mt-8 space-y-10">
              {current.blocks.map((b) => (
                <section key={b.id}>
                  <BlockBody block={b} cid={0} />
                  {!!b.citations.length && <p className="mt-2 text-xs text-muted-foreground">{b.citations.map((c) => `${c.source} p.${c.page}`).join(" · ")}</p>}
                </section>
              ))}
            </div>
            <div className="mt-14 flex justify-between gap-4 border-t border-border pt-4 text-sm">
              {i > 0 ? <button type="button" onClick={() => go({ section: i - 1 })} className="text-left hover:text-primary">← {sections[i - 1].title}</button> : <span />}
              {i < sections.length - 1 && <button type="button" onClick={() => go({ section: i + 1 })} className="text-right hover:text-primary">{sections[i + 1].title} →</button>}
            </div>
          </>
        )}
      </article>
    </div>
  );
}

document.title = course.name;
createRoot(document.getElementById("root")!).render(
  <StrictMode><QueryClientProvider client={new QueryClient()}><Viewer /></QueryClientProvider></StrictMode>,
);
