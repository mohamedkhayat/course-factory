"""Renders one Video in the Manim environment: `python render.py spec.json narration.wav out.mp4`. The spec is the template's name, its
parameters and each scene's length; the narration is already as long as the scenes together. Writes out.mp4 (picture and narration)
and out.png (a poster: the first scene's finished picture), and keeps the silent picture (out.picture) with when each scene's
animations end (out.holds.json), so another Voice's narration is fitted to it without rendering again. Imports nothing from course_factory."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from manim import config, tempconfig

sys.path.insert(0, str(Path(__file__).parent))
from scenes import TEMPLATES  # noqa: E402


def main(spec_path: str, audio: str, out: str):
    spec = json.loads(Path(spec_path).read_text())
    out_path = Path(out)
    with tempfile.TemporaryDirectory() as tmp, tempconfig({"media_dir": tmp, "pixel_width": 1280, "pixel_height": 720, "frame_rate": 30,
                                                         "disable_caching": True, "progress_bar": "none", "verbosity": "WARNING", "format": "mp4",
                                                         "output_file": "scenes"}):
        scene = TEMPLATES[spec["template"]](spec)
        scene.render()
        silent = Path(scene.renderer.file_writer.movie_file_path)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", audio, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
                        "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out_path)], check=True)
        shutil.copyfile(silent, out_path.with_suffix(".picture"))
        out_path.with_suffix(".holds.json").write_text(json.dumps([scene.holds.get(i) for i in range(len(spec["durations"]))]))
        poster_at = max(0.1, spec["durations"][0] - 0.3)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{poster_at:.2f}", "-i", str(silent), "-frames:v", "1", str(out_path.with_suffix(".png"))], check=True)
    assert out_path.stat().st_size > 0


if __name__ == "__main__":
    main(*sys.argv[1:4])
