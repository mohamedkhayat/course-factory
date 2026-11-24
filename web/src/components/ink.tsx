import { useEffect, useRef, useState } from "react";
import { getStroke } from "perfect-freehand";
import { Eraser, PenLine, Type, Upload } from "lucide-react";
import { send } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

/** A big finger (a palm resting on the screen) never writes: only a pen, a mouse or a fingertip does. */
const palm = (e: React.PointerEvent) => e.pointerType === "touch" && e.width > 20;

/** A page to write on with a pen (pressure sets the line width) or a finger, saved as a PNG. With onText, "Type it up" turns
 * the writing into text (resolve true to clear the page); with onPause, the page goes out a few seconds after the pen stops. */
export function InkPad({ onSave, label = "Add this page", onText, onPause, className }: {
  onSave: (png: Blob) => void; label?: string; onText?: (png: Blob) => Promise<boolean>; onPause?: (png: Blob) => void; className?: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [dirty, setDirty] = useState(false), [typing, setTyping] = useState(false);
  const last = useRef<{ x: number; y: number } | null>(null), pause = useRef(0);
  useEffect(() => {
    const c = ref.current!;
    const r = c.getBoundingClientRect();
    c.width = r.width * devicePixelRatio; c.height = r.height * devicePixelRatio;
    const g = c.getContext("2d")!;
    g.scale(devicePixelRatio, devicePixelRatio);
    g.fillStyle = "#fff"; g.fillRect(0, 0, r.width, r.height);
    g.lineCap = "round"; g.lineJoin = "round"; g.strokeStyle = "#111";
    return () => clearTimeout(pause.current);
  }, []);
  const png = () => new Promise<Blob | null>((ok) => ref.current!.toBlob(ok, "image/png"));
  const at = (e: React.PointerEvent) => { const r = ref.current!.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
  const draw = (e: React.PointerEvent) => {
    if (!last.current || palm(e)) return;
    const g = ref.current!.getContext("2d")!, p = at(e);
    g.lineWidth = e.pointerType === "pen" ? 1 + e.pressure * 2.5 : 2;
    g.beginPath(); g.moveTo(last.current.x, last.current.y); g.lineTo(p.x, p.y); g.stroke();
    last.current = p; setDirty(true);
  };
  const up = () => {
    if (!last.current) return;
    last.current = null;
    if (onPause) { clearTimeout(pause.current); pause.current = window.setTimeout(async () => { const b = await png(); if (b) onPause(b); }, 3500); }
  };
  const clear = () => { clearTimeout(pause.current); const c = ref.current!, g = c.getContext("2d")!; g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height); setDirty(false); };
  return (
    <div className={cn("space-y-2", className)}>
      <canvas ref={ref} className="h-80 w-full touch-none rounded-md border border-border bg-white" aria-label="Writing area"
              onPointerDown={(e) => { if (palm(e)) return; clearTimeout(pause.current); ref.current!.setPointerCapture(e.pointerId); last.current = at(e); }}
              onPointerMove={draw} onPointerUp={up} onPointerCancel={up} />
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" disabled={!dirty || typing} onClick={async () => { const b = await png(); if (b) { onSave(b); clear(); } }}><Upload className="size-4" />{label}</Button>
        {onText && <Button size="sm" variant="outline" disabled={!dirty || typing} title="The model reads your handwriting into text you can edit, math as LaTeX"
                           onClick={async () => { setTyping(true); try { const b = await png(); if (b && await onText(b)) clear(); } finally { setTyping(false); } }}>
          <Type className="size-4" />{typing ? "Reading…" : "Type it up"}</Button>}
        <Button size="sm" variant="ghost" onClick={clear}><Eraser className="size-4" />Clear</Button>
      </div>
    </div>
  );
}

export const dataUrl = (b: Blob) => new Promise<string>((ok, no) => { const r = new FileReader(); r.onload = () => ok(String(r.result)); r.onerror = no; r.readAsDataURL(b); });

/** The pen button beside a question box: write the question (working, a diagram) by hand. It goes as an image, or, with
 * onText, typed up into the box as Markdown and LaTeX. */
export function WriteButton({ onImage, cid, onText }: { onImage: (dataUrl: string) => void; cid?: number; onText?: (text: string) => void }) {
  const [open, setOpen] = useState(false), [error, setError] = useState("");
  const typeUp = cid !== undefined && onText ? async (b: Blob) => {
    setError("");
    try { onText((await send<{ text: string }>(`/api/courses/${cid}/ink/latex`, { image: await dataUrl(b) })).text); setOpen(false); return true; }
    catch (e) { setError((e as Error).message); return false; }
  } : undefined;
  return <>
    <button type="button" onClick={() => setOpen(true)} title="Write by hand (pen or finger)"
            className="mb-1 rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground">
      <PenLine className="size-4" aria-hidden /><span className="sr-only">Write by hand</span></button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader><DialogTitle>Write by hand</DialogTitle>
          <DialogDescription>Attach the page as an image{typeUp && ", or Type it up into the box as text you can edit"}. Rest your palm on the screen: only the pen writes.</DialogDescription></DialogHeader>
        <InkPad label="Attach this page" onSave={async (b) => { onImage(await dataUrl(b)); setOpen(false); }} onText={typeUp} />
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      </DialogContent>
    </Dialog>
  </>;
}

/** One pen stroke over a Block: points as [x, y, pressure] in units of the Block's width, so the ink scales with the page. */
export type Stroke = { points: number[][]; color: string; size: number; hl?: boolean };
export type Pen = { tool: "pen" | "hl" | "erase" | "ask"; color: string };

function paint(g: CanvasRenderingContext2D, strokes: Stroke[], w: number) {
  for (const s of strokes) {
    const pts = getStroke(s.points.map(([x, y, p]) => [x * w, y * w, p]), {
      size: s.size, thinning: s.hl ? 0 : 0.6, smoothing: 0.5, streamline: 0.4, simulatePressure: s.points.every((p) => p[2] === 0.5) });
    if (!pts.length) continue;
    const path = new Path2D();
    path.moveTo(pts[0][0], pts[0][1]);
    for (const [x, y] of pts.slice(1)) path.lineTo(x, y);
    path.closePath();
    g.globalAlpha = s.hl ? 0.3 : 1; g.fillStyle = s.color; g.fill(path);
  }
  g.globalAlpha = 1;
}

/** The learner's ink over a Block. With a pen tool on, the pen (or a mouse) writes, and a finger still scrolls the page.
 * shortcut: points scale with the Block's width, so ink drifts when the text reflows at another width; anchor to text if that bites. */
export function BlockInk({ strokes, pen, onChange, onAsk }: {
  strokes: Stroke[]; pen: Pen | null; onChange: (s: Stroke[]) => void; onAsk?: (circled: { text: string; image: string | null }) => void;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const live = useRef<Stroke | null>(null), finger = useRef<number | null>(null);
  const now = useRef(strokes); now.current = strokes;  // the resize observer redraws what is there now
  const redraw = () => {
    const c = ref.current; if (!c) return;
    const g = c.getContext("2d")!;
    g.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    g.clearRect(0, 0, c.width, c.height);
    paint(g, live.current ? [...now.current, live.current] : now.current, c.clientWidth);
  };
  useEffect(() => {
    const c = ref.current!;
    const ro = new ResizeObserver(() => { c.width = c.clientWidth * devicePixelRatio; c.height = c.clientHeight * devicePixelRatio; redraw(); });
    ro.observe(c);
    return () => ro.disconnect();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(redraw, [strokes]); // eslint-disable-line react-hooks/exhaustive-deps
  const at = (e: React.PointerEvent) => { const r = ref.current!.getBoundingClientRect(); return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.width, e.pointerType === "pen" ? e.pressure : 0.5]; };
  const erasing = (e: React.PointerEvent) => pen?.tool === "erase" || (e.buttons & 32) !== 0;  // 32: the pen's eraser end or button
  const rub = (e: React.PointerEvent) => {
    const [x, y] = at(e), r = 12 / ref.current!.clientWidth;
    const kept = strokes.filter((s) => !s.points.some(([a, b]) => Math.hypot(a - x, b - y) < r));
    if (kept.length !== strokes.length) onChange(kept);
  };
  return (
    <canvas ref={ref} aria-hidden className={cn("absolute inset-0 z-10 size-full", pen ? "touch-none" : "pointer-events-none", !pen && !strokes.length && "hidden")}
            onPointerDown={(e) => {
              if (!pen || palm(e)) return;
              if (e.pointerType === "touch") { finger.current = e.clientY; return; }  // a finger scrolls; the pen writes
              try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* the pointer already left: the stroke still draws while over the Block */ }
              if (erasing(e)) { rub(e); return; }
              live.current = pen.tool === "ask" ? { points: [at(e)], color: "#7c3aed", size: 2.5 }
                : { points: [at(e)], color: pen.tool === "hl" ? "#facc15" : pen.color, size: pen.tool === "hl" ? 16 : 3.5, ...(pen.tool === "hl" && { hl: true }) };
            }}
            onPointerMove={(e) => {
              if (finger.current !== null) { scrollBy(0, finger.current - e.clientY); finger.current = e.clientY; return; }
              if (!pen || e.buttons === 0) return;
              if (erasing(e)) { rub(e); return; }
              if (live.current) { live.current.points.push(at(e)); redraw(); }
            }}
            onPointerUp={() => {
              finger.current = null;
              const s = live.current; if (!s) return;
              live.current = null;
              if (pen?.tool !== "ask") { onChange([...strokes, s]); return; }
              redraw();  // the lasso goes away; what it went round goes to the tutor
              const c = ref.current!, r = c.getBoundingClientRect(), w = r.width, xs = s.points.map((p) => r.left + p[0] * w), ys = s.points.map((p) => r.top + p[1] * w);
              const box = { left: Math.min(...xs), right: Math.max(...xs), top: Math.min(...ys), bottom: Math.max(...ys) };
              if (box.right - box.left > 6 || box.bottom - box.top > 6) onAsk?.(circled(c.parentElement!, box));
            }}
            onPointerCancel={() => { finger.current = null; live.current = null; redraw(); }} />
  );
}

/** The ink alone, on white, as a PNG data: URL, for the tutor to read. */
export function inkImage(strokes: Stroke[], w: number, h: number): string {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  const g = c.getContext("2d")!;
  g.fillStyle = "#fff"; g.fillRect(0, 0, w, h);
  paint(g, strokes, w);
  return c.toDataURL("image/png");
}

type Box = { left: number; right: number; top: number; bottom: number };
const inside = (r: DOMRect, b: Box) => { const x = r.left + r.width / 2, y = r.top + r.height / 2; return r.width > 0 && x >= b.left && x <= b.right && y >= b.top && y <= b.bottom; };
const meets = (r: DOMRect, b: Box) => r.width > 0 && r.left < b.right && r.right > b.left && r.top < b.bottom && r.bottom > b.top;

/** What a lasso went round inside a Block: its words and formulas (as LaTeX) in reading order, or, when it holds no text, a
 * picture of the figures under it. */
export function circled(root: HTMLElement, b: Box): { text: string; image: string | null } {
  const parts: string[] = [], range = document.createRange();
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, { acceptNode: (n) => {
    if (!(n instanceof Element)) return NodeFilter.FILTER_ACCEPT;
    if (n.matches("button, canvas, textarea, input, .sr-only")) return NodeFilter.FILTER_REJECT;
    if (n.matches(".katex")) {  // a formula: its TeX source, not the glyphs
      const tex = n.querySelector("annotation[encoding='application/x-tex']")?.textContent;
      if (tex && inside(n.getBoundingClientRect(), b)) parts.push(`$${tex.trim()}$`);
      return NodeFilter.FILTER_REJECT;
    }
    return NodeFilter.FILTER_SKIP;
  } });
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const words: string[] = [];
    for (const m of (n.textContent ?? "").matchAll(/\S+/g)) {
      range.setStart(n, m.index!); range.setEnd(n, m.index! + m[0].length);
      if (inside(range.getBoundingClientRect(), b)) words.push(m[0]);
    }
    if (words.length) parts.push(words.join(" "));
  }
  const text = parts.join(" ").replace(/\s+/g, " ").trim().slice(0, 1200);
  if (text) return { text, image: null };
  const figures = [...root.querySelectorAll<HTMLImageElement | HTMLCanvasElement>("img, canvas:not([aria-hidden])")].filter((el) => meets(el.getBoundingClientRect(), b));
  if (!figures.length) return { text: "", image: null };
  const k = 2, c = document.createElement("canvas");
  c.width = (b.right - b.left) * k; c.height = (b.bottom - b.top) * k;
  const g = c.getContext("2d")!;
  g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
  for (const el of figures) { const r = el.getBoundingClientRect(); g.drawImage(el, (r.left - b.left) * k, (r.top - b.top) * k, r.width * k, r.height * k); }
  try { return { text: "", image: c.toDataURL("image/png") }; } catch { return { text: "", image: null }; }  // a cross-origin picture can't be read back
}

/** A page image you can drag a box over (pen, mouse or finger) to ask about that part; the part goes out as a cropped PNG. */
export function CropToAsk({ src, alt, className, onCrop }: { src: string; alt: string; className?: string; onCrop: (dataUrl: string) => void }) {
  const img = useRef<HTMLImageElement>(null);
  const [box, setBox] = useState<number[] | null>(null);  // x0, y0, x1, y1 in the element's CSS pixels
  const at = (e: React.PointerEvent) => { const r = img.current!.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  const crop = ([x0, y0, x1, y1]: number[]) => {
    const el = img.current!, r = el.getBoundingClientRect();
    const s = Math.min(r.width / el.naturalWidth, r.height / el.naturalHeight);  // object-contain: the picture sits centred in the box
    const ox = (r.width - el.naturalWidth * s) / 2, oy = (r.height - el.naturalHeight * s) / 2;
    const sx = Math.max(0, (Math.min(x0, x1) - ox) / s), sy = Math.max(0, (Math.min(y0, y1) - oy) / s);
    const sw = Math.min(el.naturalWidth - sx, Math.abs(x1 - x0) / s), sh = Math.min(el.naturalHeight - sy, Math.abs(y1 - y0) / s);
    if (sw < 8 || sh < 8) return;
    const k = Math.min(1, 1600 / Math.max(sw, sh)), c = document.createElement("canvas");
    c.width = sw * k; c.height = sh * k;
    c.getContext("2d")!.drawImage(el, sx, sy, sw, sh, 0, 0, c.width, c.height);
    onCrop(c.toDataURL("image/png"));
  };
  return (
    <div className="relative touch-none select-none"
         onPointerDown={(e) => { if (palm(e)) return; e.currentTarget.setPointerCapture(e.pointerId); const [x, y] = at(e); setBox([x, y, x, y]); }}
         onPointerMove={(e) => { if (box && e.buttons) { const [x, y] = at(e); setBox([box[0], box[1], x, y]); } }}
         onPointerUp={() => { if (box) crop(box); setBox(null); }} onPointerCancel={() => setBox(null)}>
      <img ref={img} src={src} alt={alt} draggable={false} className={className} />
      {box && <div aria-hidden className="pointer-events-none absolute rounded-sm border-2 border-violet-600 bg-violet-500/10"
                   style={{ left: Math.min(box[0], box[2]), top: Math.min(box[1], box[3]), width: Math.abs(box[2] - box[0]), height: Math.abs(box[3] - box[1]) }} />}
    </div>
  );
}
