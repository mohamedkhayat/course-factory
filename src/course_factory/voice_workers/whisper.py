"""Dictation: faster-whisper `small` on the CPU, int8, from the local HF cache only (never downloaded), limited to the languages
the Course uses. Runs in the app's own environment."""
import os

from proto import serve

os.environ.setdefault("HF_HUB_OFFLINE", "1")


def load():
    from faster_whisper import WhisperModel
    return WhisperModel("small", device="cpu", compute_type="int8", local_files_only=True)


def handle(model, msg):
    from faster_whisper import decode_audio
    langs = msg["languages"]
    audio = decode_audio(msg["path"], sampling_rate=16000)  # webm/opus from a browser, WAV, whatever PyAV reads
    if len(langs) == 1:
        language = langs[0]
    else:  # the best of the allowed languages, not whichever of 99 Whisper would guess
        _, _, probs = model.detect_language(audio)
        language = max(langs, key=lambda l: dict(probs).get(l, 0.0))
    segments, _ = model.transcribe(audio, language=language, beam_size=1)
    return {"text": " ".join(s.text.strip() for s in segments).strip()}


if __name__ == "__main__":
    serve(load, handle)
