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
  }).then((r) => handle<T>(r));

/** Reads a server-sent event stream from a fetch response, calling onEvent for each event. */
export async function readEvents(res: Response, onEvent: (event: string, data: any) => void) {
  if (!res.ok || !res.body) return handle(res);
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
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
  chapter_id: number; chapter: string; section_id: number; section: string };
export type CheatSheet = { items: CheatItem[]; left_out: number; budget_chars: number };
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
  previous?: { component: string; data: any; citations: Citation[]; origin: "from_source" | "model_added"; status: "ok" | "flagged"; flags: string[] } | null;
  cram?: { likelihood: Likelihood | null; types: string[]; questions: { id: number; exam: string; points: number }[]; minutes: number | null };
};
export type Section = { id: number; title: string; pages: Citation[]; blocks: Block[] };
export type Chapter = { id: number; title: string; priority: string; exam_weight: number; status: string; sections: Section[]; profile?: string };
export type Course = { id: number; name: string; folder: string; goal: string | null; exam_date: string | null; run_error: string | null; hours_per_day?: number; auto_resolve?: number };

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
