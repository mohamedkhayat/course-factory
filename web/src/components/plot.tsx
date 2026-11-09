import { useMemo, useState } from "react";
import { compileExpr, plotVariable } from "@/lib/math";
import { Md } from "./md";

const W = 560, H = 300, PAD = 32;
const COLORS = ["var(--primary)", "var(--warn)", "var(--ok)", "var(--destructive)"];

function Graph({ fns, range }: { fns: { f: (x: number) => number; label: string }[]; range: [number, number] }) {
  const [x0, x1] = range;
  const series = fns.map(({ f }) =>
    Array.from({ length: 241 }, (_, i) => { const x = x0 + ((x1 - x0) * i) / 240; return [x, f(x)] as const; }));
  const ys = series.flat().map(([, y]) => y).filter(Number.isFinite);
  let [y0, y1] = ys.length ? [Math.min(...ys), Math.max(...ys)] : [-1, 1];
  if (y1 - y0 < 1e-9) { y0 -= 1; y1 += 1; }
  const sx = (x: number) => PAD + ((x - x0) / (x1 - x0)) * (W - 2 * PAD);
  const sy = (y: number) => H - PAD - ((y - y0) / (y1 - y0)) * (H - 2 * PAD);
  const path = (pts: readonly (readonly [number, number])[]) => {
    let d = "", pen = false;
    for (const [x, y] of pts) {
      if (!Number.isFinite(y)) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${sx(x).toFixed(1)},${sy(y).toFixed(1)}`;
      pen = true;
    }
    return d;
  };
  return (
    <figure className="space-y-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-[560px] text-muted-foreground" role="img"
           aria-label={fns.map((f) => f.label).join(", ")}>
        {y0 < 0 && y1 > 0 && <line x1={PAD} x2={W - PAD} y1={sy(0)} y2={sy(0)} stroke="currentColor" strokeOpacity={0.5} />}
        {x0 < 0 && x1 > 0 && <line y1={PAD} y2={H - PAD} x1={sx(0)} x2={sx(0)} stroke="currentColor" strokeOpacity={0.5} />}
        <rect x={PAD} y={PAD} width={W - 2 * PAD} height={H - 2 * PAD} fill="none" stroke="currentColor" strokeOpacity={0.25} />
        <g className="tabular" fontSize={11} fill="currentColor">
          <text x={PAD} y={H - 10}>{x0}</text>
          <text x={W - PAD} y={H - 10} textAnchor="end">{x1}</text>
          <text x={4} y={PAD + 4}>{+y1.toPrecision(3)}</text>
          <text x={4} y={H - PAD}>{+y0.toPrecision(3)}</text>
        </g>
        {series.map((pts, i) => <path key={i} d={path(pts)} fill="none" stroke={COLORS[i % 4]} strokeWidth={2} />)}
      </svg>
      {fns.length > 1 && (
        <figcaption className="flex flex-wrap gap-4 text-sm">
          {fns.map((f, i) => (
            <span key={i} className="flex items-center gap-1.5"><span className="h-0.5 w-4" style={{ background: COLORS[i % 4] }} />{f.label}</span>
          ))}
        </figcaption>
      )}
    </figure>
  );
}

export function Plot({ data }: { data: { title?: string; functions: { expr: string; label?: string }[]; x_range?: [number, number] } }) {
  const fns = data.functions.flatMap((fn) => {
    const variable = plotVariable(fn.expr);
    const f = compileExpr(fn.expr);
    return f ? [{ f: (x: number) => f({ [variable]: x }), label: fn.label || fn.expr }] : [];
  });
  return (
    <div>
      {data.title && <h4 className="mb-2 font-medium">{data.title}</h4>}
      <Graph fns={fns} range={data.x_range ?? [-5, 5]} />
    </div>
  );
}

type Param = { name: string; min: number; max: number; value: number };

export function Explorer({ data }: { data: { title: string; expr: string; params: Param[]; x_range?: [number, number]; explanation?: string } }) {
  const [vals, setVals] = useState(() => Object.fromEntries(data.params.map((p) => [p.name, p.value])));
  const f = useMemo(() => compileExpr(data.expr), [data.expr]);
  return (
    <div className="space-y-3">
      <h4 className="font-medium">{data.title}</h4>
      <div className="grid gap-2 sm:grid-cols-2">
        {data.params.map((p) => (
          <label key={p.name} className="flex items-center gap-3 text-sm">
            <span className="w-10 font-mono">{p.name}</span>
            <input type="range" min={p.min} max={p.max} step={(p.max - p.min) / 200} value={vals[p.name]}
                   onChange={(e) => setVals({ ...vals, [p.name]: +e.target.value })} className="flex-1 accent-[var(--primary)]" />
            <span className="tabular w-14 text-right">{vals[p.name].toFixed(2)}</span>
          </label>
        ))}
      </div>
      {f ? <Graph fns={[{ f: (x) => f({ ...vals, x }), label: data.expr }]} range={data.x_range ?? [-5, 5]} />
         : <p className="text-sm text-destructive">This expression can't be drawn.</p>}
      {data.explanation && <Md>{data.explanation}</Md>}
    </div>
  );
}
