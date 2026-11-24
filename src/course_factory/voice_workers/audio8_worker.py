"""Audio8-TTS-Realistic-Air: the model's own code (trust_remote_code), reviewed at the pinned revision only.
Checked against the real weights on the CPU."""
import os

from proto import device, serve, wav_b64

REPO, REV = os.environ["CF_REPO"], os.environ["CF_REVISION"]


def load():
    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoModel, AutoProcessor
    dev = device()
    path = snapshot_download(REPO, revision=REV)  # the pinned folder: by repo name and revision the processor class is not found
    processor = AutoProcessor.from_pretrained(path, trust_remote_code=True)
    model = AutoModel.from_pretrained(path, trust_remote_code=True,
                                      dtype=torch.bfloat16 if dev == "cuda" else torch.float32).eval().to(dev)
    return processor, model, dev


def handle(st, msg):
    import torch
    processor, model, dev = st
    inputs = processor(text=[msg["text"]], return_tensors="pt")
    inputs = {k: v.to(dev) for k, v in inputs.items()}
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=1024, temperature=0.8, top_p=0.95, top_k=50, do_sample=True, return_dict_in_generate=True)
        waveforms, lengths = model.decode_audio(out.codes)
    return wav_b64(waveforms[0, : int(lengths[0])].float().cpu().numpy(), model.config.codec_sample_rate)


if __name__ == "__main__":
    serve(load, handle)
