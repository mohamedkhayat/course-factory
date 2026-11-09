import { compile, derivative, isSymbolNode, parse } from "mathjs";

const CONSTANTS = new Set(["e", "i", "Infinity", "NaN", "pi", "true", "false"]);

/** The Plot Block has one independent variable but does not name it in its schema. */
export function plotVariable(expr: string): string {
  try {
    const names = new Set(parse(expr.replaceAll("**", "^")).filter(isSymbolNode)
      .map((node) => isSymbolNode(node) ? node.name : "")
      .filter((name) => !CONSTANTS.has(name)));
    return names.size === 1 ? [...names][0] : "x";
  } catch {
    return "x";
  }
}

/** Compiles a sympy-syntax expression (x**2, exp(x)) with mathjs's sandboxed parser; never JS eval. */
export function compileExpr(expr: string): ((scope: Record<string, number>) => number) | null {
  try {
    const c = compile(expr.replaceAll("**", "^"));
    return (scope) => {
      try {
        const v = c.evaluate({ ...scope });
        return typeof v === "number" && Number.isFinite(v) ? v : NaN;
      } catch {
        // A bad or incomplete expression must not crash the whole Review page.
        return NaN;
      }
    };
  } catch {
    return null;
  }
}

export type Method = "gradient" | "momentum" | "newton";

/** The points an optimiser visits on f(x, y); it stops early when it diverges. */
export function optimizerPath(expr: string, method: Method, start: [number, number], step: number, iterations: number, momentum = 0.9): [number, number][] {
  const f = parse(expr.replaceAll("**", "^"));
  const d = (n: typeof f, v: string) => derivative(n, v);
  const gx = d(f, "x"), gy = d(f, "y");
  const g = [gx.compile(), gy.compile()];
  const h = [d(gx, "x"), d(gx, "y"), d(gy, "x"), d(gy, "y")].map((n) => n.compile());
  let [x, y] = start, vx = 0, vy = 0;
  const path: [number, number][] = [[x, y]];
  for (let k = 0; k < iterations; k++) {
    const s = { x, y }, [a, b] = g.map((c) => c.evaluate(s) as number);
    if (method === "newton") {
      const [hxx, hxy, hyx, hyy] = h.map((c) => c.evaluate(s) as number), det = hxx * hyy - hxy * hyx;
      if (!det) break;
      x -= (hyy * a - hxy * b) / det;
      y -= (hxx * b - hyx * a) / det;
    } else {
      vx = (method === "momentum" ? momentum * vx : 0) - step * a;
      vy = (method === "momentum" ? momentum * vy : 0) - step * b;
      x += vx;
      y += vy;
    }
    if (!Number.isFinite(x) || !Number.isFinite(y) || Math.abs(x) + Math.abs(y) > 1e6) break;
    path.push([x, y]);
  }
  return path;
}
