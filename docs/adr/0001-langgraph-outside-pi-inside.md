# LangGraph drives the pipeline; pi does the work inside each node

Course generation is a LangGraph graph with a SQLite checkpointer. Its `interrupt()` provides the Approval Gates and resume after a crash. Each node makes one pi call (Qwen 3.8 via llama-swap) through a single `run_pi_step` seam, and the output is validated against the Block schemas.

We use two frameworks on purpose. pi alone has no durable state or pauses. LangGraph alone would lose pi's agent loop (file tools, retries) over long PDFs. A hand-rolled step runner in SQLite was the cheaper option, but it would mean re-implementing resume and pauses.

Prompts, skills and checks live as versioned files under `harness/`, and every pi step writes a Trace. That lets a harness2-style optimizer be added later without touching the nodes.
