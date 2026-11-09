import { test } from "node:test";
import assert from "node:assert/strict";
import { compileExpr, plotVariable } from "./src/lib/math.ts";

test("a plot in another variable than x is drawn", () => {
  const v = plotVariable("a**2 - 6*a + 10");
  assert.equal(v, "a");
  assert.equal(compileExpr("a**2 - 6*a + 10")({ [v]: 3 }), 1);
});
