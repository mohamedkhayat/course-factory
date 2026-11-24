"""The worker side of the media seam: a JSON line in on stdin, a JSON line out on stdout. These scripts run inside a Voice's own
environment, not the app's, so they import nothing from course_factory."""
import base64
import io
import json
import os
import sys
import wave


def serve(load, handle):
    out = os.fdopen(os.dup(1), "w", buffering=1)  # the real stdout, for replies only
    os.dup2(2, 1)  # whatever a library prints goes to the log
    sys.stdout = sys.stderr

    def reply(msg):
        out.write(json.dumps(msg) + "\n")
        out.flush()

    try:
        model = load()
    except Exception as e:
        reply({"error": f"loading failed: {type(e).__name__}: {e}"})
        raise
    reply({"ready": True})
    for line in sys.stdin:
        try:
            reply(handle(model, json.loads(line)))
        except Exception as e:  # one bad request does not stop the worker
            reply({"error": f"{type(e).__name__}: {e}"[:600]})


def device():
    """CPU unless Settings turned the GPU on and this Voice's torch is a CUDA build (installs use the CPU build)."""
    if os.environ.get("CF_VOICE_GPU") != "1":
        return "cpu"
    import torch
    if torch.cuda.is_available():
        return "cuda"
    print("GPU asked for, but this Voice's torch has no CUDA: running on the CPU", file=sys.stderr)
    return "cpu"


def wav_b64(samples, rate: int) -> dict:
    """Float samples in [-1, 1] (a numpy array or a list) as a 16-bit mono WAV."""
    import numpy as np
    pcm = (np.clip(np.asarray(samples, dtype="float32").reshape(-1), -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return {"wav_b64": base64.b64encode(buf.getvalue()).decode()}
