"""OmniVoice: the `omnivoice` package on the pinned revision. Weights are CC-BY-NC. Checked against the real weights on the CPU."""
import os

from proto import device, serve, wav_b64

REPO, REV = os.environ["CF_REPO"], os.environ["CF_REVISION"]


def load():
    import torch
    from huggingface_hub import snapshot_download
    from omnivoice import OmniVoice
    dev = device()
    path = snapshot_download(REPO, revision=REV)  # the pinned snapshot's folder: given a repo name the package looks up the latest
    return OmniVoice.from_pretrained(path, device_map="cuda:0" if dev == "cuda" else "cpu",
                                     dtype=torch.float16 if dev == "cuda" else torch.float32)


def handle(model, msg):
    audio = model.generate(text=msg["text"])  # a list of numpy arrays at 24 kHz; no reference voice
    return wav_b64(audio[0], 24000)


if __name__ == "__main__":
    serve(load, handle)
