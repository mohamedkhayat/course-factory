// Playwright smoke tests: the built app on the fake model, one per key screen. Run: npm run smoke (after npm run build).
import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium, devices } from "playwright";

const PORT = 8790 + Math.floor(Math.random() * 100);
const BASE = `http://127.0.0.1:${PORT}`;
let server, browser, folder;

before(async () => {
  server = spawn("uv", ["run", "python", "tests/fake_server.py", String(PORT), mkdtempSync(join(tmpdir(), "cf-smoke-"))], { cwd: "..", stdio: ["ignore", "pipe", "inherit"] });
  await new Promise((ok, fail) => {
    server.stdout.on("data", (d) => String(d).includes("seeded course") && ok());
    server.on("exit", (c) => fail(new Error(`fake server exited ${c}`)));
  });
  for (let i = 0; i < 50; i++) { try { if ((await fetch(BASE)).ok) break; } catch { /* starting */ } await new Promise((r) => setTimeout(r, 200)); }
  folder = (await (await fetch(`${BASE}/api/courses/1`)).json()).folder;
  browser = await chromium.launch();
});
after(async () => { await browser?.close(); server?.kill(); });

async function page(opts = {}) {
  const p = await browser.newPage(opts);
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  p.errors = errors;
  return p;
}

test("found gate, outline gate, then Review and publish", async () => {
  const p = await page();
  await p.goto(BASE);
  await p.getByLabel("Course name").fill("Smoke");
  await p.getByLabel("Folder").fill(folder);
  await p.getByRole("button", { name: "Import the folder" }).click();
  await p.getByRole("heading", { name: "What was found" }).waitFor({ timeout: 30_000 });
  assert.ok(await p.locator("[data-source]").count() >= 6);
  await p.getByLabel("Role of TD1_corrige.pdf").waitFor();
  await p.getByRole("button", { name: /propose an outline/ }).click();
  await p.getByRole("heading", { name: "Proposed outline" }).waitFor({ timeout: 30_000 });
  await p.getByLabel("Chapter 1 title").fill("Convexité (édité)");
  await p.getByLabel("Chapter 2 Section 2 title").fill("Exercices corrigés");
  await p.getByRole("button", { name: "Start a new Chapter here" }).nth(2).click(); // Chapter 2's second Section starts Chapter 3
  assert.equal(await p.getByLabel("Chapter 3 title").inputValue(), "Exercices corrigés");
  await p.getByRole("button", { name: "Save changes" }).click();
  await p.getByRole("button", { name: /Approve, write the Chapters/ }).waitFor();
  assert.equal(await p.getByLabel(/^Chapter \d title$/).count(), 3);
  await p.getByRole("button", { name: /Approve, write the Chapters/ }).click();
  await p.getByText("The Chapters are written and wait for your review").waitFor({ timeout: 60_000 });
  await p.getByRole("link", { name: "Review Chapters" }).click();
  await p.getByRole("heading", { name: "Convexité (édité)" }).waitFor();
  const publish = p.getByRole("button", { name: "Publish" }).first();
  if (await publish.isEnabled()) {
    await publish.click();
    await p.getByRole("heading", { name: "Convexité (édité)" }).waitFor({ state: "detached" });
  }
  assert.deepEqual(p.errors, []);
});

test("Lab editor runs a cell with Shift+Enter, and the Lab tutor answers", async () => {
  const p = await page();
  await p.goto(`${BASE}/c/1/labs/1`);
  const editor = p.getByLabel("Code for step 1");
  await editor.click();
  await p.keyboard.press("ControlOrMeta+a");
  await p.keyboard.type("print(6 * 7)");
  await p.keyboard.press("Shift+Enter");
  await p.getByText("42", { exact: true }).waitFor({ timeout: 60_000 });
  await p.getByRole("button", { name: "Ask the tutor" }).first().click();
  await p.getByLabel("Question").fill("why?");
  await p.getByLabel("Question").press("Enter");
  await p.getByText(/plots seen/).waitFor();
  assert.deepEqual(p.errors, []);
});

test("reader opens a Citation's source page", async () => {
  const p = await page();
  await p.goto(`${BASE}/c/1/read`);
  await p.getByRole("button", { name: /cours\.pdf p\.1/ }).first().click();
  const img = p.getByRole("dialog").getByRole("img");
  await img.waitFor();
  assert.ok(await img.evaluate((i) => i.complete && i.naturalWidth > 0));
  assert.deepEqual(p.errors, []);
});

test("search finds a page of the material", async () => {
  const p = await page();
  await p.goto(`${BASE}/c/1`);
  await p.getByLabel("Search the course material").fill("convexe");
  await p.getByRole("button", { name: "Search", exact: true }).click();
  await p.getByRole("search").locator("xpath=..").getByText(/\.pdf, p\. \d/).first().waitFor();
  assert.deepEqual(p.errors, []);
});

test("quiz stepper checks one question at a time", async () => {
  const p = await page();
  await p.goto(`${BASE}/c/1/read`);
  await p.getByText("Question 1 of 1").waitFor();
  await p.getByRole("radio", { name: "oui" }).click();
  await p.getByRole("button", { name: "Check" }).click();
  await p.getByRole("button", { name: "See score" }).click();
  await p.getByText(/Score: 1 \/ 1/).waitFor();
  assert.deepEqual(p.errors, []);
});

test("exam mode: answer, hand in, graded Copy with Marking scheme", async () => {
  const p = await page();
  await p.goto(`${BASE}/c/1/exams`);
  await p.getByRole("button", { name: "Sit it" }).first().click();
  await p.getByRole("timer", { name: "Time left" }).waitFor();
  await p.getByLabel("Answer to question 1").fill("$x^* = 0$ car le gradient s'annule.");
  await p.getByText("Saved").waitFor();
  await p.getByRole("button", { name: "Hand in" }).click();
  await p.getByRole("button", { name: "Hand in now" }).click();
  await p.getByText("Marking scheme").first().waitFor({ timeout: 30_000 });
  await p.getByText("Model answer").first().waitFor();
  assert.deepEqual(p.errors, []);
});

test("Component preview renders in its sandbox and can be approved", async () => {
  const p = await page();
  await p.goto(`${BASE}/components`);
  const frame = p.frameLocator('iframe[title="saddle_point"]');
  await frame.getByText("Lagrange").waitFor();
  assert.equal(await p.locator('iframe[title="saddle_point"]').getAttribute("sandbox"), "allow-scripts");
  const approve = p.getByRole("button", { name: "Approve", exact: true });
  await approve.click();
  await approve.waitFor({ state: "detached" });
  await p.getByText("approved", { exact: true }).first().waitFor();
  assert.deepEqual(p.errors, []);
});

test("tablet viewport: reader and exams fit without sideways scrolling", async () => {
  const p = await page({ ...devices["Galaxy Tab S4"] });
  for (const path of ["/c/1/read", "/c/1/exams", "/c/1/cards"]) {
    await p.goto(BASE + path);
    await p.waitForLoadState("networkidle");
    assert.ok(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${path} overflows`);
  }
  await p.getByRole("button", { name: "Show the answer" }).tap();
  await p.getByRole("button", { name: /Bien/ }).waitFor();
  assert.deepEqual(p.errors, []);
});
