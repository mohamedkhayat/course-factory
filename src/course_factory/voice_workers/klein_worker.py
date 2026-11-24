"""Klein-TTS-X1.5-Pro: the model's own code at the pinned revision. KLEINTTS_NO_AUTO_INSTALL=1 is always set by the app (the code
would otherwise pip-install packages the first time it is given text; Install already put them in this environment).
Checked against the real weights on the CPU."""
import os

os.environ["KLEINTTS_NO_AUTO_INSTALL"] = "1"

from proto import serve, wav_b64  # noqa: E402

REPO, REV = os.environ["CF_REPO"], os.environ["CF_REVISION"]
FALLBACK_SPEAKER = {"en": "Sarah", "fr": "Camille"}


def load():
    from huggingface_hub import snapshot_download
    from transformers import AutoModel
    path = snapshot_download(REPO, revision=REV)  # the pinned folder: given a repo name its code looks up the English lexicon at the latest
    return AutoModel.from_pretrained(path, trust_remote_code=True).eval()  # 13M parameters: the CPU is plenty


def handle(model, msg):
    voice = msg.get("speaker") or FALLBACK_SPEAKER.get(msg["language"])
    if voice is None:
        raise ValueError(f"Klein has no voice for {msg['language']}")
    out = model.tts(msg["text"], voice=voice)  # the text is read in the language of the voice
    return wav_b64(out.waveform, out.sample_rate)


if __name__ == "__main__":
    serve(load, handle)
