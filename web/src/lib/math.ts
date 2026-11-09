import { compile, isSymbolNode, parse } from "mathjs";

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
