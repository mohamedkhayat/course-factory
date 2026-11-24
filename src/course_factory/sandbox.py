"""Course files for the chat's shell tool: a throwaway container per answer, the Course's sources and their read text
mounted read-only at /course, no network, memory and processes capped, run as the owner's uid."""
import os
import subprocess
import uuid
from contextlib import contextmanager
from pathlib import Path

from .context import Ctx

MEMORY = "2g"
TEXT_DIR = "files_text"  # under the Course's folder: one .txt per source, rewritten before each container starts


def export_text(ctx: Ctx, cid: int) -> Path:
    """Every non-excluded source's read page text as <name>.txt with a "=== page N ===" line before each page, so grep finds a
    page number to cite. Names keep their folders (chap3/x.pdf -> chap3/x.pdf.txt)."""
    root = ctx.course_dir(cid) / TEXT_DIR
    root.mkdir(parents=True, exist_ok=True)
    for src in ctx.db.execute("SELECT id, name FROM sources WHERE course_id=? AND excluded=0", (cid,)).fetchall():
        path = (root / f"{src['name']}.txt").resolve()
        if not path.is_relative_to(root.resolve()):
            continue  # a name with ".." never leaves the folder
        path.parent.mkdir(parents=True, exist_ok=True)
        pages = ctx.db.execute("SELECT n, text FROM pages WHERE source_id=? ORDER BY n", (src["id"],)).fetchall()
        path.write_text("".join(f"=== page {p['n']} ===\n{p['text'] or '(not read yet)'}\n\n" for p in pages))
    return root


@contextmanager
def course_box(ctx: Ctx, cid: int, image: str):
    """A running container named by the yielded string, removed on exit. /course/sources: the uploaded files; /course/text:
    their read text; /tmp: scratch."""
    text = export_text(ctx, cid)
    sources = ctx.course_dir(cid) / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    name = f"cf-files-{cid}-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "--network", "none", "--memory", MEMORY, "--memory-swap", MEMORY,
                    "--pids-limit", "128", "--cpus", "2", "--read-only", "--tmpfs", "/tmp", "--user", f"{os.getuid()}:{os.getgid()}",
                    "-v", f"{sources}:/course/sources:ro", "-v", f"{text}:/course/text:ro", "-w", "/course", "-e", "HOME=/tmp",
                    image, "sleep", "1800"], check=True, capture_output=True, text=True, timeout=120)
    try:
        yield name
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
