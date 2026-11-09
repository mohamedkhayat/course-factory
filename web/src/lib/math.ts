import { compile } from "mathjs";

/** Compiles a sympy-syntax expression (x**2, exp(x)) with mathjs's sandboxed parser; never JS eval. */
export function compileExpr(expr: string): ((scope: Record<string, number>) => number) | null {
  try {
    const c = compile(expr.replaceAll("**", "^"));
    return (scope) => {
      const v = c.evaluate({ ...scope });
      return typeof v === "number" ? v : NaN;
    };
  } catch {
    return null;
  }
}
