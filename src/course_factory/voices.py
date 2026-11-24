"""Voices: the local text-to-speech models that read Listen and narrate Videos. The registry pins each one to an exact revision;
Settings picks one, installs and removes them (an explicit click: nothing downloads otherwise) and previews it. Which Voice reads a
language: the chosen one when it has the language, else a fallback that has it."""
import json
import re

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from .context import Ctx

CPU_TORCH = ["--extra-index-url", "https://download.pytorch.org/whl/cpu", "--index-strategy", "unsafe-best-match"]
LANGUAGES = ("en", "fr")  # the Course languages a Voice has to cover (mixed Courses use both)
DEFAULT = "kokoro"
SAMPLE = {"en": "This is how your Course sounds: the gradient points toward the steepest increase.",
          "fr": "Voici comment sonne votre cours : le gradient pointe vers la plus forte croissance."}
# What every Voice is checked with: Listen never sends these to a Voice (see listen.safe_speak)
FORBIDDEN = re.compile(r"[\\$_^{}]")

# `languages` are the ones the model reads; `speakers` the named voices of a model that has several, per language (first = default).
# `packages` are installed into the Voice's own environment with exact pins; the full resolution is kept in freeze.txt next to it.
REGISTRY: dict[str, dict] = {
    "kokoro": {
        "name": "Kokoro", "repo": "hexgrad/Kokoro-82M", "revision": "f3ff3571791e39611d31c381e3a41a3af07b4987", "licence": "Apache-2.0",
        "size_mb": 363, "custom_code": False, "languages": ["en", "fr"], "default": True,
        "speakers": {"en": ["af_heart", "af_bella", "af_nicole", "am_michael", "bf_emma"], "fr": ["ff_siwis"]},
        "files": ["config.json", "kokoro-v1_0.pth", "voices/af_heart.pt", "voices/af_bella.pt", "voices/af_nicole.pt", "voices/am_michael.pt",
                  "voices/bf_emma.pt", "voices/ff_siwis.pt"],
        "packages": ["kokoro==0.9.4", "misaki[en]==0.9.4", "torch==2.15.0", "transformers==4.57.3", "huggingface_hub==0.36.2", "soundfile==0.14.0",
                     "numpy==2.5.4", "spacy==3.8.18",
                     "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"],
        "index": CPU_TORCH,
        "note": "No custom code. Reads from the pinned files only: the app never lets it download.",
    },
    "audio8": {
        "name": "Audio8", "repo": "Edge0/Audio8-TTS-Realistic-Air", "revision": "4d02073010389bdcc86e2f0bc52137b3e2ab7580", "licence": "Apache-2.0",
        "size_mb": 2600, "custom_code": True, "languages": ["en", "fr"], "speakers": {},
        "packages": ["torch==2.15.0", "transformers==4.57.3", "huggingface_hub==0.36.2", "soundfile==0.14.0", "safetensors==0.6.2", "numpy==2.5.4"],
        "index": CPU_TORCH,
        "note": "Runs the model's own code (trust_remote_code), reviewed at this revision: no network, no subprocess, weights loaded with weights_only=True. "
                "It is trusted at this revision only.",
    },
    "klein": {
        "name": "Klein", "repo": "klein-ml/Klein-TTS-X1.5-Pro", "revision": "25e0e73bebba71e5985bc369628ebdcb81bf7116", "licence": "Apache-2.0",
        "size_mb": 110, "custom_code": True, "languages": ["en", "fr"], "speakers": {"en": ["Sarah", "Owen", "Isabella"], "fr": ["Camille"]},
        "packages": ["torch==2.15.0", "transformers==4.57.3", "huggingface_hub==0.36.2", "numpy==2.5.4", "soundfile==0.14.0",
                     "regex==2026.11.9", "phonemizer-fork==3.3.2", "espeakng-loader==0.2.4"],
        "index": CPU_TORCH,
        "note": "Runs the model's own code, reviewed at this revision. Its code installs packages when first used: they are installed here "
                "instead and the worker always runs with KLEINTTS_NO_AUTO_INSTALL=1.",
    },
    "omnivoice": {
        "name": "OmniVoice", "repo": "k2-fsa/OmniVoice", "revision": "c5fdb5ccb189668d56333f77ba2629f4cd7535f4",
        "licence": "Code Apache-2.0; weights CC-BY-NC (non-commercial: fine for personal study)",
        "size_mb": 3300, "custom_code": False, "languages": ["en", "fr"], "speakers": {},
        "packages": ["omnivoice==0.2.1", "torch==2.11.0", "torchaudio==2.11.0", "transformers==5.23.0", "soundfile==0.14.0", "numpy==2.5.4"],
        "index": CPU_TORCH,
        "note": "The weights are CC-BY-NC, trained on non-commercial data: use them for study, not for anything sold.",
    },
}


# The Manim environment that renders narrated Videos: its own uv environment like a Voice's, made by the explicit Install in Settings.
# LaTeX, ffmpeg and pango are the system's. The full resolution is kept in freeze.txt next to it.
MANIM = {"name": "Manim Community", "version": "0.22.1", "licence": "MIT", "size_mb": 400,
         "packages": ["manim==0.22.1", "manimpango==0.7.1", "pycairo==1.29.2", "numpy==2.5.4", "scipy==1.18.1", "av==19.0.2"],
         "note": "Renders Videos on the CPU at low priority, from the app's own templates. Needs LaTeX, ffmpeg and pango on this machine."}


def settings(db) -> dict:
    row = db.execute("SELECT value FROM settings WHERE key='voices'").fetchone()
    return {"voice": DEFAULT, "speakers": {}, "fallback": {}, "gpu": False} | (json.loads(row["value"]) if row else {})


def speaker_of(s: dict, voice: str, language: str) -> str | None:
    names = REGISTRY[voice]["speakers"].get(language, [])
    return s["speakers"].get(voice, {}).get(language) if s["speakers"].get(voice, {}).get(language) in names else (names[0] if names else None)


def voice_for(ctx: Ctx, language: str) -> tuple[str, bool]:
    """The installed Voice that reads `language`, and whether it is a fallback for the chosen one: the chosen Voice if it has the
    language, else the fallback picked in Settings, else the first installed Voice that has it. Raises when none is installed."""
    s, have = settings(ctx.db), ctx.media.installed()  # type: ignore[union-attr]
    for v in [s["voice"], s["fallback"].get(language), *REGISTRY]:
        if v in REGISTRY and v in have and language in REGISTRY[v]["languages"]:
            return v, v != s["voice"]
    raise LookupError(f"no installed Voice reads {language}: install one in Settings")


class Change(BaseModel):
    voice: str | None = None
    speakers: dict[str, dict[str, str]] | None = None  # Voice -> language -> speaker
    fallback: dict[str, str] | None = None  # language -> Voice
    gpu: bool | None = None


class Install(BaseModel):
    confirm: bool = False


class Preview(BaseModel):
    language: str = "en"


def router(ctx: Ctx, lane) -> APIRouter:
    r = APIRouter()
    db, media = ctx.db, ctx.media
    installing: dict[str, dict] = {}  # Voice -> {"state": "running"|"failed", "log": [...]}

    def known(voice: str) -> dict:
        if voice not in REGISTRY:
            raise HTTPException(404, "no such Voice")
        return REGISTRY[voice]

    def listing() -> dict:
        s, have = settings(db), media.installed()  # type: ignore[union-attr]
        out = []
        for vid, v in REGISTRY.items():
            job = installing.get(vid)
            out.append({"id": vid, **{k: v[k] for k in ("name", "repo", "revision", "licence", "size_mb", "custom_code", "languages", "speakers", "note")},
                        "installed": vid in have, "selected": vid == s["voice"], "default": bool(v.get("default")),
                        "speaker": {l: speaker_of(s, vid, l) for l in v["speakers"]},
                        "install": {"state": job["state"], "log": job["log"][-6:]} if job else None})
        reads = {}
        for lang in LANGUAGES:
            try:
                voice, fell = voice_for(ctx, lang)
                reads[lang] = {"voice": voice, "fallback": fell, "sample": SAMPLE[lang]}
            except LookupError as e:
                reads[lang] = {"voice": None, "fallback": False, "sample": SAMPLE[lang], "error": str(e)}
        return {"voices": out, "selected": s["voice"], "fallback": s["fallback"], "gpu": s["gpu"], "reads": reads}

    @r.get("/api/voices")
    def get_voices():
        return listing()

    @r.put("/api/voices")
    def put_voices(body: Change):
        s = settings(db)
        if body.voice is not None:
            known(body.voice)
            if body.voice not in media.installed():  # type: ignore[union-attr]
                raise HTTPException(409, f"Install {REGISTRY[body.voice]['name']} first")
            s["voice"] = body.voice
        for vid, per in (body.speakers or {}).items():
            for lang, name in per.items():
                if name not in known(vid)["speakers"].get(lang, []):
                    raise HTTPException(422, f"{REGISTRY[vid]['name']} has no {lang} speaker {name}")
                s["speakers"].setdefault(vid, {})[lang] = name
        for lang, vid in (body.fallback or {}).items():
            if vid and lang not in known(vid)["languages"]:
                raise HTTPException(422, f"{REGISTRY[vid]['name']} does not read {lang}")
            s["fallback"][lang] = vid
        if body.gpu is not None:
            s["gpu"] = body.gpu
            media.gpu = body.gpu  # type: ignore[union-attr]
        db.execute("INSERT INTO settings VALUES ('voices', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(s),))
        return listing()

    @r.post("/api/voices/{vid}/install", status_code=202)
    def install(vid: str, body: Install):
        v = known(vid)
        if not body.confirm:
            raise HTTPException(422, f"Installing {v['name']} downloads about {v['size_mb']} MB: confirm it to go ahead")
        if vid in media.installed() or installing.get(vid, {}).get("state") == "running":  # type: ignore[union-attr]
            raise HTTPException(409, f"{v['name']} is installed or installing")
        job = installing[vid] = {"state": "running", "log": []}

        def work():
            try:
                media.install(vid, job["log"].append)  # type: ignore[union-attr]
                installing.pop(vid, None)
            except Exception as e:
                job.update(state="failed", log=[*job["log"][-5:], f"{type(e).__name__}: {e}"[:600]])
        lane.submit(work, kind="install", label=f"Install {v['name']}")
        return listing()

    @r.delete("/api/voices/{vid}", status_code=204)
    def remove(vid: str):
        known(vid)
        if vid not in media.installed():  # type: ignore[union-attr]
            raise HTTPException(409, "not installed")
        media.remove(vid)  # type: ignore[union-attr]
        installing.pop(vid, None)
        s = settings(db)
        if s["voice"] == vid:  # the chosen Voice is gone: back to the default
            db.execute("INSERT INTO settings VALUES ('voices', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(s | {"voice": DEFAULT}),))

    @r.post("/api/voices/{vid}/preview")
    def preview(vid: str, body: Preview):
        """The sample sentence in a language, as audio."""
        v = known(vid)
        if vid not in media.installed() or body.language not in v["languages"]:  # type: ignore[union-attr]
            raise HTTPException(409, f"{v['name']} is not installed or does not read {body.language}")
        s = settings(db)
        speech = lane.submit(lambda: media.speak(SAMPLE[body.language], body.language, vid, speaker_of(s, vid, body.language)),
                              kind="preview", label=f"Preview {v['name']}").result()  # type: ignore[union-attr]
        return Response(speech.wav, media_type="audio/wav")

    return r
