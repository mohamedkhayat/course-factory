import { createContext, useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import { BookOpen, Maximize2, Minimize2, Paperclip, Pause, Play, SkipBack, SkipForward, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Citation } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Md } from "./md";

type Item = { id: string; label: string; explanation: string; cite: Citation; parent?: string | null; layer?: number | null; container?: string | null };
type Step = { caption: string; cite: Citation; highlight: string[]; links: string[][]; move: string[]; add: string[]; remove: string[]; labels: Record<string, string> };
type Data = { kind: string; items: Item[]; order: string[]; links: string[][]; hub: string; spokes: string[]; caption: string; steps?: Step[] };
type Size = { w: number; h: number; lines: string[] };
type Box = Size & { x: number; y: number; holds?: boolean };
type Edge = { a: string; b: string; label?: string; hidden?: boolean };
type Laid = { h: number; boxes: Record<string, Box>; edges: Edge[]; paths: string[]; at: [number, number][]; bands: { y: number; h: number }[]; order: string[] };

/** What a Block's diagram can do in its page: open a source page, and ask the tutor about one item. Without them the card only reads. */
export const DiagramActions = createContext<{ onCite?: (c: Citation) => void; onAsk?: (item: { id: string; label: string }) => void }>({});

const FONT = 14, LH = 18, PX = 12, PY = 8, GAP = 16, ROW = 40, M = 10, MAXBOX = 180, CARD = 288;

/** Wraps a label into lines no wider than `max`, breaking inside a word only when the word alone is too wide. */
function wrap(text: string, max: number, measure: (s: string) => number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    for (let rest = word; rest;) {
      const joined = line ? `${line} ${rest}` : rest;
      if (measure(joined) <= max) { line = joined; break; }
      if (line) { lines.push(line); line = ""; continue; }
      let n = rest.length;
      while (n > 1 && measure(rest.slice(0, n)) > max) n--;
      lines.push(rest.slice(0, n));
      rest = rest.slice(n);
      if (!rest) break;
    }
  }
  return [...lines, line].filter(Boolean);
}

const sizeOf = (label: string, max: number, measure: (s: string) => number): Size => {
  const lines = wrap(label, Math.max(40, max - 2 * PX), measure);
  return { lines, w: Math.ceil(Math.max(...lines.map(measure), 0)) + 2 * PX, h: lines.length * LH + 2 * PY };
};

/** Centred rows of boxes, wrapping at `max`: positions relative to the block, and the block's size. */
function flow(ids: string[], sz: Record<string, Size>, max: number) {
  const rows: string[][] = [[]];
  let used = 0;
  for (const id of ids) {
    if (used && used + GAP + sz[id].w > max) { rows.push([]); used = 0; }
    used += (used ? GAP : 0) + sz[id].w;
    rows.at(-1)!.push(id);
  }
  const width = (r: string[]) => r.reduce((s, id) => s + sz[id].w, 0) + GAP * (r.length - 1);
  const w = Math.max(...rows.map(width));
  const pos: Record<string, [number, number]> = {};
  let y = 0;
  for (const r of rows) {
    const h = Math.max(...r.map((id) => sz[id].h));
    let x = (w - width(r)) / 2;
    for (const id of r) { pos[id] = [x, y + (h - sz[id].h) / 2]; x += sz[id].w + GAP; }
    y += h + ROW;
  }
  return { pos, w, h: y - ROW };
}

const kidsOf = (items: Item[], key: "parent" | "container") => {
  const kids: Record<string, string[]> = Object.fromEntries(items.map((i) => [i.id, []]));
  for (const i of items) if (i[key] && kids[i[key]!]) kids[i[key]!].push(i.id);
  return kids;
};

/** The edges of a kind and the order its items are walked in with the arrow keys. A cycle in bad data is cut by `seen`. */
function structure(d: Data): { order: string[]; edges: Edge[] } {
  const ids = d.items.map((i) => i.id);
  const chain = (order: string[], close = false) => order.slice(0, close ? undefined : -1).map((a, i) => ({ a, b: order[(i + 1) % order.length] }));
  const depthFirst = (key: "parent" | "container") => {
    const kids = kidsOf(d.items, key), seen = new Set<string>(), order: string[] = [];
    const visit = (id: string) => { if (seen.has(id)) return; seen.add(id); order.push(id); kids[id].forEach(visit); };
    d.items.filter((i) => !i[key]).forEach((i) => visit(i.id));
    ids.forEach(visit);
    return { order, edges: order.flatMap((b) => { const a = d.items.find((i) => i.id === b)![key]; return a ? [{ a, b, hidden: key === "container" }] : []; }) };
  };
  switch (d.kind) {
    case "tree": return depthFirst("parent");
    case "nesting": return depthFirst("container");
    case "layers": return { order: [...d.items].sort((p, q) => (p.layer ?? 0) - (q.layer ?? 0)).map((i) => i.id), edges: d.links.map(([a, b, label]) => ({ a, b, label })) };
    case "pipeline": return { order: d.order, edges: chain(d.order) };
    case "cycle": return { order: d.order, edges: chain(d.order, true) };
    case "state_machine": return { order: ids, edges: d.links.map(([a, b, label]) => ({ a, b, label })) };
    default: return { order: [d.hub, ...d.spokes], edges: d.spokes.map((b) => ({ a: d.hub, b })) };
  }
}

const cx = (b: Box) => b.x + b.w / 2, cy = (b: Box) => b.y + b.h / 2;

/** A line down (or up) from one box to another, bending half way; side to side when they share a row. */
function elbow(a: Box, b: Box): { d: string; at: [number, number] } {
  if (Math.abs(cy(a) - cy(b)) < 4) {
    const [from, to] = a.x < b.x ? [a.x + a.w, b.x] : [a.x, b.x + b.w];
    return { d: `M${from},${cy(a)}L${to},${cy(b)}`, at: [(from + to) / 2, cy(a) - 10] };
  }
  const [from, to] = b.y >= a.y + a.h ? [a.y + a.h, b.y] : [a.y, b.y + b.h], mid = (from + to) / 2;
  return { d: `M${cx(a)},${from}V${mid}H${cx(b)}V${to}`, at: [(cx(a) + cx(b)) / 2, mid - 9] };
}

/** Where the line from a box's centre toward a point leaves the box. */
function edgeOf(b: Box, [tx, ty]: [number, number]): [number, number] {
  const dx = tx - cx(b), dy = ty - cy(b), k = Math.min(b.w / 2 / (Math.abs(dx) || 1e-9), b.h / 2 / (Math.abs(dy) || 1e-9));
  return [cx(b) + dx * k, cy(b) + dy * k];
}

/** A curve between two boxes; the two directions of a pair bend to opposite sides. A link to itself loops over the box. */
function arc(a: Box, b: Box): { d: string; at: [number, number] } {
  if (a === b) return { d: `M${cx(a) - 12},${a.y}C${cx(a) - 34},${a.y - 34} ${cx(a) + 34},${a.y - 34} ${cx(a) + 12},${a.y}`, at: [cx(a), a.y - 30] };
  const mx = (cx(a) + cx(b)) / 2, my = (cy(a) + cy(b)) / 2, len = Math.hypot(cx(b) - cx(a), cy(b) - cy(a));
  const c: [number, number] = [mx - (cy(b) - cy(a)) * 0.18, my + (cx(b) - cx(a)) * 0.18];
  const s = edgeOf(a, c), e = edgeOf(b, c);
  return { d: `M${s[0]},${s[1]}Q${c[0]},${c[1]} ${e[0]},${e[1]}`, at: len ? [0.25 * s[0] + 0.5 * c[0] + 0.25 * e[0], 0.25 * s[1] + 0.5 * c[1] + 0.25 * e[1]] : [mx, my] };
}

const overlap = (a: Box, b: Box) => a.x < b.x + b.w + 10 && b.x < a.x + a.w + 10 && a.y < b.y + b.h + 10 && b.y < a.y + a.h + 10;

/** One deterministic layout per kind, for a drawing `width` wide: every box fits it, labels wrapped by their measured width. */
export function layout(d: Data, width: number, measure: (s: string) => number): Laid {
  const iw = Math.max(120, width - 2 * M), max = Math.min(MAXBOX, iw);
  const { order, edges } = structure(d);
  const sz = Object.fromEntries(d.items.map((i) => [i.id, sizeOf(i.label, max, measure)]));
  const boxes: Record<string, Box> = {};
  const bands: Laid["bands"] = [];
  let h = 0, route = elbow;
  const put = (id: string, x: number, y: number) => { boxes[id] = { ...sz[id], x: M + x, y: M + y }; };
  const centred = (w: number) => (iw - w) / 2;

  if (d.kind === "tree") {
    const kids = kidsOf(d.items, "parent"), root = order[0], span: Record<string, number> = {}, depth: Record<string, number> = {};
    const measureSpan = (id: string, k: number): number => {
      depth[id] = k;
      return span[id] = Math.max(sz[id].w, kids[id].reduce((s, c) => s + measureSpan(c, k + 1), 0) + GAP * Math.max(0, kids[id].length - 1));
    };
    if (measureSpan(root, 0) <= iw) {
      const rowH: number[] = [], rowY: number[] = [];
      for (const id of order) rowH[depth[id]] = Math.max(rowH[depth[id]] ?? 0, sz[id].h);
      rowH.forEach((_, k) => { rowY[k] = k ? rowY[k - 1] + rowH[k - 1] + ROW : 0; });
      const place = (id: string, x0: number) => {
        put(id, x0 + (span[id] - sz[id].w) / 2, rowY[depth[id]] + (rowH[depth[id]] - sz[id].h) / 2);
        let x = x0 + (span[id] - (kids[id].reduce((s, c) => s + span[c], 0) + GAP * Math.max(0, kids[id].length - 1))) / 2;
        for (const c of kids[id]) { place(c, x); x += span[c] + GAP; }
      };
      place(root, centred(span[root]));
      h = rowY.at(-1)! + rowH.at(-1)!;
    } else {  // too wide for this screen: an outline, each level indented
      const step = Math.min(24, (iw - 80) / Math.max(1, Math.max(...Object.values(depth))));
      for (const id of order) {
        sz[id] = sizeOf(d.items.find((i) => i.id === id)!.label, iw - depth[id] * step, measure);
        put(id, depth[id] * step, h);
        h += sz[id].h + GAP;
      }
      h -= GAP;
      route = (a, b) => ({ d: `M${a.x + 14},${a.y + a.h}V${cy(b)}H${b.x}`, at: [b.x, cy(b)] });
    }
  } else if (d.kind === "layers") {
    const levels = [...new Set(d.items.map((i) => i.layer ?? 0))].sort((p, q) => p - q);
    for (const l of levels) {
      const f = flow(d.items.filter((i) => (i.layer ?? 0) === l).map((i) => i.id), sz, iw - 2 * PY);
      for (const [id, [x, y]] of Object.entries(f.pos)) put(id, centred(f.w) + x, h + PY + y);
      bands.push({ y: M + h, h: f.h + 2 * PY });
      h += f.h + 2 * PY + ROW;
    }
    h -= ROW;
  } else if (d.kind === "nesting") {
    const kids = kidsOf(d.items, "container");
    type Nest = { size: Size & { holds: boolean }; inner?: ReturnType<typeof flow>; sub: Record<string, Nest>; head: number };
    const nest = (id: string, maxW: number): Nest => {
      if (!kids[id].length) return { size: { ...sizeOf(d.items.find((i) => i.id === id)!.label, maxW, measure), holds: false }, sub: {}, head: 0 };
      const inner = maxW - 2 * PY, sub = Object.fromEntries(kids[id].map((k) => [k, nest(k, inner)]));
      const head = wrap(d.items.find((i) => i.id === id)!.label, inner - PX, measure);
      const f = flow(kids[id], Object.fromEntries(kids[id].map((k) => [k, sub[k].size])), inner);
      const hh = head.length * LH + PY;
      return { size: { lines: head, w: Math.max(f.w, ...head.map(measure)) + 2 * PY + PX, h: hh + f.h + 2 * PY, holds: true }, inner: f, sub, head: hh };
    };
    const tops = order.filter((id) => !d.items.find((i) => i.id === id)!.container);
    const laid = Object.fromEntries(tops.map((t) => [t, nest(t, iw)]));
    const f = flow(tops, Object.fromEntries(tops.map((t) => [t, laid[t].size])), iw);
    const draw = (id: string, n: Nest, x: number, y: number) => {
      boxes[id] = { ...n.size, x: M + x, y: M + y };
      for (const k of kids[id]) draw(k, n.sub[k], x + PY + (n.size.w - 2 * PY - n.inner!.w) / 2 + n.inner!.pos[k][0], y + n.head + n.inner!.pos[k][1]);
    };
    for (const t of tops) draw(t, laid[t], centred(f.w) + f.pos[t][0], f.pos[t][1]);
    h = f.h;
  } else if (d.kind === "fan_out") {
    const f = flow(d.spokes, sz, iw);
    put(d.hub, centred(sz[d.hub].w), 0);
    for (const [id, [x, y]] of Object.entries(f.pos)) put(id, centred(f.w) + x, sz[d.hub].h + ROW + y);
    h = sz[d.hub].h + ROW + f.h;
  } else if (d.kind === "pipeline") {
    const f = flow(order, sz, iw);
    for (const [id, [x, y]] of Object.entries(f.pos)) put(id, centred(f.w) + x, y);
    h = f.h;
  } else {  // cycle, state_machine: boxes around an ellipse, taller until none touch
    route = arc;
    const ids = order, n = ids.length, wide = Math.max(...ids.map((id) => sz[id].w)), tall = Math.max(...ids.map((id) => sz[id].h));
    const rx = (iw - wide) / 2;
    let ry = rx * 0.6;
    const spot = () => ids.map((id, i) => ({ ...sz[id], x: iw / 2 + rx * Math.cos(-Math.PI / 2 + 2 * Math.PI * i / n) - sz[id].w / 2,
      y: ry + tall / 2 + ry * Math.sin(-Math.PI / 2 + 2 * Math.PI * i / n) - sz[id].h / 2 }));
    let at = spot();
    while (ry < 1500 && at.some((a, i) => at.some((b, j) => i < j && overlap(a, b)))) { ry += 12; at = spot(); }
    ids.forEach((id, i) => put(id, at[i].x, at[i].y));
    h = 2 * ry + tall;
  }
  const routed = edges.map((e) => (e.hidden ? { d: "", at: [0, 0] as [number, number] } : route(boxes[e.a], boxes[e.b])));
  return { h: h + 2 * M, boxes, edges, paths: routed.map((r) => r.d), at: routed.map((r) => r.at), bands, order };
}

function useMeasure(el: React.RefObject<HTMLElement | null>) {
  const [fonts, setFonts] = useState(0);
  useEffect(() => { document.fonts?.ready.then(() => setFonts(1)); }, []);
  return useMemo(() => {
    const ctx = document.createElement("canvas").getContext("2d");
    if (!ctx) return (s: string) => s.length * FONT * 0.6;
    ctx.font = `600 ${FONT}px ${el.current ? getComputedStyle(el.current).fontFamily : "sans-serif"}`;
    return (s: string) => ctx.measureText(s).width;
  }, [el.current, fonts]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** A stepped animation at step `n`: which items are there, their labels, where the token sits. An item whose first event is an add is absent at the start (checks.animation_errors). */
function replay(d: Data, n: number) {
  const steps = d.steps ?? [], first = new Map<string, string>();
  for (const st of steps) { st.add.forEach((i) => first.has(i) || first.set(i, "add")); st.remove.forEach((i) => first.has(i) || first.set(i, "remove")); }
  const here = new Set(d.items.map((i) => i.id).filter((i) => first.get(i) !== "add"));
  const labels: Record<string, string> = {};
  let token: string | null = null;
  for (const st of steps.slice(0, n + 1)) {
    st.add.forEach((i) => here.add(i)); st.remove.forEach((i) => here.delete(i));
    Object.assign(labels, st.labels);
    if (st.move.length === 2) token = st.move[1];
  }
  return { here, labels, token, now: steps[n] as Step | undefined };
}
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

const INK = "var(--foreground)", LINE = "color-mix(in oklab, var(--foreground) 38%, transparent)";

function Card({ item, className, style, close, cardRef }: { item: Item; className?: string; style?: React.CSSProperties; close: () => void; cardRef?: React.Ref<HTMLElement> }) {
  const { onCite, onAsk } = useContext(DiagramActions);
  return (
    <aside ref={cardRef} role="region" aria-label={`About ${item.label}`} style={style} className={cn("z-10 max-h-[22rem] overflow-y-auto rounded-md border border-border bg-card p-3 text-sm shadow-md", className)}>
      <div className="flex items-start justify-between gap-2">
        <h4 className="font-medium">{item.label}</h4>
        <button type="button" onClick={close} aria-label="Close" className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"><X className="size-4" /></button>
      </div>
      <Md className="mt-1">{item.explanation}</Md>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        {onCite ? <button type="button" onClick={() => onCite(item.cite)} className="inline-flex items-center gap-1 underline decoration-dotted hover:text-foreground">
          <BookOpen className="size-3" />{item.cite.source} p.{item.cite.page}</button>
          : <span className="text-muted-foreground">{item.cite.source} p.{item.cite.page}</span>}
        {onAsk && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => onAsk({ id: item.id, label: item.label })}><Paperclip className="size-3" />Ask the tutor about this</Button>}
      </div>
    </aside>
  );
}

/** A diagram the model described (a kind, items, their relation) and code lays out and draws; click an item for its card. */
export function KindDiagram({ data }: { data: Data }) {
  const { onCite } = useContext(DiagramActions);
  const onCiteOf = (c: Citation) => onCite
    ? <button type="button" onClick={() => onCite(c)} className="inline-flex items-center gap-1 underline decoration-dotted hover:text-foreground"><BookOpen className="size-3" />{c.source} p.{c.page}</button>
    : <span>{c.source} p.{c.page}</span>;
  const mark = useId().replace(/[^a-zA-Z0-9]/g, "");
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [sel, setSel] = useState<string | null>(null);
  const [full, setFull] = useState(false);
  const [cardH, setCardH] = useState(0);
  const [at, setAt] = useState(0);
  const [playing, setPlaying] = useState(false);
  const token = useRef<SVGGElement>(null);
  const total = data.steps?.length ?? 0;
  const state = useMemo(() => replay(data, at), [data, at]);
  const { here, now } = state;
  const shown = useMemo(() => total ? { ...data, items: data.items.map((i) => ({ ...i, label: state.labels[i.id] ?? i.label })) } : data,
    [data, total, JSON.stringify(state.labels)]); // eslint-disable-line react-hooks/exhaustive-deps
  const card = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const on = () => setWidth(Math.floor(el.clientWidth));
    on();
    const ro = new ResizeObserver(on);
    ro.observe(el);
    return () => ro.disconnect();
  }, [full]);
  const measure = useMeasure(box);
  const laid = useMemo(() => width ? layout(shown, width, measure) : { h: 24, boxes: {}, edges: [], paths: [], at: [], bands: [], order: [] } as Laid, [shown, width, measure]);
  const item = sel ? shown.items.find((i) => i.id === sel) : undefined;
  useEffect(() => { setCardH(card.current?.offsetHeight ?? 0); }, [sel, width]);

  const near = new Set(sel ? [sel, ...laid.edges.flatMap((e) => (e.a === sel ? [e.b] : e.b === sel ? [e.a] : []))] : []);
  const stepLit = new Set(now ? [...now.highlight, ...now.links.flat(), ...now.move] : []);
  const lit = sel ? near : stepLit.size ? stepLit : null;  // what stays bright: the clicked item and its links, else this step's changes
  const stepEdge = (e: Edge) => !!now && [...now.links, now.move].some((l) => l.length === 2 && ((l[0] === e.a && l[1] === e.b) || (l[0] === e.b && l[1] === e.a)));
  const seen = (id: string) => !total || here.has(id);
  const order = laid.order.filter(seen);
  const go = (n: number) => { setAt(Math.max(0, Math.min(total - 1, n))); };
  useEffect(() => {
    if (!playing) return;
    if (at >= total - 1) { setPlaying(false); return; }
    const t = setTimeout(() => setAt(at + 1), 3000);
    return () => clearTimeout(t);
  }, [playing, at, total]);
  useEffect(() => { if (sel && !seen(sel)) setSel(null); }, [at]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {  // the token glides from where it was to where this step puts it; with reduced motion it cuts
    const el = token.current, move = now?.move;
    if (!el || !move || move.length !== 2 || reduced()) return;
    const prev = replay(data, at - 1).token ?? move[0], a = laid.boxes[prev], b = laid.boxes[move[1]];
    if (a && b) el.animate([{ transform: `translate(${cx(a)}px,${a.y}px)` }, { transform: `translate(${cx(b)}px,${b.y}px)` }], { duration: 700, easing: "ease-in-out" });
  }, [at]); // eslint-disable-line react-hooks/exhaustive-deps
  const b = sel ? laid.boxes[sel] : null;
  const floating = (() => {  // beside the item (right, left, below) where it hides no other item; else docked under the drawing
    if (!b || full || width < 560) return undefined;
    const w = Math.min(CARD, width - 2 * M), top = Math.max(0, Math.min(b.y, laid.h - cardH)), h = cardH || 160;
    const free = (r: { left: number; top: number; width: number }) => r.left >= 0 && r.left + r.width <= width && !Object.entries(laid.boxes)
      .some(([id, o]) => id !== sel && seen(id) && o.x < r.left + r.width && r.left < o.x + o.w && o.y < r.top + h && r.top < o.y + o.h);
    return [{ left: b.x + b.w + 12, top, width: w }, { left: b.x - 12 - w, top, width: w },
      { left: Math.max(0, Math.min(b.x, width - w)), top: b.y + b.h + 8, width: w }].find(free);
  })();
  const docked = !!item && !floating;
  const walk = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      if (sel) { setSel(null); e.stopPropagation(); } else if (full) setFull(false);
      return;
    }
    const step = ({ ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 } as Record<string, number>)[e.key];
    if (!step) return;
    e.preventDefault();
    const cur = order.indexOf((document.activeElement as HTMLElement | null)?.dataset.item ?? sel ?? "");
    const next = order[(cur < 0 ? (step > 0 ? 0 : order.length - 1) : (cur + step + order.length) % order.length)];
    if (sel) setSel(next);
    box.current?.querySelector<SVGGElement>(`[data-item="${CSS.escape(next)}"]`)?.focus();
  };
  const arrow = (on: boolean) => `${mark}${on ? "on" : "off"}`;
  const textBox = (id: string) => { const x = laid.boxes[id]; return x.holds ? { x: PX, anchor: "start" as const } : { x: x.w / 2, anchor: "middle" as const }; };
  return (
    <figure className={cn(full ? "fixed inset-0 z-50 flex flex-col gap-3 overflow-auto bg-background p-4 md:flex-row" : "relative")} onKeyDown={walk}>
      <div className={cn("min-w-0", full && "flex-1")}>
        <div className="mb-1 flex justify-end">
          <Button size="sm" variant="ghost" className="h-7 text-xs" aria-pressed={full} onClick={() => setFull(!full)}>
            {full ? <><Minimize2 className="size-3" />Exit full screen</> : <><Maximize2 className="size-3" />Full screen</>}</Button>
        </div>
        <div ref={box} className="relative w-full" style={{ minHeight: Math.max(laid.h, item && floating ? floating.top + cardH : 0) }}>
          <svg width={width} height={laid.h} role="group" aria-label="Diagram" style={{ display: "block", fontSize: FONT, fontFamily: "inherit" }}>
            <defs>
              {[true, false].map((on) => (
                <marker key={String(on)} id={arrow(on)} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
                  <path d="M0,0L10,5L0,10z" fill={on ? "var(--primary)" : LINE} /></marker>))}
            </defs>
            {laid.bands.map((band, i) => <rect key={i} x={M / 2} y={band.y} width={width - M} height={band.h} rx="6" fill="var(--muted)" opacity="0.55" />)}
            {laid.order.map((id) => {
              const x = laid.boxes[id], t = textBox(id), on = id === sel, bold = on || (!sel && !!now?.highlight.includes(id)), there = seen(id);
              return (
                <g key={id} data-item={id} role="button" tabIndex={there ? 0 : -1} aria-hidden={!there} aria-label={shown.items.find((i) => i.id === id)!.label} aria-pressed={on}
                   transform={`translate(${x.x},${x.y})`} opacity={!there ? 0 : lit && !lit.has(id) ? 0.3 : 1} pointerEvents={there ? undefined : "none"}
                   className="cursor-pointer outline-none motion-safe:transition-opacity motion-safe:duration-500 [&:focus-visible>rect]:[stroke:var(--primary)] [&:focus-visible>rect]:[stroke-width:3]"
                   onClick={() => setSel(on ? null : id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSel(on ? null : id); } }}>
                  <rect width={x.w} height={x.h} rx="6" fill={x.holds ? "color-mix(in oklab, var(--muted) 70%, var(--card))" : "var(--card)"}
                        stroke={bold ? "var(--primary)" : LINE} strokeWidth={bold ? 2.5 : 1.25} />
                  {x.lines.map((l, k) => <text key={k} x={t.x} y={PY + LH * (k + 0.5)} textAnchor={t.anchor} dominantBaseline="central" fill={INK} fontWeight={x.holds ? 600 : 500}>{l}</text>)}
                </g>
              );
            })}
            {laid.edges.map((e, i) => {
              if (e.hidden || !seen(e.a) || !seen(e.b)) return null;
              const on = sel ? e.a === sel || e.b === sel : stepEdge(e), lw = e.label ? Math.min(measure(e.label), width - 2 * M) : 0;
              const lx = Math.max(M + lw / 2, Math.min(width - M - lw / 2, laid.at[i][0]));
              return (
                <g key={i} pointerEvents="none" opacity={lit && !on ? 0.15 : 1}>
                  <path d={laid.paths[i]} fill="none" stroke={on ? "var(--primary)" : LINE} strokeWidth={on ? 2.25 : 1.25} markerEnd={`url(#${arrow(on)})`} />
                  {e.label && <text x={lx} y={laid.at[i][1]} textAnchor="middle" fill={INK} fontSize={FONT - 1} style={{ paintOrder: "stroke", stroke: "var(--background)", strokeWidth: 4 }}>{e.label}</text>}
                </g>
              );
            })}
            {state.token && laid.boxes[state.token] && <g ref={token} pointerEvents="none" data-token style={{ transform: `translate(${cx(laid.boxes[state.token])}px,${laid.boxes[state.token].y}px)` }}>
              <circle r="7" fill="var(--primary)" stroke="var(--background)" strokeWidth="2.5" /></g>}
          </svg>
          {item && floating && <Card item={item} close={() => setSel(null)} className="absolute" style={floating} cardRef={card} />}
        </div>
        {now && (
          <div className="mt-2 rounded-md border border-border bg-card p-3 text-sm">
            <div aria-live="polite" data-caption><Md>{now.caption}</Md></div>
            <div className="mt-1 text-xs text-muted-foreground">{onCiteOf(now.cite)}</div>
            <div className="mt-2 flex items-center gap-2">
              <Button size="icon" variant="outline" className="size-9" aria-label="Previous step" disabled={at === 0} onClick={() => { setPlaying(false); go(at - 1); }}><SkipBack className="size-4" /></Button>
              <Button size="icon" variant="outline" className="size-9" aria-label={playing ? "Pause" : "Play"}
                onClick={() => { if (!playing && at >= total - 1) setAt(0); setPlaying(!playing); }}>{playing ? <Pause className="size-4" /> : <Play className="size-4" />}</Button>
              <Button size="icon" variant="outline" className="size-9" aria-label="Next step" disabled={at >= total - 1} onClick={() => { setPlaying(false); go(at + 1); }}><SkipForward className="size-4" /></Button>
              <input type="range" aria-label="Step" min={0} max={total - 1} value={at} onChange={(e) => { setPlaying(false); go(+e.target.value); }} className="h-9 min-w-0 flex-1 accent-primary" />
              <span className="w-14 shrink-0 text-right text-xs tabular-nums text-muted-foreground">{at + 1} / {total}</span>
            </div>
          </div>
        )}
        {data.caption && <figcaption className="mt-2 text-sm text-muted-foreground"><Md>{data.caption}</Md></figcaption>}
      </div>
      {item && docked && <Card item={item} close={() => setSel(null)} className={full ? "md:w-80 md:shrink-0 md:self-start" : "mt-3"} />}
    </figure>
  );
}
