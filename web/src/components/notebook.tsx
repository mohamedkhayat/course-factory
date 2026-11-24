import { useEffect, useRef, useState } from "react";
import { Excalidraw, exportToBlob, getNonDeletedElements, getSceneVersion } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI, ExcalidrawInitialDataState } from "@excalidraw/excalidraw/types";
import "@excalidraw/excalidraw/index.css";
import { get, send } from "@/lib/api";
import { dataUrl } from "./ink";

/** A picture of the notes for the tutor, or null when the page is empty. */
export type Snapshot = () => Promise<string | null>;

/** The learner's handwritten notes beside a Section: an Excalidraw page (pen pressure, palm rejection once a pen is seen,
 * eraser, lasso, shapes, text). Saved to the Course a moment after each change. Loaded lazily: it is a large bundle.
 * Mount it with key={sectionId}: one instance per Section, so a scene never lands in another Section.
 * shortcut: Excalidraw's text fonts load from its CDN; pen ink needs none. Self-host them if the tablet studies offline. */
export default function Notebook({ cid, sectionId, onSnapshot, onStatus }: {
  cid: number; sectionId: number; onSnapshot: (s: Snapshot | null) => void; onStatus: (s: string) => void }) {
  const url = `/api/courses/${cid}/sections/${sectionId}/notebook`;
  const [initial, setInitial] = useState<ExcalidrawInitialDataState | null>(null);
  const api = useRef<ExcalidrawImperativeAPI | null>(null);
  const saved = useRef(-1), timer = useRef<ReturnType<typeof setTimeout>>(undefined), pending = useRef<(() => void) | null>(null);
  const dark = document.documentElement.dataset.theme === "instrument";

  useEffect(() => {
    let live = true;
    get<{ scene: ExcalidrawInitialDataState | null }>(url).then((r) => {
      if (!live) return;
      saved.current = getSceneVersion((r.scene?.elements ?? []) as never);
      setInitial({ ...r.scene, appState: { currentItemStrokeWidth: 1, currentItemRoughness: 0, ...r.scene?.appState } });
    }).catch((e) => onStatus(`Couldn't open the notes: ${(e as Error).message}`));
    return () => { live = false; pending.current?.(); };  // leaving the Section saves what is not saved yet
  }, [url]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    onSnapshot(async () => {
      const a = api.current; if (!a) return null;
      const elements = getNonDeletedElements(a.getSceneElements());
      if (!elements.length) return null;
      const png = await exportToBlob({ elements, files: a.getFiles(), maxWidthOrHeight: 1600, mimeType: "image/png",
        appState: { exportBackground: true, viewBackgroundColor: "#ffffff", exportWithDarkMode: false } });
      return dataUrl(png);
    });
    return () => onSnapshot(null);
  }, [onSnapshot]);

  const save = () => {
    const a = api.current; if (!a) return;
    const elements = a.getSceneElements(), st = a.getAppState();
    const version = getSceneVersion(elements);
    pending.current = null;
    if (version === saved.current) return;
    onStatus("Saving…");
    const files = a.getFiles(), used = new Set<string>(elements.flatMap((e) => "fileId" in e && e.fileId ? [e.fileId] : []));
    send(url, { scene: { elements, files: Object.fromEntries(Object.entries(files).filter(([k]) => used.has(k))),
      appState: { scrollX: st.scrollX, scrollY: st.scrollY, zoom: st.zoom, currentItemStrokeColor: st.currentItemStrokeColor, currentItemStrokeWidth: st.currentItemStrokeWidth } } }, "PUT")
      .then(() => { saved.current = version; onStatus("Saved"); })
      .catch((e) => onStatus(`Not saved: ${(e as Error).message}`));
  };

  if (!initial) return <p className="p-4 text-sm text-muted-foreground">Opening your notes…</p>;
  return (
    <div className="size-full [&_.excalidraw]:[--ui-font:var(--font-ui)]">
      <Excalidraw initialData={initial} theme={dark ? "dark" : "light"}
        excalidrawAPI={(a) => { api.current = a; setTimeout(() => a.setActiveTool({ type: "freedraw" })); }}
        UIOptions={{ canvasActions: { loadScene: false, saveToActiveFile: false, export: false, toggleTheme: false } }}
        onChange={(elements) => {
          if (getSceneVersion(elements) === saved.current) return;  // a pan or a tool change: nothing to keep
          clearTimeout(timer.current); pending.current = save; timer.current = setTimeout(save, 800);
        }} />
    </div>
  );
}
