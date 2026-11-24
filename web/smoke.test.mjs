// Playwright smoke tests: the built app on the fake model, one per key screen. Run: npm run smoke (after npm run build).
import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium, devices } from "playwright";

const PORT = 8790 + Math.floor(Math.random() * 100);
const BASE = `http://127.0.0.1:${PORT}`;
const dataDir = mkdtempSync(join(tmpdir(), "cf-smoke-"));
let server, browser, folder;

before(async () => {
  server = spawn("uv", ["run", "python", "tests/fake_server.py", String(PORT), dataDir], { cwd: "..", stdio: ["ignore", "pipe", "inherit"] });
  await new Promise((ok, fail) => {
    server.stdout.on("data", (d) => String(d).includes("seeded course") && ok());
    server.on("exit", (c) => fail(new Error(`fake server exited ${c}`)));
  });
  for (let i = 0; i < 50; i++) { try { if ((await fetch(BASE)).ok) break; } catch { /* starting */ } await new Promise((r) => setTimeout(r, 200)); }
  folder = (await (await fetch(`${BASE}/api/courses/1`)).json()).folder;
  browser = await chromium.launch();
});
after(async () => { await browser?.close(); server?.kill(); rmSync(dataDir, { recursive: true, force: true }); });

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
  await p.getByRole("heading", { name: "Optimisation" }).first().waitFor();  // the seeded Course's card on the hub
  await p.getByRole("button", { name: "New Course" }).first().click();
  await p.getByLabel("Folder").setInputFiles(folder);  // what the folder picker hands over
  assert.equal(await p.getByLabel("Course name").inputValue(), "optimisation");  // named after the folder
  await p.getByLabel("Course name").fill("Smoke");
  await p.getByRole("button", { name: /^Import \d+ files$/ }).click();
  await p.getByRole("heading", { name: "What was found" }).waitFor({ timeout: 30_000 });
  await p.getByText("Step 4 of 13: Check what was found").waitFor();
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
  await p.getByRole("button", { name: "Check", exact: true }).first().click();
  await p.getByRole("button", { name: "See score" }).click();
  await p.getByText(/Score: 1 \/ 1/).waitFor();
  assert.deepEqual(p.errors, []);
});

test("exam mode: answer, hand in, graded Copy with Marking scheme", async () => {
  const p = await page();
  await p.goto(`${BASE}/c/1/exams`);
  await p.getByRole("button", { name: "Sit it" }).first().click();
  await p.getByRole("button", { name: "Start the clock" }).click();
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
  await p.getByRole("button", { name: /Good/ }).waitFor();
  assert.deepEqual(p.errors, []);
});

test("practice and visual Components work in the reader", async () => {
  const p = await page();
  await p.goto(`${BASE}/c/1/read`);
  const blank = p.getByLabel("Blank 1").first();
  await blank.fill("python:3.11");  // accepted by the blank's regex
  await p.getByLabel("Blank 2").first().fill("add");
  const blanks = p.locator("div").filter({ has: p.getByRole("heading", { name: "Dockerfile", exact: true }) }).last();
  await blanks.getByRole("button", { name: "Check", exact: true }).click();
  await p.getByText("All correct").first().waitFor();
  await p.getByRole("img", { name: /3D surface of/ }).first().locator(".main-svg").first().waitFor({ timeout: 30_000 });
  await p.getByRole("button", { name: "Step" }).first().click();
  await p.getByText(/^k = 1/).first().waitFor();
  await p.getByRole("button", { name: "Next step" }).first().click();
  await p.getByText("The load balancer forwards it").first().waitFor();
  await p.waitForFunction(() => [...document.querySelectorAll("path.flowchart-link, .edgePaths path")]
    .some((e) => e instanceof SVGElement && e.style.stroke.includes("primary")), null, { timeout: 10_000 });
  await p.getByText("Successfully tagged app:latest").first().waitFor();
  await p.getByRole("button", { name: "Show step 1 of 2" }).first().click();
  await p.getByRole("button", { name: "Show step 2 of 2" }).first().click();
  await p.getByRole("button", { name: "Show the answer" }).first().click();
  await p.getByRole("button", { name: "Missed it" }).first().click();
  await p.getByText("Marked: missed").first().waitFor();
  const code = p.locator("figure, div").filter({ has: p.getByRole("heading", { name: "Containerise the app" }) }).last();
  await code.getByRole("button", { name: "Check", exact: true }).click();
  await code.getByRole("status").waitFor();
  await code.getByRole("button", { name: "Hint" }).click();
  await code.getByText("Start from a Python image.").waitFor();
  await code.getByRole("button", { name: "Hint" }).click();
  await code.getByText(/Look at what/).waitFor();
  const compose = p.locator("div").filter({ has: p.getByRole("heading", { name: "Complete the Compose file" }) }).last();
  await compose.getByLabel("Blank 1").fill("127.0.0.1:8000:8000");
  await compose.getByRole("button", { name: "Check", exact: true }).click();
  await compose.getByText("All correct").waitFor();
  assert.deepEqual(p.errors, []);
});

test("Course chat draws a checked Block inline and saves it into the suggested Section", async () => {
  const p = await page();
  await p.goto(`${BASE}/c/1/chat`);
  await p.getByRole("button", { name: "Attach Blocks" }).click();
  await p.getByRole("dialog", { name: "Attach Blocks" }).getByRole("listitem").first().getByRole("button").click();
  await p.keyboard.press("Escape");
  await p.getByRole("button", { name: "Detach this Block" }).waitFor();  // shown above the box until it is sent
  await p.getByLabel("Question", { exact: true }).fill("Explique le gradient");
  await p.getByRole("button", { name: "Ask", exact: true }).click();
  await p.getByText("Le gradient pointe vers la plus forte croissance.").waitFor({ timeout: 30_000 });  // drawn by the theorem_box renderer
  assert.equal(await p.getByText('"component"').count(), 0);  // never as JSON
  await p.getByRole("button", { name: "Save to Section" }).click();
  await p.getByRole("combobox").first().waitFor();
  assert.match(await p.getByRole("combobox").first().locator("option:checked").textContent(), /Gradient/);
  await p.getByRole("button", { name: "Save", exact: true }).click();
  await p.getByRole("link", { name: /Saved in Gradient/ }).click();
  await p.getByText("Le gradient pointe vers la plus forte croissance.").first().waitFor();
  await p.getByText("from the chat").first().waitFor();
  assert.deepEqual(p.errors, []);
});

test("the tutor remembers a stated preference, shown with Undo, listed in Settings and deleted there", async () => {
  const p = await page();
  await p.goto(`${BASE}/c/1/read`);
  await p.locator(".fixed button", { hasText: "Ask the tutor" }).click();
  await p.getByLabel("Question").fill("No paper exercises please");
  await p.getByLabel("Question").press("Enter");
  await p.getByText("Remembered: No exercises to write on paper.").waitFor({ timeout: 30_000 });
  assert.equal(await p.getByText("remember", { exact: false }).filter({ hasText: "```" }).count(), 0);  // the fence never shows
  await p.getByRole("button", { name: "Undo", exact: true }).waitFor();
  await p.goto(`${BASE}/settings`);
  await p.getByText("No exercises to write on paper.").waitFor();
  await p.getByRole("button", { name: "Delete “No exercises to write on paper.”" }).click();
  await p.getByText("Nothing yet.").first().waitFor();
  assert.equal(await p.getByText("No exercises to write on paper.").count(), 0);
  assert.deepEqual(p.errors, []);
});

test("a diagram item opens its card, arrow keys walk the items, Escape closes, labels fit at any width", async () => {
  const p = await page();
  await p.goto(`${BASE}/c/1/read`);
  const about = (n) => p.getByRole("region", { name: `About Etape ${n}` });
  await p.getByRole("button", { name: "Etape a", exact: true }).click();
  await about("a").getByText("a fait une chose").waitFor();
  await about("a").getByRole("button", { name: /cours\.pdf p\.1/ }).waitFor();
  await p.keyboard.press("ArrowRight");  // a tree is walked depth first: a, then its first child
  await about("b").waitFor();
  assert.equal(await about("a").count(), 0);
  await p.keyboard.press("Escape");
  await about("b").waitFor({ state: "detached" });
  await p.getByRole("button", { name: "Etape c", exact: true }).click();
  await p.getByRole("button", { name: "Ask the tutor about this" }).click();
  await p.getByLabel("Attached to the next question").getByText("Etape c").waitFor();
  for (const width of [320, 1400]) {
    await p.setViewportSize({ width, height: 900 });
    const fits = await p.getByRole("group", { name: "Diagram" }).first().evaluate((svg) => {
      const w = svg.getBoundingClientRect().width;
      return [...svg.querySelectorAll("[data-item]")].every((g) => { const r = g.getBoundingClientRect(), s = svg.getBoundingClientRect(); return r.left >= s.left - 1 && r.right <= s.left + w + 1; })
        && svg.parentElement.scrollWidth <= svg.parentElement.clientWidth + 1;
    });
    assert.ok(fits, `a diagram item sticks out at ${width}px`);
  }
  assert.deepEqual(p.errors, []);
});

test("a stepped animation steps forward, plays, scrubs and keeps its items clickable", async () => {
  const p = await page();
  await p.goto(`${BASE}/c/1/read`);
  const fig = p.locator("figure").filter({ has: p.locator("[data-caption]") });  // the tree diagram has Etape a..d too
  const caption = fig.locator("[data-caption]");
  await caption.getByText("arrivent dans la partition a").waitFor();
  await fig.getByRole("button", { name: "Next step" }).click();
  await caption.getByText("passe de a à b").waitFor();
  assert.equal(await fig.locator("[data-token]").count(), 1);
  assert.equal(await fig.locator("[data-item=d]").getAttribute("aria-hidden"), "true");  // added in step 3
  await fig.getByLabel("Step", { exact: true }).fill("3");  // scrub to the last step
  await caption.getByText("Le jeton continue vers c").waitFor();
  assert.equal(await fig.locator("[data-item=d]").getAttribute("aria-hidden"), "false");
  await fig.getByRole("button", { name: "Partition c bis", exact: true }).click();  // relabelled in step 3, still clickable
  await p.getByRole("region", { name: "About Partition c bis" }).getByText("c fait une chose").waitFor();
  await fig.getByRole("button", { name: "Previous step" }).click();
  await caption.getByText("La partition d apparaît").waitFor();
  await fig.getByRole("button", { name: "Play" }).click();
  await caption.getByText("Le jeton continue vers c").waitFor({ timeout: 8000 });  // plays on by itself
  assert.deepEqual(p.errors, []);
});

test("Listen highlights the sentence being read and a click on another seeks to it", async () => {
  const p = await page();
  await p.goto(`${BASE}/c/1/read`);
  await p.getByRole("button", { name: "Listen to this Section" }).click();
  const bar = p.getByRole("region", { name: "Listen" });
  await bar.getByRole("button", { name: "Show the transcript" }).click();  // the widget starts small
  const lines = bar.getByRole("list", { name: "Transcript" }).getByRole("listitem");
  await lines.nth(3).getByRole("button").waitFor();
  await p.waitForFunction(() => document.querySelectorAll('[aria-label="Transcript"] button:not([disabled])').length >= 4);  // clips arrive as they are made
  assert.equal(await bar.locator("[aria-current]").count(), 1);
  const target = lines.nth(3);
  await target.getByRole("button").click();
  assert.equal(await target.getAttribute("aria-current"), "true");  // the clicked sentence is the current one
  assert.equal(await bar.locator("[aria-current]").count(), 1);
  assert.match(await p.locator("audio").evaluate((a) => a.getAttribute("src")), /\/listen\/kokoro\/[0-9a-f]{16}\/3\.wav$/);
  await bar.getByRole("button", { name: "Pause" }).click();
  await bar.getByRole("button", { name: "Play" }).waitFor();
  await bar.getByRole("button", { name: "Forward 10 seconds" }).click();
  await bar.getByLabel("Speed").selectOption("1.5");
  assert.equal(await p.locator("audio").evaluate((a) => a.playbackRate), 1.5);
  assert.ok(await p.locator("[data-block].ring-2").count() >= 1);  // the Block being read is marked in the article
  await p.screenshot({ path: process.env.SMOKE_SHOTS ? join(process.env.SMOKE_SHOTS, "listen.png") : undefined });
  assert.deepEqual(p.errors, []);
});

test("the media queue shows what is being made, pauses and stops a job", async () => {
  const p = await page();
  await p.goto(`${BASE}/c/1/read`);
  await p.evaluate(() => fetch("/api/media/pause", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ paused: true }) }));
  await p.evaluate(() => fetch("/api/voices", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ speakers: { kokoro: { en: "af_bella" } } }) }));
  await p.getByRole("button", { name: "Listen to this Section" }).click();  // another speaker: a job that waits in the paused queue
  await p.getByRole("button", { name: "Media queue" }).click();
  const panel = p.getByRole("dialog", { name: "Media queue" });
  await panel.getByText("Paused: jobs wait after their current step").waitFor();
  await panel.getByText(/^Listen · .*\(kokoro\)$/).waitFor();
  await panel.getByRole("button", { name: /^Stop Listen · / }).click();
  await panel.getByRole("button", { name: "Resume" }).click();
  await p.getByRole("button", { name: "Media queue" }).waitFor({ state: "detached" });  // idle again: the indicator goes away
  await p.getByRole("region", { name: "Listen" }).getByText("stopped from the media queue").waitFor();
  await p.evaluate(() => fetch("/api/voices", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ speakers: { kokoro: { en: "af_heart" } } }) }));
  assert.deepEqual(p.errors, []);
});

test("Listen is a widget you drag, and a Block can be listened to alone", async () => {
  const p = await page();
  await p.goto(`${BASE}/c/1/read`);
  const block = p.locator("[data-block]").filter({ has: p.getByRole("button", { name: "Listen", exact: true }) }).nth(1);
  const id = await block.getAttribute("data-block");
  await block.getByRole("button", { name: "Listen", exact: true }).click();
  const bar = p.getByRole("region", { name: "Listen" });
  await bar.getByText("This Block ·").waitFor();
  await p.waitForFunction((id) => document.querySelector(`[data-block="${id}"]`)?.classList.contains("ring-2"), id);  // it starts at that Block
  const before = await bar.boundingBox();
  const grip = bar.getByTitle("Drag to move");
  const g = await grip.boundingBox();
  await p.mouse.move(g.x + 20, g.y + g.height / 2);
  await p.mouse.down();
  await p.mouse.move(g.x - 200, g.y - 150, { steps: 5 });
  await p.mouse.up();
  const after = await bar.boundingBox();
  assert.ok(after.x < before.x - 100 && after.y < before.y - 100, "the widget moved");
  await bar.getByText("End of the Block.").waitFor({ timeout: 15000 });  // it pauses at the Block's end
  await bar.getByRole("button", { name: "Keep listening" }).click();
  assert.deepEqual(p.errors, []);
});

test("the mic's transcript goes into the box and can be edited before it is sent", async () => {
  const mic = await chromium.launch({ args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] });
  const ctx = await mic.newContext({ permissions: ["microphone"] });
  const p = await ctx.newPage();
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  const asked = [];
  p.on("request", (r) => r.method() === "POST" && r.url().endsWith("/tutor") && asked.push(r.url()));
  await p.goto(`${BASE}/c/1/read`);
  await p.locator(".fixed button", { hasText: "Ask the tutor" }).click();
  const tutor = p.getByRole("complementary", { name: "Tutor" });
  await tutor.getByRole("button", { name: "Dictate" }).click();
  await tutor.getByRole("button", { name: "Stop dictating" }).click();
  const box = tutor.getByRole("textbox", { name: "Question" });
  await p.waitForFunction(() => document.querySelector('textarea[aria-label="Question"]')?.value.includes("bonjour"), null, { timeout: 30_000 });
  assert.equal(await box.inputValue(), "bonjour, la convexité");
  await box.fill(`${await box.inputValue()} et le gradient`);  // edited before sending
  assert.equal(await box.inputValue(), "bonjour, la convexité et le gradient");
  assert.deepEqual(asked, []);  // nothing was sent by dictating
  assert.deepEqual(errors, []);
  await mic.close();
});

test("without a secure context the mic says how to get one", async () => {
  const p = await page();
  await p.addInitScript(() => Object.defineProperty(window, "isSecureContext", { value: false }));
  await p.goto(`${BASE}/c/1/read`);
  await p.locator(".fixed button", { hasText: "Ask the tutor" }).click();
  await p.getByRole("complementary", { name: "Tutor" }).getByText("Dictation needs HTTPS: open the app through tailscale serve").waitFor();
  assert.equal(await p.getByRole("button", { name: "Dictate" }).count(), 0);
});

test("Settings: pick a Voice, install one after confirming its size, preview it and remove it", async () => {
  const p = await page();
  await p.goto(`${BASE}/settings`);
  const voice = (name) => p.getByRole("listitem", { name: `Voice ${name}` });
  await voice("Kokoro").getByText("reads Listen").waitFor();  // the default, installed
  await voice("Kokoro").getByText("Licence: Apache-2.0").waitFor();
  await voice("OmniVoice").getByText(/CC-BY-NC/).first().waitFor();
  await voice("Audio8").getByRole("button", { name: /Install · 2\.6 GB/ }).click();
  await voice("Audio8").getByText("Download about 2.6 GB?").waitFor();  // nothing downloads before this is confirmed
  assert.equal(await voice("Audio8").getByRole("button", { name: "Use Audio8" }).count(), 0);
  await voice("Audio8").getByRole("button", { name: "Download 2.6 GB" }).click();
  await voice("Audio8").getByRole("button", { name: "Use Audio8" }).click();
  await voice("Audio8").getByText("reads Listen").waitFor();
  await voice("Audio8").getByRole("button", { name: "Preview Audio8 in English" }).click();
  await voice("Kokoro").getByRole("combobox", { name: "Kokoro speaker for English" }).click();
  await p.getByRole("option", { name: "af_bella" }).click();
  await p.screenshot({ path: process.env.SMOKE_SHOTS ? join(process.env.SMOKE_SHOTS, "settings-voices.png") : undefined, fullPage: true });
  await voice("Audio8").getByRole("button", { name: "Remove" }).click();
  await voice("Kokoro").getByText("reads Listen").waitFor();  // the choice went back to the default
  assert.deepEqual(p.errors, []);
});

test("a Video shows its narration while it is pending, and a player with captions once video rendering is installed", async () => {
  const p = await page();
  await p.goto(`${BASE}/c/1/read`);
  const pending = p.getByLabel("Video, not rendered yet").filter({ hasText: "On retire cinq des deux côtés" }).first();
  await pending.getByText("On retire cinq des deux côtés pour isoler x.").waitFor();  // the narration is text meanwhile
  await pending.getByText(/Install video rendering in Settings/).waitFor();
  assert.equal(await p.locator("video").count(), 0);
  await p.goto(`${BASE}/settings`);
  const card = p.getByLabel("Video rendering");
  await card.getByRole("button", { name: /Install video rendering · 400 MB/ }).click();
  await card.getByText("Download about 400 MB?").waitFor();  // nothing downloads before this is confirmed
  await card.getByRole("button", { name: "Download 400 MB" }).click();
  await card.getByRole("button", { name: "Remove" }).waitFor();
  await p.goto(`${BASE}/c/1/read`);
  const player = p.locator("video").first();
  await player.waitFor({ timeout: 20_000 });  // queued when the page asked, rendered by the fake, picked up by the poll
  assert.match(await player.getAttribute("src"), /\/blocks\/\d+\/video\/[0-9a-f]{16}\.mp4$/);
  assert.match(await player.locator("track").getAttribute("src"), /\.vtt$/);
  await p.screenshot({ path: process.env.SMOKE_SHOTS ? join(process.env.SMOKE_SHOTS, "video.png") : undefined });
  assert.deepEqual(p.errors, []);
});
