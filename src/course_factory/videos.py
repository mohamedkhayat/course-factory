"""Videos: a `video` Block is a template (video_templates.py) filled with parameters and narrated. Once its Section is checked, a job on
the media lane has the Voice speak each scene's script, fits each scene's length to its narration, and renders the template with Manim
(its own uv environment, installed from Settings) at low priority. The Run never waits: until the file exists the Block shows its
narration as text. A render that fails puts the Block in the Review Queue with the log. The file's name holds a digest of everything
it was made from (Block, Voice, template version, language), so a changed Block or Voice renders again."""
import hashlib
import io
import json
import re
import threading
import wave
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import listen, voices
from .media_queue import Stopped
from .checks import curve, heal_markdown
from .context import Ctx
from .video_templates import PLAIN, TEMPLATES, check_params

FLAG = "video: "
MIN_SCENE, PAD = 3.0, 0.8  # seconds: a scene lasts its narration plus a breath, and never less than this
WORDS = {"en": {"map": "The map of this Chapter", "partition": "Partition", "task": "task", "cached": "cached",
                "split": "The data is split into partitions; each one is worked on by its own task.",
                "narrow": "Narrow: {}. Each task works on its own partition; no record moves.",
                "wide": "Wide: {}. Records with the same key must meet, so they travel across the network: a shuffle.",
                "cache": "Cache: the result stays in memory, so the next action reuses it and does not compute it again."},
         "fr": {"map": "Le plan de ce chapitre", "partition": "Partition", "task": "tâche", "cached": "en cache",
                "split": "Les données sont découpées en partitions ; chacune est traitée par sa propre tâche.",
                "narrow": "Étroite : {}. Chaque tâche travaille sur sa partition ; aucun enregistrement ne bouge.",
                "wide": "Large : {}. Les enregistrements de même clé doivent se retrouver : ils voyagent sur le réseau, c'est un shuffle.",
                "cache": "Cache : le résultat reste en mémoire, l'action suivante le réutilise sans le recalculer."}}
FILE = re.compile(r"[0-9a-f]{16}\.(mp4|png|vtt)")


def clean(text: str, n: int) -> str:
    """Plain on-screen text of at most n characters, cut at a word."""
    t = re.sub(r"\s+", " ", PLAIN.sub(" ", text)).strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def frames(data: bytes) -> tuple[tuple, bytes]:
    with wave.open(io.BytesIO(data)) as w:
        return w.getparams()[:3], w.readframes(w.getnframes())


def vtt(cues: list[dict]) -> str:
    def t(x: float) -> str:
        return f"{int(x // 3600):02}:{int(x % 3600 // 60):02}:{x % 60:06.3f}"
    return "WEBVTT\n\n" + "\n\n".join(f"{t(c['start'])} --> {t(c['end'])}\n{c['text']}" for c in cues) + "\n"


class Install(BaseModel):
    confirm: bool = False


class Videos:
    def __init__(self, ctx: Ctx, lane):
        self.ctx, self.lane = ctx, lane
        self.running: set[tuple[int, str]] = set()
        self.failed: dict[tuple[int, str], str] = {}  # (Block, digest) -> the log: a Block is not retried until it or its Voice changes (or Retry)
        self.scripts: dict[str, tuple[list[list[str]], dict]] = {}
        self.installing: dict | None = None
        self.lock = threading.Lock()

    def block(self, bid: int):
        return self.ctx.db.execute("SELECT b.*, c.course_id AS cid, co.language FROM blocks b JOIN sections s ON s.id=b.section_id "
                                   "JOIN chapters c ON c.id=s.chapter_id JOIN courses co ON co.id=c.course_id WHERE b.id=? AND b.component='video'", (bid,)).fetchone()

    def script(self, narration: list[str], lang: str) -> tuple[list[list[str]], dict]:
        """Each scene's sentences (maths spoken as Listen does it) and the scenes whose formulas it could not say."""
        key = json.dumps([narration, lang], ensure_ascii=False)
        if key not in self.scripts:
            spoken, bad = listen.maths_words([(lang, n) for n in narration]), {}
            self.scripts[key] = ([listen.sayable(n, lang, spoken, bad, i) for i, n in enumerate(narration)], bad)
        return self.scripts[key]

    def state(self, bid: int, start: bool = False) -> dict | None:
        """Where a Video is: "ready" (with its files), "rendering", "failed" (with the log) or "pending" (with the note on what to install,
        or why it cannot be drawn). `start` queues the render when nothing prevents it."""
        row = self.block(bid)
        if row is None:
            return None
        data, db = json.loads(row["data"]), self.ctx.db
        out = {"state": "pending", "note": "", "narration": data["narration"], "caption": data.get("caption", ""), "url": None, "poster": None,
               "captions": None, "error": None}
        try:
            params, _ = check_params(data["template"], data["params"])
        except ValueError as e:
            return out | {"state": "invalid", "note": str(e)}
        lang = row["language"] if row["language"] != "mixed" else listen.detect(" ".join(data["narration"]))
        try:
            voice, _ = voices.voice_for(self.ctx, lang)
        except LookupError as e:
            return out | {"note": str(e)}
        speaker = voices.speaker_of(voices.settings(db), voice, lang)
        digest = hashlib.sha1(json.dumps([data["template"], TEMPLATES[data["template"]].version, params, data["narration"], lang, voice, speaker],
                                         ensure_ascii=False).encode()).hexdigest()[:16]
        folder, key = self.ctx.course_dir(row["cid"]) / "videos" / str(bid), (bid, digest)
        base = f"/api/courses/{row['cid']}/blocks/{bid}/video/{digest}"
        if (folder / f"{digest}.mp4").exists():
            return out | {"state": "ready", "url": base + ".mp4", "poster": base + ".png", "captions": base + ".vtt"}
        if key in self.running:
            return out | {"state": "rendering"}
        if key in self.failed:
            return out | {"state": "failed", "error": self.failed[key]}
        if not self.ctx.media.video_installed():  # type: ignore[union-attr]
            return out | {"note": f"Install video rendering in Settings (about {voices.MANIM['size_mb']} MB) to render this Video."}
        if row["status"] != "ok":
            return out | {"note": "This Block has flags: it is rendered once they are resolved."}
        if start:
            with self.lock:
                self.running.add(key)
            self.lane.submit(self.job, bid, digest, lang, voice, speaker, params, kind="video", course=row["cid"], stoppable=True,
                             label=f"Video · {params.get('title') or data['template'].replace('_', ' ')} ({voice})")
            return out | {"state": "rendering"}
        return out

    def ensure(self, bid: int) -> dict | None:
        return self.state(bid, start=True)

    def sync_section(self, sid: int) -> None:
        for r in self.ctx.db.execute("SELECT id FROM blocks WHERE section_id=? AND component='video'", (sid,)).fetchall():
            self.ensure(r["id"])

    def job(self, bid: int, digest: str, lang: str, voice: str, speaker: str | None, params: dict) -> None:
        key, db = (bid, digest), self.ctx.db
        try:
            row = self.block(bid)
            data = json.loads(row["data"])
            folder = self.ctx.course_dir(row["cid"]) / "videos" / str(bid)
            folder.mkdir(parents=True, exist_ok=True)
            scenes, bad = self.script(data["narration"], lang)
            if bad:
                listen.flag_block(self.ctx, bid, "listen:", listen.FLAG + next(iter(bad.values()))[:80])
            # the picture depends on the Block, not the Voice: rendered once, then fitted to each Voice's narration
            pic = hashlib.sha1(json.dumps([data["template"], TEMPLATES[data["template"]].version, params, data["narration"], lang],
                                          ensure_ascii=False).encode()).hexdigest()[:16]
            picture, timing = folder / f"{pic}.picture", folder / f"{pic}.timing.json"
            fit = json.loads(timing.read_text()) if picture.exists() and timing.exists() else None
            spoken, fmt = [], None  # per scene: its sentences with their frames, and the PCM
            total, said = sum(map(len, scenes)) + 1, 0  # every sentence, then the render
            for sentences in scenes:
                clip, lines = b"", []
                for sent in sentences:
                    self.lane.checkpoint(said, total, "narration")
                    said += 1
                    fmt, pcm = frames(listen.spoken(self.ctx, row["cid"], sent, lang, voice, speaker).read_bytes())
                    lines.append((sent, len(pcm) // (fmt[0] * fmt[1])))
                    clip += pcm
                spoken.append((lines, clip))
            if fmt is None:
                raise RuntimeError("the narration has nothing to say")
            durations = [max(MIN_SCENE, sum(k for _, k in lines) / fmt[2] + PAD) for lines, _ in spoken]
            if fit:  # never cut into an animation of the picture
                durations = [max(d, used + 0.1) for d, used in zip(durations, fit["used"])]
            audio, cues, at = b"", [], 0.0
            for (lines, clip), length in zip(spoken, durations):
                n = 0
                for sent, k in lines:
                    cues.append({"start": at + n / fmt[2], "end": at + (n + k) / fmt[2], "text": sent})
                    n += k
                at += length
                audio += clip + b"\0" * fmt[0] * fmt[1] * (round(length * fmt[2]) - n)
            wav = folder / f"{digest}.wav"
            with wave.open(str(wav), "wb") as w:
                w.setnchannels(fmt[0]), w.setsampwidth(fmt[1]), w.setframerate(fmt[2])  # wave params: channels, width, rate
                w.writeframes(audio)
            work = folder / "work.mp4"
            if fit:
                self.lane.checkpoint(said, total, "fitting the picture to the narration")
                self.ctx.media.retime(picture, fit["durations"], durations, wav, work)  # type: ignore[union-attr]
            else:
                spec = {"template": data["template"], "params": params, "durations": durations, "words": WORDS[lang]}
                if data["template"] == "function_plot":
                    spec["curve"] = curve(params["expr"], params["x_range"])
                    spec["params"] = params | {"marks": [m | {"y": curve(params["expr"], (m["x"], m["x"]), 1)[0][1]} for m in params["marks"]]}
                self.lane.checkpoint(said, total, "rendering the scenes")
                self.ctx.media.render(spec, wav, work)  # type: ignore[union-attr]
                holds = work.with_suffix(".holds.json")
                if work.with_suffix(".picture").exists() and holds.exists():
                    starts = [sum(durations[:i]) for i in range(len(durations))]
                    used = [d if h is None else h - s for h, s, d in zip(json.loads(holds.read_text()), starts, durations)]
                    work.with_suffix(".picture").replace(picture)
                    timing.write_text(json.dumps({"durations": durations, "used": used}))
                holds.unlink(missing_ok=True)
            wav.unlink(missing_ok=True)
            (folder / f"{digest}.json").write_text(json.dumps(cues, ensure_ascii=False))
            # each Voice keeps its own Video, so switching back is instant; what the Block said before, in any Voice, is stale
            content = hashlib.sha1(json.dumps([data["template"], params, data["narration"], lang], ensure_ascii=False).encode()).hexdigest()
            made = json.loads((folder / "made.json").read_text()) if (folder / "made.json").exists() else {}
            made[digest] = {"voice": voice, "content": content}
            stale = [d for d, m in made.items() if d != digest and (m["content"] != content or m["voice"] == voice)]
            for old in folder.iterdir():
                if any(old.name.startswith(d) for d in stale) or (old.name.endswith((".picture", ".timing.json")) and not old.name.startswith(pic)):
                    old.unlink(missing_ok=True)
            (folder / "made.json").write_text(json.dumps({d: m for d, m in made.items() if d not in stale}))
            flags = [f for f in json.loads(db.execute("SELECT flags FROM blocks WHERE id=?", (bid,)).fetchone()["flags"]) if not f.startswith(FLAG)]
            db.execute("UPDATE blocks SET flags=?, review_queue=? WHERE id=?", (json.dumps(flags, ensure_ascii=False), int(bool(flags)), bid))
            work.with_suffix(".png").rename(folder / f"{digest}.png")
            work.rename(folder / f"{digest}.mp4")  # last: the Video is ready once this file is there
        except Stopped as e:
            self.failed[key] = str(e)  # shown with Retry; not a flag: nothing is wrong with the Block
        except Exception as e:
            log = f"{type(e).__name__}: {e}"[:3000]
            self.failed[key] = log
            try:
                listen.flag_block(self.ctx, bid, FLAG, FLAG + "the render failed, the Block shows its narration instead: " + log)
            except Exception:
                pass  # the Block went away while it rendered
        finally:
            with self.lock:
                self.running.discard(key)

    def ensure_overview(self, chid: int) -> None:
        """One Chapter overview Video per Chapter, made by code from the Chapter's overview and its Sections' first Objectives. Only once
        video rendering is installed: before that it would be a "not rendered yet" box at the top of every Chapter."""
        db = self.ctx.db
        if not self.ctx.media.video_installed():  # type: ignore[union-attr]
            return
        if db.execute("SELECT 1 FROM blocks b JOIN sections s ON s.id=b.section_id WHERE s.chapter_id=? AND b.component='video' AND "
                      "json_extract(b.data,'$.template')='chapter_overview'", (chid,)).fetchone():
            return
        if (data := overview_data(db, chid)) is None:
            return
        first = db.execute("SELECT id FROM sections WHERE chapter_id=? ORDER BY position LIMIT 1", (chid,)).fetchone()["id"]
        db.execute("UPDATE blocks SET position=position+1 WHERE section_id=?", (first,))
        bid = db.execute("INSERT INTO blocks (section_id, position, component, data, origin, status) VALUES (?,0,'video',?,'model_added','ok')",
                         (first, json.dumps(data, ensure_ascii=False))).lastrowid
        self.ensure(bid)

    def sync_chapter(self, chid: int) -> None:
        self.ensure_overview(chid)
        for s in self.ctx.db.execute("SELECT id FROM sections WHERE chapter_id=?", (chid,)).fetchall():
            self.sync_section(s["id"])


def overview_data(db, chid: int) -> dict | None:
    """The Chapter overview Video's data, from the Chapter plan's overview and its Sections' first Objectives. What a Voice can't
    say (maths written without $…$) is left out: a Section whose Objective has it is named by its title alone."""
    ch = db.execute("SELECT * FROM chapters WHERE id=?", (chid,)).fetchone()
    plan = json.loads(ch["plan"] or "{}")
    sections = db.execute("SELECT * FROM sections WHERE chapter_id=? ORDER BY position", (chid,)).fetchall()
    sayable = lambda t: not voices.FORBIDDEN.search(listen.plain(listen.MATH.sub(" ", t)))  # noqa: E731
    # its prose, without the list of Sections that can follow it ("\n" escaped twice by the model is a line break)
    prose = re.split(r"(?:(?<=[.!?…:])|\n|^)\s*[-•]\s", heal_markdown(plan.get("overview", "")).strip(), maxsplit=1)[0]
    sentences = [s for s in re.split(r"(?<=[.!?…])\s+", prose) if s and sayable(s)]
    if not sections or not sentences:
        return None
    first = {p["title"]: " ".join(o["text"] for o in p.get("objectives", [])[:1]) for p in plan.get("sections", [])}
    said = {t: o for t, o in first.items() if sayable(o)}
    lines = [{"title": clean(s["title"], 60), "line": clean(said.get(s["title"], ""), 110)} for s in sections[:8]]
    try:
        params, _ = check_params("chapter_overview", {"title": clean(ch["title"], 70), "points": [clean(s, 90) for s in sentences[:3]], "sections": lines})
    except ValueError:
        return None
    narration = [" ".join(sentences[:3]), *[f"{s['title']}. {said.get(s['title'], '')}".strip() for s in sections[:8]]]
    return {"template": "chapter_overview", "params": params, "narration": narration, "caption": ""}


def router(ctx: Ctx, videos: Videos, lane) -> APIRouter:
    r = APIRouter()
    media = ctx.media

    def video_or_404(cid: int, bid: int) -> dict:
        row = videos.block(bid)
        if row is None or row["cid"] != cid:
            raise HTTPException(404, "no such Video")
        return row

    @r.get("/api/courses/{cid}/blocks/{bid}/video")
    def get_video(cid: int, bid: int):
        """Where the Video is; asking also queues a render that is due (a changed Voice, a Block saved before video rendering was installed)."""
        video_or_404(cid, bid)
        return videos.ensure(bid)

    @r.post("/api/courses/{cid}/blocks/{bid}/video/retry")
    def retry(cid: int, bid: int):
        video_or_404(cid, bid)
        for k in [k for k in videos.failed if k[0] == bid]:
            del videos.failed[k]
        return videos.ensure(bid)

    @r.get("/api/courses/{cid}/blocks/{bid}/video/{name}")
    def file(cid: int, bid: int, name: str):
        video_or_404(cid, bid)
        folder = ctx.course_dir(cid) / "videos" / str(bid)
        if not FILE.fullmatch(name):
            raise HTTPException(404, "no such file")
        stem, ext = name.split(".")
        if ext == "vtt":
            cues = folder / f"{stem}.json"
            if not cues.is_file():
                raise HTTPException(404, "no such file")
            return Response(vtt(json.loads(cues.read_text())), media_type="text/vtt")
        if not (folder / name).is_file():
            raise HTTPException(404, "no such file")
        return FileResponse(folder / name, media_type="video/mp4" if ext == "mp4" else "image/png")

    def listing() -> dict:
        m = voices.MANIM
        return {"name": m["name"], "version": m["version"], "licence": m["licence"], "size_mb": m["size_mb"], "note": m["note"],
                "installed": media.video_installed(), "install": videos.installing}  # type: ignore[union-attr]

    @r.post("/api/courses/{cid}/videos/overviews")
    def add_overviews(cid: int):
        """Gives a Course written before video rendering was installed its Chapter overview Videos: the owner picks the Courses."""
        if not media.video_installed():  # type: ignore[union-attr]
            raise HTTPException(409, "install video rendering first")
        for ch in ctx.db.execute("SELECT id FROM chapters WHERE course_id=?", (cid,)).fetchall():
            videos.ensure_overview(ch["id"])
        return {"ok": True}

    @r.get("/api/video")
    def get_settings():
        return listing()

    @r.post("/api/video/install", status_code=202)
    def install(body: Install):
        if not body.confirm:
            raise HTTPException(422, f"Installing video rendering downloads about {voices.MANIM['size_mb']} MB: confirm it to go ahead")
        if media.video_installed() or (videos.installing or {}).get("state") == "running":  # type: ignore[union-attr]
            raise HTTPException(409, "video rendering is installed or installing")
        job = videos.installing = {"state": "running", "log": []}

        def work():
            try:
                media.install_video(job["log"].append)  # type: ignore[union-attr]
                videos.installing = None
            except Exception as e:
                job.update(state="failed", log=[*job["log"][-5:], f"{type(e).__name__}: {e}"[:600]])
        lane.submit(work, kind="install", label="Install video rendering")
        return listing()

    @r.delete("/api/video", status_code=204)
    def remove():
        if not media.video_installed():  # type: ignore[union-attr]
            raise HTTPException(409, "not installed")
        media.remove_video()  # type: ignore[union-attr]
        videos.installing = None

    return r
