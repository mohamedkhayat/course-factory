import { test } from "node:test";
import assert from "node:assert/strict";
import { compileExpr, plotVariable } from "./src/lib/math.ts";

test("a plot in another variable than x is drawn", () => {
  const v = plotVariable("a**2 - 6*a + 10");
  assert.equal(v, "a");
  assert.equal(compileExpr("a**2 - 6*a + 10")({ [v]: 3 }), 1);
});

test("gradient descent on a bowl walks to its minimum; Newton gets there in one step", async () => {
  const { optimizerPath } = await import("./src/lib/math.ts");
  const gd = optimizerPath("x**2 + 10*y**2", "gradient", [2, 1], 0.05, 200);
  const [x, y] = gd.at(-1);
  assert.ok(Math.abs(x) < 1e-3 && Math.abs(y) < 1e-3);
  const nt = optimizerPath("x**2 + 10*y**2", "newton", [2, 1], 0.05, 3);
  assert.ok(Math.abs(nt[1][0]) < 1e-9 && Math.abs(nt[1][1]) < 1e-9);
  assert.ok(optimizerPath("x**2", "gradient", [1, 0], 5, 100).length < 101); // diverges: stops early
});
