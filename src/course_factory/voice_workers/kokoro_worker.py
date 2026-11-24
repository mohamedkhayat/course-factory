"""Kokoro-82M: the `kokoro` package on the pinned revision. Files are resolved from the local cache at that revision (the package
would otherwise fetch the latest), and HF_HUB_OFFLINE keeps it from downloading anything. Checked against the real weights on the CPU."""
import os

from proto import device, serve, wav_b64

REPO, REV = os.environ["CF_REPO"], os.environ["CF_REVISION"]
CODES = {"en": "a", "fr": "f"}  # Kokoro's language codes: American English, French
FALLBACK_SPEAKER = {"en": "af_heart", "fr": "ff_siwis"}


def load():
    from huggingface_hub import hf_hub_download
    from kokoro import KModel, KPipeline
    get = lambda name: hf_hub_download(REPO, name, revision=REV)
    model = KModel(repo_id=REPO, config=get("config.json"), model=get("kokoro-v1_0.pth")).to(device()).eval()
    return {"model": model, "pipes": {}, "get": get}


def handle(st, msg):
    lang = msg["language"]
    if lang not in CODES:
        raise ValueError(f"Kokoro does not read {lang}")
    if lang not in st["pipes"]:
        from kokoro import KPipeline
        st["pipes"][lang] = KPipeline(lang_code=CODES[lang], repo_id=REPO, model=st["model"], device=device())
    voice = st["get"](f"voices/{msg.get('speaker') or FALLBACK_SPEAKER[lang]}.pt")  # a path: the package loads it as it is
    parts = [audio for _, _, audio in st["pipes"][lang](msg["text"], voice=voice, speed=1.0) if audio is not None]
    if not parts:
        raise ValueError("no audio came out")
    import numpy as np
    return wav_b64(np.concatenate([p.numpy() for p in parts]), 24000)


if __name__ == "__main__":
    serve(load, handle)
