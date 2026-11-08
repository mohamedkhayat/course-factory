"""The Lab Environment for real: Docker, the pinned image, no network, memory capped, idle kernels stopped."""

import shutil

import pytest

from course_factory.kernels import DockerLauncher, Kernels, lab_image

pytestmark = [pytest.mark.slow, pytest.mark.skipif(shutil.which("docker") is None, reason="no docker")]


@pytest.fixture(scope="module")
def image():
    return lab_image()


@pytest.fixture
def kernel(image, tmp_path):
    ks = Kernels(idle_seconds=0.5)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "data.csv").write_text("x\n4\n")
    k = ks.get("t", DockerLauncher(image), tmp_path / "work", tmp_path / "data")
    yield ks, k
    ks.stop_all()


def test_scientific_stack_data_and_no_network(kernel):
    _, k = kernel
    out, err = k.execute("import pandas as pd, numpy, scipy, sympy, sklearn\nprint(int(pd.read_csv('data/data.csv')['x'][0]))")
    assert err is None and out[0]["text"] == "4\n"
    _, err = k.execute("import urllib.request\nurllib.request.urlopen('http://1.1.1.1', timeout=3)")
    assert err is not None  # --network none
    _, err = k.execute("open('data/new.txt', 'w')")
    assert err is not None  # the Course's material is read-only


def test_memory_is_capped(kernel):
    _, k = kernel
    _, err = k.execute("b = bytearray(6 * 1024**3)", timeout=60)  # more than the 4 GB cap: the kernel dies or refuses
    assert err is not None


def test_check_rejects_mutant_and_idle_kernel_is_reaped(kernel):
    ks, k = kernel
    k.execute("def f(x):\n    return 2*x")
    _, err = k.execute("assert f(3) == 9, 'f(3) should be 9'", silent=True)
    assert err == {"ename": "AssertionError", "evalue": "f(3) should be 9"}
    import time
    time.sleep(1)
    assert ks.reap() == ["t"] and not ks.running("t")
