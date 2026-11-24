"""The media seam: the local engines (text to speech, speech to text; later Manim) behind one object on the app context, faked
in tests the way the model is. The real one runs each engine as a worker process at low priority, speaking line-delimited
JSON on stdin/stdout. A Voice's worker lives in its own uv environment under the data dir; nothing here downloads except Install."""
import base64
import io
import json
import os
import select
import shutil
import subprocess
import sys
import threading
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .voices import FORBIDDEN, MANIM, REGISTRY

WORKERS = Path(__file__).parent / "voice_workers"
VIDEO_WORKER = Path(__file__).parent / "video_workers" / "render.py"
RENDER_WAIT = 3600.0  # seconds a Video may take to render
NICE = ["nice", "-n", "19"]
REPLY_WAIT = 900.0  # seconds a worker may take for one request; past that it is killed
IDLE_WHISPER = 300.0  # the Dictation worker holds ~500 MB: it stops after this long unused


@dataclass
class Speech:
    wav: bytes
    duration: float
    sentences: list[tuple[float, float]]  # start and end (s) of each sentence in the audio


class Media(Protocol):
    gpu: bool

    def speak(self, text: str, language: str, voice: str, speaker: str | None = None) -> Speech: ...
    def transcribe(self, audio: Path, languages: list[str]) -> str: ...
    def installed(self) -> set[str]: ...
    def install(self, voice: str, log: Callable[[str], object]) -> None: ...
    def remove(self, voice: str) -> None: ...
    def video_installed(self) -> bool: ...
    def install_video(self, log: Callable[[str], object]) -> None: ...
    def remove_video(self) -> None: ...
    def render(self, spec: dict, audio: Path, out: Path) -> None:
        """Renders a Video: the template's scene spec and its narration (a WAV as long as the scenes) into out.mp4 and out.png (the poster)."""

    def retime(self, picture: Path, old: list[float], new: list[float], audio: Path, out: Path) -> None:
        """A rendered picture (scene lengths `old`) fitted to another narration (`new`) into out.mp4 and out.png."""


def speak_checked(media: Media, text: str, language: str, voice: str, speaker: str | None = None) -> Speech:
    """The only way anything is spoken: text with a backslash, dollar, underscore, caret or brace never reaches a Voice."""
    if FORBIDDEN.search(text):
        raise ValueError(f"refusing to speak text with a symbol in it: {text[:80]!r}")
    return media.speak(text, language, voice, speaker)


def wav_length(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as w:
        return w.getnframes() / w.getframerate()


class Worker:
    """One child process, one request at a time: a JSON line in, a JSON line out. It says {"ready": true} when its model is loaded."""

    def __init__(self, argv: list[str], env: dict[str, str], log: Path):
        log.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.proc = subprocess.Popen([*NICE, *argv], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=open(log, "ab"),
                                     env={**os.environ, **env}, text=True, bufsize=1)
        self.read()

    def read(self) -> dict:
        assert self.proc.stdout is not None
        if not select.select([self.proc.stdout], [], [], REPLY_WAIT)[0]:
            self.stop()
            raise TimeoutError("the worker did not answer in time")
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("the worker stopped: see worker.log next to its environment")
        msg = json.loads(line)
        if msg.get("error"):
            raise RuntimeError(msg["error"])
        return msg

    def call(self, msg: dict) -> dict:
        assert self.proc.stdin is not None
        with self.lock:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
            return self.read()

    def stop(self):
        self.proc.kill()
        self.proc.wait()


class LocalMedia:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "voices"
        self.video = data_dir / "video"
        self.gpu = False  # off by default: Voices run on the CPU
        self.tts: tuple[str, Worker] | None = None  # the one Voice loaded now
        self.whisper: Worker | None = None
        self.idle: threading.Timer | None = None
        self.lock = threading.Lock()

    def python(self, voice: str) -> Path:
        return self.root / voice / "venv" / "bin" / "python"

    def installed(self) -> set[str]:
        return {v for v in REGISTRY if (self.root / v / "installed.json").exists()}

    def speak(self, text: str, language: str, voice: str, speaker: str | None = None) -> Speech:
        with self.lock:
            if self.tts is None or self.tts[0] != voice:
                if self.tts:
                    self.tts[1].stop()
                self.tts = None
                v = REGISTRY[voice]
                env = {"HF_HUB_OFFLINE": "1", "KLEINTTS_NO_AUTO_INSTALL": "1", "CF_REPO": v["repo"], "CF_REVISION": v["revision"],
                       "CF_VOICE_GPU": "1" if self.gpu else "0", "CF_FILES": json.dumps(v.get("files", []))}
                self.tts = (voice, Worker([str(self.python(voice)), str(WORKERS / f"{voice}_worker.py")], env, self.root / voice / "worker.log"))
            worker = self.tts[1]
        reply = worker.call({"op": "speak", "text": text, "language": language, "speaker": speaker})
        wav = base64.b64decode(reply["wav_b64"])
        d = wav_length(wav)
        return Speech(wav, d, [(0.0, d)])  # one sentence per call: Listen sends sentences one by one

    def transcribe(self, audio: Path, languages: list[str]) -> str:
        with self.lock:
            if self.idle:
                self.idle.cancel()
            if self.whisper is None:  # the main environment has faster-whisper; the model is the cached `small`, never downloaded
                self.whisper = Worker([sys.executable, str(WORKERS / "whisper.py")], {"HF_HUB_OFFLINE": "1"}, self.root / "whisper.log")
            worker = self.whisper
        try:
            return worker.call({"op": "transcribe", "path": str(audio), "languages": languages})["text"]
        finally:
            with self.lock:
                self.idle = threading.Timer(IDLE_WHISPER, self.stop_whisper)
                self.idle.daemon = True
                self.idle.start()

    def stop_whisper(self):
        with self.lock:
            if self.whisper:
                self.whisper.stop()
                self.whisper = None

    def stop(self):
        self.stop_whisper()
        with self.lock:
            if self.tts:
                self.tts[1].stop()
                self.tts = None

    def run(self, argv: list[str], log: Callable[[str], object], env: dict[str, str] | None = None):
        log("$ " + " ".join(argv[:6]) + (" …" if len(argv) > 6 else ""))
        p = subprocess.Popen([*NICE, *argv], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env={**os.environ, **(env or {})})
        assert p.stdout is not None
        tail: list[str] = []
        for line in p.stdout:
            tail = [*tail[-8:], line.rstrip()]
            log(line.rstrip()[:300])
        if p.wait():
            raise RuntimeError(f"{argv[0]} failed ({p.returncode}): " + " | ".join(tail[-3:]))

    def install(self, voice: str, log: Callable[[str], object]) -> None:
        """Creates the Voice's own environment with its pinned packages, then downloads its pinned revision into the HF cache."""
        v, home = REGISTRY[voice], self.root / voice
        try:
            shutil.rmtree(home / "venv", ignore_errors=True)
            self.run(["uv", "venv", "--python", "3.12", str(home / "venv")], log)
            py = str(self.python(voice))
            self.run(["uv", "pip", "install", "--python", py, *v.get("index", []), *v["packages"]], log)
            code = ("import sys, json; from huggingface_hub import snapshot_download as d; "
                    "d(sys.argv[1], revision=sys.argv[2], allow_patterns=json.loads(sys.argv[3]) or None)")
            self.run([py, "-c", code, v["repo"], v["revision"], json.dumps(v.get("files", []))], log, {"HF_HUB_OFFLINE": "0"})
            freeze = subprocess.run(["uv", "pip", "freeze", "--python", py], capture_output=True, text=True).stdout
            (home / "freeze.txt").write_text(freeze)
            (home / "installed.json").write_text(json.dumps({"revision": v["revision"], "packages": v["packages"]}))
        except BaseException:
            shutil.rmtree(home / "venv", ignore_errors=True)  # a half-made environment is not an installed Voice
            raise

    def remove(self, voice: str) -> None:
        with self.lock:
            if self.tts and self.tts[0] == voice:
                self.tts[1].stop()
                self.tts = None
        shutil.rmtree(self.root / voice, ignore_errors=True)  # the weights stay in the HF cache: reinstalling needs no download

    def video_installed(self) -> bool:
        return (self.video / "installed.json").exists()

    def install_video(self, log: Callable[[str], object]) -> None:
        """Creates the Manim environment with its pinned packages."""
        try:
            shutil.rmtree(self.video / "venv", ignore_errors=True)
            self.run(["uv", "venv", "--python", "3.12", str(self.video / "venv")], log)
            py = str(self.video / "venv" / "bin" / "python")
            self.run(["uv", "pip", "install", "--python", py, *MANIM["packages"]], log)
            self.run([py, "-c", "import manim"], log, {"PYTHONWARNINGS": "ignore"})
            (self.video / "freeze.txt").write_text(subprocess.run(["uv", "pip", "freeze", "--python", py], capture_output=True, text=True).stdout)
            (self.video / "installed.json").write_text(json.dumps({"version": MANIM["version"], "packages": MANIM["packages"]}))
        except BaseException:
            shutil.rmtree(self.video, ignore_errors=True)
            raise

    def remove_video(self) -> None:
        shutil.rmtree(self.video, ignore_errors=True)

    def render(self, spec: dict, audio: Path, out: Path) -> None:
        spec_path = out.with_suffix(".json")
        spec_path.write_text(json.dumps(spec))
        try:
            done = subprocess.run([*NICE, str(self.video / "venv" / "bin" / "python"), str(VIDEO_WORKER), str(spec_path), str(audio), str(out)],
                                  capture_output=True, text=True, timeout=RENDER_WAIT, env={**os.environ, "PYTHONWARNINGS": "ignore"})
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"the render took more than {int(RENDER_WAIT)} s and was stopped")
        finally:
            spec_path.unlink(missing_ok=True)
        if done.returncode:
            raise RuntimeError(f"manim render failed ({done.returncode}):\n" + (done.stdout + done.stderr)[-2500:])

    def retime(self, picture: Path, old: list[float], new: list[float], audio: Path, out: Path) -> None:
        """A Video's picture, rendered for another narration, fitted to this one: each scene's still end is cut, or its last frame
        held longer (the caller never cuts into an animation). Writes out.mp4 and out.png in seconds, without Manim."""
        parts, at = [], 0.0
        for i, (o, n) in enumerate(zip(old, new)):
            parts.append(f"[0:v]trim=start={at:.3f}:duration={min(o, n):.3f},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={max(0.0, n - o):.3f}[v{i}]")
            at += o
        graph = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[v]"
        try:
            for cmd in (["ffmpeg", "-y", "-loglevel", "error", "-i", str(picture), "-i", str(audio), "-filter_complex", graph, "-map", "[v]", "-map", "1:a",
                         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out)],
                        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.1, new[0] - 0.3):.2f}", "-i", str(out), "-frames:v", "1", str(out.with_suffix(".png"))]):
                subprocess.run([*NICE, *cmd], check=True, capture_output=True, text=True, timeout=RENDER_WAIT)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"ffmpeg could not fit the picture to the narration:\n{e.stderr[-2500:]}")
