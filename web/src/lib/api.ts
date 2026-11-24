export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === "string" ? detail : `request failed (${status})`);
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try { detail = (await res.json()).detail; } catch { /* not JSON */ }
    if (res.status === 401 && location.pathname !== "/pair") location.assign("/pair");
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const get = <T,>(path: string) => fetch(path).then((r) => handle<T>(r));

export const send = <T,>(path: string, body?: unknown, method = "POST") =>
  fetch(path, {
    method,
    headers: body === undefined || body instanceof FormData ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
  }).then((r) => handle<T>(r)).then((out) => {
    if (/\/(answers|self-mark|grade|outcome)$/.test(path)) dispatchEvent(new Event("cf-attempt"));  // the reader and Practice refresh results
    return out;
  });

/** Reads a server-sent event stream from a fetch response, calling onEvent for each event. */
export async function readEvents(res: Response, onEvent: (event: string, data: any) => void, signal?: AbortSignal) {
  if (!res.ok || !res.body) return handle(res);
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  signal?.addEventListener("abort", () => reader.cancel(), { once: true });  // some tablet browsers keep reading an aborted body: end it ourselves
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (signal?.aborted) throw new DOMException("stopped", "AbortError");
    if (done) break;
    buf += value;
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const event = /^event: (.*)$/m.exec(chunk)?.[1] ?? "message";
      const data = /^data: (.*)$/m.exec(chunk)?.[1];
      if (data) onEvent(event, JSON.parse(data));
    }
  }
}

/** An exported Course: the data a standalone file carries instead of a server (see export.tsx). */
export type Exported = {
  course: { name: string }; chapters: Chapter[]; exams: ExportedExam[];
  pages: Record<string, string>; components: { name: string; bundle: string }[]; cheatsheet?: CheatSheet;
};
export type Likelihood = "high" | "medium" | "low";
export type CheatItem = { block_id: number; kind: string; title: string; body: string; likelihood: Likelihood | null;
  chapter_id: number | null; chapter: string; section_id: number | null; section: string | null; rows: { command: string; note: string }[] | null };
export type CheatSheet = { items: CheatItem[] };
export type ExportedExam = { id: number; kind: string; title: string; duration_min: number;
  questions: { id: number; statement: string; points: number; model_answer: string; scheme: { step: string; points: number }[] | null }[] };
export const exported: Exported | undefined = (() => {
  const el = document.getElementById("cf-course");
  return el ? JSON.parse(el.textContent!) : undefined;
})();

export const pageUrl = (cid: number | string, source: string, page: number) =>
  exported ? exported.pages[`${source}#${page}`] ?? "" : `/api/courses/${cid}/sources/${encodeURIComponent(source)}/pages/${page}`;

export type Citation = { source: string; page: number; quote?: string };
export type Block = {
  id: number; position: number; component: string; data: any; citations: Citation[];
  origin: "from_source" | "model_added"; status: "ok" | "flagged"; flags: string[]; fallback_markdown?: string;
  exam_types?: string[]; review_queue?: boolean;
  item?: { id: string; label: string };  // client only: the diagram item an attached Block is asked about
  from_chat?: boolean;  // saved from the Course chat
  chat?: { mid: number; part: number };  // a Block still only in a chat answer: practice on it is recorded against Concepts, not the Block
  previous?: { component: string; data: any; citations: Citation[]; origin: "from_source" | "model_added"; status: "ok" | "flagged"; flags: string[] } | null;
  cram?: { likelihood: Likelihood | null; types: string[]; questions: PastQuestion[]; minutes: number | null };
};
/** Where a practice Block's answers go: its own endpoints, or, for a Block that is only in a chat answer, the chat's (recorded against Concepts). */
export const practiceUrl = (cid: number, block: Block, tail: string) =>
  block.chat ? `/api/courses/${cid}/chat/messages/${block.chat.mid}/parts/${block.chat.part}/${tail}` : `/api/courses/${cid}/blocks/${block.id}/${tail}`;

export type Section = { id: number; title: string; pages: Citation[]; blocks: Block[]; teaches?: string[]; objectives?: string[] };
export type Note = { block_id: number; text: string; updated_at: string; component: string; section_id: number; section: string; chapter: string };
export type Confidence = "solid" | "shaky" | "lost";
/** How a practice Block stands: sittings, latest score 0..1, sittings right in a row, the day it is due again. */
export type Standing = { tries: number; last: number; last_at: string; run: number; due: string };
export type PracticeQueue = { counts: Record<"missed" | "weak" | "due" | "new", number>;
  items: { kind: "missed" | "weak" | "due" | "new"; reason: string; section_id: number; section: string; chapter: string; standing: Standing | null; block: Block }[] };
export type Progress = {
  chapters: { id: number; title: string; exam_weight: number;
    sections: { id: number; title: string; read: boolean; confidence: Confidence | null; questions: number; answered: number; correct: number;
      practice: number; tried: number; missed: number }[] }[];
  concepts: { name: string; section_id: number; section: string; chapter: string; chapter_id: number; blocks: number; tried: number; mastery: number | null; chat: number | null }[];
  next: { section_id: number; section: string; chapter: string; reason: string }[];
};
/** A past paper Question, as shown one click from a Block, a Chapter or a Step answer (#29). */
export type PastQuestion = { id: number; exam: string; points: number; statement: string };
export type Chapter = { id: number; title: string; priority: string; exam_weight: number; status: string; sections: Section[]; profile?: string; overview?: string; exam?: PastQuestion[] };
export type Course = { id: number; name: string; folder: string; goal: string | null; exam_date: string | null; run_error: string | null; hours_per_day?: number; auto_resolve?: number; language: "mixed" | "en" | "fr"; subject?: Subject };
/** What the Course is: theoretical gets Step answers when the learner quotes the course (#30). */
export type Subject = "theoretical" | "practical" | "mixed";

export type CourseSummary = Course & {
  run: { status: string; gate: string | null; error: string | null; active: boolean; pages_read: number; pages_total: number; seconds_left?: number | null };
  chapters_total: number; chapters_published: number; cards_due: number; exam_countdown_days: number | null;
};
export type Gpu = { name: string; util: number; mem_used_mb: number; mem_total_mb: number };

export const duration = (s: number) => (s < 90 ? "under 2 min" : s < 5400 ? `about ${Math.round(s / 60)} min` : `about ${(s / 3600).toFixed(1)} h`);

/** Uploads with progress (fetch can't report upload progress). Resolves with the JSON reply. */
export function upload<T>(path: string, body: FormData, onProgress: (fraction: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", path);
    x.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    x.onload = () => {
      let data: any = null;
      try { data = JSON.parse(x.responseText); } catch { /* not JSON */ }
      if (x.status >= 200 && x.status < 300) resolve(data as T);
      else reject(new ApiError(x.status, data?.detail ?? x.statusText));
    };
    x.onerror = () => reject(new Error("the upload failed: is the app still running?"));
    x.send(body);
  });
}

/** The page's id for an answer it streams: the server runs the answer on when the connection drops, and Stop ends it by this id. */
export const answerId = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36);

/** After the connection dropped mid-answer: waits for the server to finish it, and gives its conversation id. */
export async function answerAfterDrop(cid: number, id: string, signal: AbortSignal): Promise<number> {
  for (let i = 0; i < 300; i++) {  // ten minutes
    await new Promise((r) => setTimeout(r, 2000));
    if (signal.aborted) throw new DOMException("stopped", "AbortError");
    let s: { done: boolean; conversation_id: number | null; error: string | null };
    try { s = await get(`/api/courses/${cid}/answers/${id}`); }
    catch (e) { if (e instanceof ApiError) throw e; continue; }  // still no connection: try again
    if (s.error) throw new Error(s.error);
    if (s.done) { if (s.conversation_id != null) return s.conversation_id; throw new Error("The answer didn't finish."); }
  }
  throw new Error("The answer is taking too long. Reload the page later to see it.");
}

/** Tells the server the learner stopped this answer: the model stops and nothing is saved. */
export const stopAnswer = (cid: number, id: string) => { send(`/api/courses/${cid}/answers/${id}/stop`).catch(() => { /* gone already */ }); };

export const DROPPED = "*The connection dropped. The answer is still being written and shows here when it's done…*";
