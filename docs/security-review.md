# Security review (2026-11-11)

Scope: the app as one owner runs it on their own machine, with an optional paired tablet on the home network. The question asked: can anything put the machine at risk? Covers the FastAPI app, the model steps, the Labs, the web app and its npm packages.

## Threat model

- **The owner** on the host (loopback) is trusted.
- **A paired device** (the tablet) is trusted like the owner once paired.
- **Untrusted:** web pages open in the owner's browser, other machines on the LAN, and every piece of content the app did not write itself: course PDFs, uploaded copies, and above all **model output** (Block data, Component code, Lab code, tutor replies).

## What protects the machine

| Surface | Protection |
|---|---|
| Network | Binds 127.0.0.1 by default (`CF_HOST`). `PairingGuard` refuses any Host that is not an IP literal or `localhost` (DNS rebinding), and any request whose Origin differs from its Host (cross-site requests from a page in the browser). Non-loopback clients need a device token: a one-time six-digit code, revoked after 5 failed claims, in an `HttpOnly`, `SameSite=Strict` cookie. |
| Model steps | `pi` runs with `--no-tools` / `--no-builtin-tools --no-mcp --no-extensions` (only `cf_return_result`), `--no-skills --no-context-files`. The model can't run commands or read files beyond the attached pages. Its output is parsed into pydantic schemas. |
| Lab code (learner and model) | `DockerLauncher`: `--network none`, 4 GB memory and swap, 256 pids, runs as the owner's uid (not root), course data mounted read-only. `LocalLauncher` (no isolation) is only used by the tests. |
| Model-made Components | Gated (strict tsc, import allowlist: `react` only, no `require` or dynamic import), then run only in an `<iframe sandbox="allow-scripts">` (no same-origin) with a CSP of `default-src 'none'`: no network, no access to the app or its cookie. |
| Model text in the page | react-markdown without raw HTML; KaTeX with `trust` off; Mermaid with `securityLevel: "strict"`. The exported HTML escapes `<` in the embedded JSON, so no `</script>` can break out. |
| Math the learner types | mathjs's own parser (`compile`), never JS `eval`; `constructor` escapes are refused (checked on mathjs 15.2). |
| Uploads | 40 MB cap; images by declared type only (PNG, JPEG, WebP), stored under random names in the Course folder; PDFs rendered to PNGs. |

## Fixed in this pass

- **An uploaded PDF had no page limit.** A small crafted PDF of thousands of pages renders every page as a PNG at 2×, which fills the disk. Now at most 40 pages, else 413 (test in `tests/test_learner.py`).
- **npm advisories, `npm audit`: 14 → 0.**
  - **vite** 6.3.5 → 6.4.5, which fixes dev-server file read and path traversal. This mattered: `npm run dev` serves the repo.
  - **mathjs** 14.5 → 15.2: an unsafe object property setter.
  - **katex** 0.16 → 0.19.1: prototype pollution could bypass `trust`. One copy now via `overrides`, so rehype-katex and mermaid use it too.
  - **lodash-es, chevrotain, langium, @mermaid-js/parser:** `npm audit fix`, within their ranges.
  - Versions published in the last two weeks were avoided (vite 6.4.6).

## Accepted risks

- **Plain HTTP on the LAN.** With `CF_HOST=0.0.0.0` for the tablet, the device token travels unencrypted, so anyone on the same Wi-Fi can capture it. Pair only on a trusted network. If in doubt, revoke the device from the host with `curl -X POST localhost:8765/api/pairing/devices/<id>/revoke` (ids come from `GET /api/pairing/devices`; there is no button for it yet).
- **A paired device can do everything the owner can.** That includes creating a Course from any folder path on the host (only course material files are copied), and starting Runs.
- **Uploaded images aren't decoded to check that they are images.** They are served back with the image type of their extension, so a browser won't run them as a page.
- **Python dependencies weren't audited in this pass**: fetching `pip-audit` was blocked here. Run `uvx pip-audit` (or `uv run --with pip-audit pip-audit`) on the next update.
