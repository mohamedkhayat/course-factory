# Lab runtime: what runs course labs

Resolves issue #3. Part of #1.

## Question

Which runtime should run the in-app labs? The owner writes mostly Python (numpy, scipy, matplotlib, sympy, plus per-course extras) and needs plots, tables and math inline. Not LeetCode-style tests.

## Machine (read-only checks, no images pulled)

- Docker server 29.9.2 is running. No images are pulled for this work. Local images present: pi-bench, pgvector, nikolaik/python-nodejs, qdrant.
- GPU: NVIDIA GeForce RTX 5090, 32 GB VRAM, driver 615.71.09.
- RAM: 60 GiB total, about 52 GiB available. 32 CPU cores.
- Container GPU access (NVIDIA Container Toolkit) was not checked. It is needed only for the later ML labs.

## Primary-source facts

- **Pyodide 314.0.7** ships numpy 2.4.6, scipy 1.18.0, matplotlib 3.10.8 and sympy 1.14.0 as built-in packages. Other pure-Python wheels install with `micropip`. plotly is not on the built-in list. Source: pyodide.org packages page.
- **JupyterLite** is a static site with Pyodide as its kernel (via xeus-python for the other kernel path). The deploy page does not say whether it works offline, how big the kernel download is, or what the storage limits are. Those points are unverified.
- **Jupyter messaging spec** (jupyter-client docs): a client sends `execute_request`. The kernel publishes `busy`, then `stream`, `display_data`, `execute_result` and `error` on IOPub, then `idle`, and replies `execute_reply` on shell. Outputs come as MIME bundles, and a frontend ignores MIME types it does not understand. `display_id` allows updating an output in place. This is what makes matplotlib PNG/SVG and sympy LaTeX (via `text/latex`) renderable in a React output pane.
- **jupyter_kernel_gateway**: the README describes it as a headless kernel server. Its maintenance status and latest release could not be confirmed from the fetch. Check before depending on it. Jupyter Server with the kernel REST and WebSocket API is the safer default.
- **marimo**: Apache-2.0. Reactive notebooks run as `.py` files. It can run in the browser through WASM, and `marimo run` serves a notebook as an app. Its docs in the fetch did not cover sympy or matplotlib output specifics. Its own server is a second runtime to operate beside Jupyter.
- **code-server** (coder): MIT. Default auth is a password and the default bind is `127.0.0.1:8080`. The fetched page did not say whether it can be framed inside another page. Treat iframe embedding as unverified and expect it to need extra header or proxy work.

## Comparison

| Criterion | Jupyter kernel per course (Docker) | JupyterLite / Pyodide (browser) | code-server / OpenVSCode | marimo |
|---|---|---|---|---|
| Rich output (matplotlib, plotly, sympy LaTeX) | Full: any MIME type over IOPub | matplotlib and sympy yes (built in); plotly needs a wheel, unverified | Only via a notebook extension; not a native output pane | Good, but its output model is its own, not Jupyter's |
| Start latency | Container plus kernel start, seconds; kernel can be kept warm | Pyodide download on first load (size unverified), then fast | Seconds to start the server; the VS Code UI is heavy | Server start, seconds |
| Per-course dependency images | Yes: one image per course, pinned | No: one shared Pyodide set; extras by micropip | Yes, but the env is a whole dev box | Per-course via uv/venv or container |
| Isolation | Strong: container per course, resource limits | Browser sandbox; no host access | Shell access to the container; weaker unless containerized | Process-level unless containerized |
| Offline use | Yes, once images are local | Possible once cached (unverified) | Yes if local | Yes if local |
| Running checks on owner code | Easy: execute code in the kernel, read outputs and errors | Easy in the page, but checks run in the owner's browser | Possible through the terminal; no structured output | Easy: a notebook is a Python module, so tests can import it |
| Embedding in React | Use CodeMirror 6 or Monaco for the editor and render MIME outputs ourselves; the protocol is documented | Iframe the JupyterLite app; limited control of the UI | Iframe; framing unverified; heavy | Iframe of `marimo run`, or the WASM build |
| Fit for this machine | Fits: Docker present, 60 GiB RAM, 32 cores | Fits; no server | Fits, but over-built for the need | Fits |

## Recommendation

Use a **Jupyter kernel per course in a Docker container**, driven through Jupyter Server's REST and WebSocket API (or `jupyter_client` from a FastAPI service). Put a CodeMirror 6 editor in React and render the IOPub MIME outputs (PNG/SVG for plots, `text/latex` for sympy, HTML for tables) in our own output pane. Each course gets a pinned image that adds its extra packages, and the owner's code runs in a container, not on the host.

Keep **Pyodide** as a fallback for offline-only, light courses whose packages are all built in (numpy, scipy, matplotlib, sympy). Do not build on code-server: it brings a full IDE to iframe and does not give structured outputs. Keep **marimo** on a watch list; it is a good fit for the reactive notebook experience, but adopting it would add a second runtime.

Before building, check: (1) Jupyter Server vs kernel_gateway status, (2) the Pyodide first-load size for the built-in set, (3) container GPU access for the later ML labs.

## Not verified

- Startup times for either runtime (no benchmarks run).
- code-server and marimo iframe embedding behaviour.
- JupyterLite offline size and storage limits.
- Image sizes for per-course Docker images.
