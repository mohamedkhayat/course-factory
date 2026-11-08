"""Jupyter kernels for Labs, started through jupyter_client. In Docker: no network, CPU only, ~4 GB, stopped when idle.

The kernel talks to the app over ZMQ IPC sockets in a bind-mounted folder, so the container needs no network at all."""

import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import nbformat
from jupyter_client.blocking.client import BlockingKernelClient
from jupyter_client.connect import write_connection_file

LAB_DIR = Path(__file__).resolve().parents[2] / "lab"
LAB_IMAGE_TAG = "course-factory-lab:1"
IDLE_SECONDS = 20 * 60
MEMORY = "4g"
RUN_DIR = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "course-factory"


class Launcher(Protocol):
    def start(self, conn_file: Path, workdir: Path, data_dir: Path) -> Callable[[], object]: ...


class LocalLauncher:
    """A kernel on the host (tests and development only: no isolation)."""

    def start(self, conn_file, workdir, data_dir):
        link = workdir / "data"
        if not link.exists():
            link.symlink_to(data_dir, target_is_directory=True)
        proc = subprocess.Popen([sys.executable, "-m", "ipykernel_launcher", "-f", str(conn_file)], cwd=workdir,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return proc.kill


class DockerLauncher:
    """A kernel in the Course's pinned image: --network none, no GPU, memory capped, runs as the owner's uid."""

    def __init__(self, image: str):
        self.image = image

    def start(self, conn_file, workdir, data_dir):
        (workdir / "data").mkdir(exist_ok=True)
        name = f"cf-lab-{uuid.uuid4().hex[:10]}"
        conn = conn_file.parent
        subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "--network", "none", "--memory", MEMORY,
                        "--memory-swap", MEMORY, "--pids-limit", "256", "--user", f"{os.getuid()}:{os.getgid()}",
                        "-v", f"{conn}:{conn}", "-v", f"{workdir}:/work", "-v", f"{data_dir}:/work/data:ro", "-w", "/work",
                        self.image, "python", "-m", "ipykernel_launcher", "-f", str(conn_file)],
                       check=True, capture_output=True, text=True, timeout=120)
        return lambda: subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)


def lab_image() -> str:
    """Builds the Lab Environment if needed and returns its immutable image id (what a Course pins)."""
    out = subprocess.run(["docker", "image", "inspect", "-f", "{{.Id}}", LAB_IMAGE_TAG], capture_output=True, text=True)
    if out.returncode != 0:
        subprocess.run(["docker", "build", "-t", LAB_IMAGE_TAG, str(LAB_DIR)], check=True, capture_output=True, timeout=3600)
        out = subprocess.run(["docker", "image", "inspect", "-f", "{{.Id}}", LAB_IMAGE_TAG], capture_output=True, text=True, check=True)
    return out.stdout.strip()


class Kernel:
    def __init__(self, client: BlockingKernelClient, stop: Callable[[], object], conn_dir: Path):
        self.client, self._stop, self.conn_dir = client, stop, conn_dir
        self.last_used = time.monotonic()
        self.lock = threading.Lock()

    def execute(self, code: str, on_output: Callable[[dict], object] | None = None, silent: bool = False,
                timeout: float = 300) -> tuple[list[dict], dict | None]:
        """Runs code; returns (nbformat outputs, error or None). Silent runs show nothing (hidden Checks)."""
        with self.lock:
            self.last_used = time.monotonic()
            kc = self.client
            msg_id = kc.execute(code, silent=silent, store_history=not silent, allow_stdin=False)
            outputs: list[dict] = []
            deadline = time.monotonic() + timeout
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    return outputs, {"ename": "TimeoutError", "evalue": f"the code ran longer than {int(timeout)} s"}
                try:
                    msg = kc.get_iopub_msg(timeout=left)
                except Exception:
                    continue
                if msg["parent_header"].get("msg_id") != msg_id:
                    continue
                kind = msg["msg_type"]
                if kind == "status" and msg["content"]["execution_state"] == "idle":
                    break
                if kind in ("stream", "execute_result", "display_data", "error") and not silent:
                    out = dict(nbformat.v4.output_from_msg(msg))
                    outputs.append(out)
                    if on_output:
                        on_output(out)
            reply = kc.get_shell_msg(timeout=30)
            while reply["parent_header"].get("msg_id") != msg_id:
                reply = kc.get_shell_msg(timeout=30)
            self.last_used = time.monotonic()
            c = reply["content"]
            return outputs, ({"ename": c.get("ename", ""), "evalue": c.get("evalue", "")} if c["status"] == "error" else None)

    def stop(self):
        try:
            self.client.stop_channels()
        finally:
            self._stop()


class Kernels:
    """One kernel per key (an open Lab, or a Check proof). Idle kernels are stopped by a reaper thread."""

    def __init__(self, idle_seconds: float = IDLE_SECONDS):
        self.idle = idle_seconds
        self.kernels: dict[str, Kernel] = {}
        self.lock = threading.Lock()
        threading.Thread(target=self._reap_forever, daemon=True).start()

    def get(self, key: str, launcher: Launcher, workdir: Path, data_dir: Path) -> Kernel:
        with self.lock:
            if key in self.kernels:
                return self.kernels[key]
            workdir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            conn_dir = RUN_DIR / uuid.uuid4().hex[:10]  # short: unix socket paths are limited to ~100 bytes
            conn_dir.mkdir(parents=True)
            conn_file = conn_dir / "k.json"
            write_connection_file(str(conn_file), transport="ipc", ip=str(conn_dir / "s"))
            stop = launcher.start(conn_file, workdir, data_dir)
            kc = BlockingKernelClient(connection_file=str(conn_file))
            kc.load_connection_file()
            kc.start_channels()
            try:
                kc.wait_for_ready(timeout=120)
            except Exception:
                kc.stop_channels()
                stop()
                raise
            self.kernels[key] = Kernel(kc, stop, conn_dir)
            return self.kernels[key]

    def running(self, key: str) -> bool:
        return key in self.kernels

    def stop(self, key: str) -> None:
        with self.lock:
            k = self.kernels.pop(key, None)
        if k:
            k.stop()

    def reap(self) -> list[str]:
        now = time.monotonic()
        idle = [key for key, k in list(self.kernels.items()) if now - k.last_used > self.idle and not k.lock.locked()]
        for key in idle:
            self.stop(key)
        return idle

    def _reap_forever(self):
        while True:
            time.sleep(30)
            self.reap()

    def stop_all(self):
        for key in list(self.kernels):
            self.stop(key)
