import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from course_factory.app import create_app
from course_factory.kernels import Kernels
from conftest import FakeModel, FakeSearch

SPAWN = """
import sys, time
from pathlib import Path
from course_factory.kernels import Kernels, LocalLauncher
k = Kernels().get("lab-1", LocalLauncher(), Path(sys.argv[1]), Path(sys.argv[2]))
print(k.client.connection_file, flush=True)
time.sleep(600)
"""


def kernel_pids(workdir: Path) -> list[int]:
    out = subprocess.run(["pgrep", "-f", "ipykernel_launcher"], capture_output=True, text=True).stdout.split()
    return [int(p) for p in out if Path(f"/proc/{p}/cwd").exists() and Path(f"/proc/{p}/cwd").resolve() == workdir.resolve()]


def test_a_kernel_exits_when_the_app_is_killed(tmp_path):
    work = tmp_path / "work"
    app = subprocess.Popen([sys.executable, "-c", SPAWN, str(work), str(tmp_path / "data")], stdout=subprocess.PIPE, text=True)
    try:
        app.stdout.readline()  # the kernel is ready
        assert len(kernel_pids(work)) == 1
        os.kill(app.pid, signal.SIGKILL)  # no shutdown hook runs
        deadline = time.monotonic() + 15
        while kernel_pids(work) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert kernel_pids(work) == []
    finally:
        app.kill()
        for pid in kernel_pids(work):
            os.kill(pid, signal.SIGKILL)


def test_stopping_the_app_stops_its_kernels(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(Kernels, "stop_all", lambda self: calls.append(self))
    with TestClient(create_app(tmp_path / "data", FakeModel(), FakeSearch())):
        assert calls == []
    assert len(calls) == 1
