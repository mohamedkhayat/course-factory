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

export const pageUrl = (cid: number | string, source: string, page: number) =>
  `/api/courses/${cid}/sources/${encodeURIComponent(source)}/pages/${page}`;

export type Citation = { source: string; page: number; quote?: string };
export type Block = {
  id: number; position: number; component: string; data: any; citations: Citation[];
  origin: "from_source" | "model_added"; status: "ok" | "flagged"; flags: string[]; fallback_markdown?: string;
};
export type Section = { id: number; title: string; pages: Citation[]; blocks: Block[] };
export type Chapter = { id: number; title: string; priority: string; exam_weight: number; status: string; sections: Section[] };
export type Course = { id: number; name: string; folder: string; goal: string | null; exam_date: string | null; run_error: string | null };
