import { useEffect, useMemo, useRef, useState } from "react";
import { Pause, Play, RotateCcw, StepForward } from "lucide-react";
import { Button } from "@/components/ui/button";
import { compileExpr, optimizerPath, type Method } from "@/lib/math";
import { Md, MdLine } from "./md";

type Range = [number, number];
const N = 60;

function grid(expr: string, xr: Range, yr: Range) {
  const f = compileExpr(expr);
  const xs = Array.from({ length: N }, (_, i) => xr[0] + ((xr[1] - xr[0]) * i) / (N - 1));
  const ys = Array.from({ length: N }, (_, i) => yr[0] + ((yr[1] - yr[0]) * i) / (N - 1));
  const z = ys.map((y) => xs.map((x) => (f ? f({ x, y }) : NaN)));
  return { xs, ys, z };
}

/** Theme colours as rgb(): the theme uses oklch(), which Plotly cannot parse. */
function rgb(css: string, fallback: string) {
  const ctx = document.createElement("canvas").getContext("2d");
  if (!ctx || !css) return fallback;
  ctx.fillStyle = css;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  return `rgb(${r},${g},${b})`;
}

function colors() {
  const s = getComputedStyle(document.documentElement), v = (n: string) => s.getPropertyValue(n).trim();
  return { fg: rgb(v("--foreground"), "#222"), primary: rgb(v("--primary"), "#c2410c"), font: v("--font-read") || "sans-serif" };
}

/** Draws with Plotly, loaded only when a 3D or contour Block is on screen. */
function usePlotly(ref: React.RefObject<HTMLDivElement | null>, traces: object[], layout: object) {
  useEffect(() => {
    let alive = true;
    const el = ref.current;
    import("plotly.js-dist-min").then(({ default: Plotly }) => {
      if (!alive || !el) return;
      const c = colors();
      Plotly.react(el, traces as never, { paper_bgcolor: "transparent", plot_bgcolor: "transparent", margin: { l: 40, r: 10, t: 10, b: 36 },
        font: { color: c.fg, family: c.font, size: 12 }, showlegend: false, ...layout } as never, { displayModeBar: false, responsive: true });
    });
    return () => { alive = false; };
  }, [ref, traces, layout]);
  useEffect(() => () => { const el = ref.current; if (el) import("plotly.js-dist-min").then(({ default: P }) => P.purge(el)); }, [ref]);
}

function Plotted({ traces, layout, label, className = "h-80" }: { traces: object[]; layout: object; label: string; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  usePlotly(ref, traces, layout);
  return <div ref={ref} role="img" aria-label={label} className={`w-full ${className}`} />;
}

type SurfaceData = { title: string; expr: string; x_range: Range; y_range: Range; view: "surface" | "contour" | "both"; points: { x: number; y: number; label: string }[]; caption: string };

export function SurfacePlot({ data }: { data: SurfaceData }) {
  const g = useMemo(() => grid(data.expr, data.x_range, data.y_range), [data.expr, data.x_range, data.y_range]);
  const f = useMemo(() => compileExpr(data.expr), [data.expr]);
  const c = colors();
  const pts = data.points;
  const surface = useMemo(() => [
    { type: "surface", x: g.xs, y: g.ys, z: g.z, colorscale: "YlOrBr", reversescale: true, showscale: false, contours: { z: { show: true, usecolormap: true, project: { z: true } } } },
    ...(pts.length ? [{ type: "scatter3d", mode: "markers+text", x: pts.map((p) => p.x), y: pts.map((p) => p.y), z: pts.map((p) => (f ? f({ x: p.x, y: p.y }) : 0)),
      text: pts.map((p) => p.label), marker: { size: 4, color: c.primary } }] : []),
  ], [g, pts, f, c.primary]);
  const contour = useMemo(() => [
    { type: "contour", x: g.xs, y: g.ys, z: g.z, colorscale: "YlOrBr", reversescale: true, showscale: false, ncontours: 25, contours: { coloring: "lines" } },
    ...(pts.length ? [{ type: "scatter", mode: "markers+text", x: pts.map((p) => p.x), y: pts.map((p) => p.y), text: pts.map((p) => p.label),
      textposition: "top center", marker: { size: 8, color: c.primary } }] : []),
  ], [g, pts, c.primary]);
  const layout3d = useMemo(() => ({ margin: { l: 0, r: 0, t: 0, b: 0 }, scene: { xaxis: { title: { text: "x" } }, yaxis: { title: { text: "y" } }, zaxis: { title: { text: "f" } } } }), []);
  const layout2d = useMemo(() => ({ xaxis: { title: { text: "x" } }, yaxis: { title: { text: "y" }, scaleanchor: "x" } }), []);
  return (
    <figure>
      <h4 className="mb-2 font-medium"><MdLine>{data.title}</MdLine></h4>
      <div className={data.view === "both" ? "grid gap-4 md:grid-cols-2" : ""}>
        {data.view !== "contour" && <Plotted traces={surface} layout={layout3d} label={`3D surface of ${data.expr}; drag to rotate`} />}
        {data.view !== "surface" && <Plotted traces={contour} layout={layout2d} label={`Contour lines of ${data.expr}`} />}
      </div>
      <figcaption className="mt-2 text-sm text-muted-foreground">{data.view !== "contour" && "Drag to rotate. "}<Md>{data.caption}</Md></figcaption>
    </figure>
  );
}

type OptimizerData = { title: string; expr: string; method: Method; start: [number, number]; step: number; momentum: number; iterations: number; x_range: Range; y_range: Range; caption: string };

const METHOD: Record<Method, string> = { gradient: "Gradient descent", momentum: "Gradient descent with momentum", newton: "Newton's method" };

/** An optimiser stepping over the contour lines; the step size is a slider, the path is recomputed live. */
export function OptimizerAnimation({ data }: { data: OptimizerData }) {
  const [step, setStep] = useState(data.step);
  const [k, setK] = useState(0);
  const [playing, setPlaying] = useState(false);
  const path = useMemo(() => optimizerPath(data.expr, data.method, data.start, step, data.iterations, data.momentum), [data, step]);
  const g = useMemo(() => grid(data.expr, data.x_range, data.y_range), [data.expr, data.x_range, data.y_range]);
  const f = useMemo(() => compileExpr(data.expr), [data.expr]);
  const shown = path.slice(0, k + 1), [x, y] = shown.at(-1)!;
  useEffect(() => {
    if (!playing) return;
    if (k >= path.length - 1) { setPlaying(false); return; }
    const t = setTimeout(() => setK(k + 1), 220);
    return () => clearTimeout(t);
  }, [playing, k, path.length]);
  const c = colors();
  const traces = useMemo(() => [
    { type: "contour", x: g.xs, y: g.ys, z: g.z, colorscale: "YlOrBr", reversescale: true, showscale: false, ncontours: 25, contours: { coloring: "lines" } },
    { type: "scatter", mode: "lines+markers", x: shown.map((p) => p[0]), y: shown.map((p) => p[1]), line: { color: c.primary, width: 2 }, marker: { size: 6, color: c.primary } },
  ], [g, shown, c.primary]);
  const layout = useMemo(() => ({ xaxis: { range: data.x_range, title: { text: "x" } }, yaxis: { range: data.y_range, title: { text: "y" }, scaleanchor: "x" } }), [data.x_range, data.y_range]);
  const diverged = path.length < data.iterations + 1 && data.method !== "newton";
  return (
    <figure>
      <h4 className="mb-1 font-medium"><MdLine>{data.title}</MdLine></h4>
      <p className="mb-2 text-sm text-muted-foreground">{METHOD[data.method]} on <code>f(x, y) = {data.expr}</code> from ({data.start.join(", ")})</p>
      <Plotted traces={traces} layout={layout} label={`${METHOD[data.method]} path on the contour lines of ${data.expr}`} className="h-96" />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => { if (k >= path.length - 1) setK(0); setPlaying(!playing); }} aria-label={playing ? "Pause" : "Play"}>
          {playing ? <Pause className="size-4" /> : <Play className="size-4" />}{playing ? "Pause" : "Play"}</Button>
        <Button size="sm" variant="outline" onClick={() => setK(Math.min(k + 1, path.length - 1))} disabled={k >= path.length - 1}><StepForward className="size-4" />Step</Button>
        <Button size="sm" variant="ghost" onClick={() => { setK(0); setPlaying(false); }}><RotateCcw className="size-4" />Reset</Button>
        <span className="tabular ml-auto text-sm text-muted-foreground">k = {k} · x = ({x.toFixed(3)}, {y.toFixed(3)}) · f = {f ? f({ x, y }).toPrecision(4) : "?"}</span>
      </div>
      {data.method !== "newton" && (
        <label className="mt-3 flex items-center gap-3 text-sm">
          <span className="shrink-0">Step size {step.toPrecision(3)}</span>
          <input type="range" className="w-full accent-[var(--primary)]" min={data.step / 10} max={data.step * 4} step={data.step / 100} value={step}
            onChange={(e) => { setStep(Number(e.target.value)); setK(0); setPlaying(false); }} />
        </label>
      )}
      {diverged && <p className="mt-1 text-sm text-destructive">The iterates blow up at this step size: it is too large for this function.</p>}
      {data.caption && <figcaption className="mt-2 text-sm text-muted-foreground"><Md>{data.caption}</Md></figcaption>}
    </figure>
  );
}
