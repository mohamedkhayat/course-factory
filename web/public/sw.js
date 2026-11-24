// Lets the app install to a tablet's home screen. Nothing is cached: Courses live on the PC and change, so pages always come
// from the network; without it, opening the app says so instead of showing the browser's offline page.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  if (e.request.mode !== "navigate") return;  // API calls, streams and assets go straight to the network
  e.respondWith(fetch(e.request).catch(() => new Response(
    "<!doctype html><meta name=viewport content='width=device-width'><title>course-factory</title>"
    + "<body style='font:16px system-ui;padding:2rem;background:#faf8f3;color:#1e2f55'><h1>Can't reach course-factory</h1>"
    + "<p>The PC running it is off, asleep, or off Tailscale. Start it, then pull down to reload.</p>",
    { headers: { "content-type": "text/html; charset=utf-8" } })));
});
