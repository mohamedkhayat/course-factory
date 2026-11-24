"""Listen: a Section read aloud, and Dictation. Code builds the script from the Section's Blocks (never the model), turns maths into
words with the Speech Rule Engine, splits it into sentences tied to their Block, and a background job on the media lane has a Voice
read each one. Clips are cached per Section, Voice and content hash under the Course dir, and stream to the client as they are made."""
import hashlib
import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from . import voices
from .chapters import page_texts
from .context import Ctx
from .media import speak_checked, wav_length
from .media_queue import Stopped
from .progression import PRACTICE
from .tutor import sse

SPEECH_HELPER = Path(__file__).resolve().parents[2] / "web" / "scripts" / "speech.mjs"
MAX_SENTENCE = 300  # characters: a longer one is cut at a comma so a clip stays short
MAX_AUDIO = 25_000_000  # a spoken answer, not a lecture
FORMULA = {"en": "the formula on screen", "fr": "la formule affichée à l'écran"}
FLAG = "listen: a formula could not be turned into speech, so Listen says \"the formula on screen\": "
KINDS = {"en": {"definition": "Definition", "theorem": "Theorem", "proposition": "Proposition", "lemma": "Lemma", "corollary": "Corollary", "property": "Property"},
         "fr": {"definition": "Définition", "theorem": "Théorème", "proposition": "Proposition", "lemma": "Lemme", "corollary": "Corollaire", "property": "Propriété"}}
NAMES = {"sql": "SQL", "yaml": "YAML", "json": "JSON", "bash": "shell", "sh": "shell", "html": "HTML", "css": "CSS", "javascript": "JavaScript",
         "typescript": "TypeScript", "scala": "Scala", "python": "Python", "java": "Java", "r": "R", "dockerfile": "Dockerfile"}
CAPTIONED = ("plot", "figure", "table", "surface_plot", "optimizer_animation", "diagram")
MATH = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$|\\\((.+?)\\\)|\\\[(.+?)\\\]", re.S)
FRENCH = set("le la les des du de un une est et que qui dans pour sur avec ce cette sont nous vous au aux par pas ne se".split())
ENGLISH = set("the of and is are to in that for with this it as be by on not we you an or from".split())


def detect(text: str, tie: str = "en") -> str:
    """The language of some text, by counting its common words: a quote's or a paragraph's language in a mixed Course."""
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    fr, en = sum(w in FRENCH for w in words), sum(w in ENGLISH for w in words)
    return "fr" if fr > en else "en" if en > fr else tie


def walk(d: dict) -> list[str]:
    """The ids of a diagram's items in the order a person is walked through them (the arrow-key order of the diagram)."""
    ids = [i["id"] for i in d["items"]]
    kind = d["kind"]
    if kind in ("tree", "nesting"):
        key = "parent" if kind == "tree" else "container"
        kids = {i: [x["id"] for x in d["items"] if x.get(key) == i] for i in ids}
        order: list[str] = []

        def visit(i):
            if i not in order:
                order.append(i)
                for k in kids[i]:
                    visit(k)
        for i in ids:
            if not next(x for x in d["items"] if x["id"] == i).get(key):
                visit(i)
        for i in ids:
            visit(i)
        return order
    if kind == "layers":
        return [i["id"] for i in sorted(d["items"], key=lambda x: x.get("layer") or 0)]
    if kind in ("pipeline", "cycle"):
        return d["order"]
    if kind == "fan_out":
        return [d["hub"], *d["spokes"]]
    return ids


def lines_of(block: dict, lang: str) -> list[str]:
    """What a Block says, as Markdown paragraphs with maths as $...$; nothing for practice, which would give the answers away."""
    c, d = block["component"], block["data"]
    if c in PRACTICE:
        return []
    caption = [d["caption"]] if d.get("caption") else []
    if c == "prose":
        return [d["markdown"]]
    if c == "theorem_box":
        return [f"{KINDS[lang].get(d['kind'], d['kind'])}. {d['title']}." if d.get("title") else f"{KINDS[lang].get(d['kind'], d['kind'])}.", d["statement"]]
    if c == "worked_example":
        return [d["title"] + ".", d["problem"], *d["steps"], d["answer"]]
    if c == "derivation":
        return [d["title"] + ".", *[x for x in (d.get("statement"), *[ln["math"] for ln in d["lines"]], d.get("conclusion")) if x]]
    if c == "key_formula":
        return [d["name"] + ".", f"$${d['latex']}$$", d["meaning"]]
    if c == "callout":
        return [d["text"]]
    if c == "algorithm":
        return [d["name"] + ".", *[x for x in (d.get("when"), d["inputs"], *d["steps"], d["output"]) if x]]
    if c == "intuition":
        return [x for x in (d["idea"], d.get("analogy"), d.get("limits")) if x]
    if c == "misconception":
        return [d["belief"], d["why_wrong"], d["correct"]]
    if c == "recap":
        return [*d["takeaways"], *d.get("can_do", [])]
    if c == "kind_diagram":  # the items' explanations, in the order the arrow keys walk them
        by = {i["id"]: i for i in d["items"]}
        return [*caption, *[f"{by[i]['label']}. {by[i]['explanation']}" for i in walk(d) if i in by]]
    if c == "stepped_animation":
        return [*caption, *[s["caption"] for s in d["steps"]]]
    if c == "step_diagram":
        return [*caption, *[s["caption"] for s in d["steps"]]]
    if c == "code":
        n = len(d["code"].strip("\n").split("\n"))
        name = NAMES.get(d.get("language", "").lower(), (d.get("language") or "code").capitalize())
        return [f"A {name} example, {n} line{'s' * (n != 1)}." if lang == "en" else f"Un exemple {name}, {n} ligne{'s' * (n != 1)}."]
    if c == "terminal":
        n = len(d["entries"])
        return [f"A terminal session, {n} command{'s' * (n != 1)}." if lang == "en" else f"Une session de terminal, {n} commande{'s' * (n != 1)}."]
    return caption if c in CAPTIONED else []


def math_speech(latex: list[str], lang: str) -> dict[str, str | None]:
    """The words for each formula (None where the engine can't say it): one run of the Node helper for the whole Section."""
    if not latex:
        return {}
    try:
        out = subprocess.run(["node", str(SPEECH_HELPER)], input=json.dumps({"locale": lang, "items": latex}), capture_output=True,
                             text=True, timeout=60, check=True).stdout
        spoken = json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        spoken = [None] * len(latex)
    return {l: s if s and not voices.FORBIDDEN.search(s) else None for l, s in zip(latex, spoken)}


def plain(text: str) -> str:
    """Markdown as plain words: no fences, links, citations, emphasis or HTML; an identifier's underscores are spaces."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[[^\[\]]+ p\.\s*\d+\]", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"(?m)^\s*(#+|>|[-*+]|\d+[.)])\s+", "", text)
    text = re.sub(r"[`*|~]", " ", text).replace("_", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def pieces(paragraph: str) -> list[str]:
    out = []
    for s in re.split(r"(?<=[.!?…])\s+(?=\S)", paragraph):
        while len(s) > MAX_SENTENCE:  # cut at the last comma or semicolon before the limit
            cut = max(s.rfind(", ", 0, MAX_SENTENCE), s.rfind("; ", 0, MAX_SENTENCE))
            cut = cut + 1 if cut > 40 else MAX_SENTENCE
            out.append(s[:cut].strip())
            s = s[cut:].strip()
        out.append(s)
    return [s.strip() for s in out if re.search(r"\w", s)]


def maths_words(paragraphs: list[tuple[str, str]]) -> dict[str, dict[str, str | None]]:
    """The words for every formula in (language, Markdown paragraph) pairs, one Node run per language: what `sayable` needs."""
    return {lang: math_speech(sorted({next(g for g in m.groups() if g is not None).strip() for l, p in paragraphs if l == lang
                                      for m in MATH.finditer(p)}), lang) for lang in ("en", "fr")}


def sayable(paragraph: str, lang: str, spoken: dict, bad: dict, key) -> list[str]:
    """A Markdown paragraph as sentences a Voice can read: maths in words; a formula that has none, or any backslash, dollar, underscore,
    caret or brace left, is "the formula on screen" and is recorded in `bad` under `key`. Shared by Listen and Video narration."""
    def say(m):
        latex = next(g for g in m.groups() if g is not None).strip()
        words = spoken[lang].get(latex)
        if words is None:
            bad.setdefault(key, latex)
            return " " + FORMULA[lang] + " "
        return f" {words} "
    out = []
    for s in pieces(plain(MATH.sub(say, paragraph))):
        if voices.FORBIDDEN.search(s):
            bad.setdefault(key, s)
            s = FORMULA[lang]
        out.append(s if re.search(r"[.!?…]$", s) else s + ".")
    return out


def flag_block(ctx: Ctx, bid: int, prefix: str, text: str) -> None:
    """Puts the Block in the Review Queue with a flag, once per kind of flag (`prefix`)."""
    flags = json.loads(ctx.db.execute("SELECT flags FROM blocks WHERE id=?", (bid,)).fetchone()["flags"])
    if not any(f.startswith(prefix) for f in flags):
        ctx.db.execute("UPDATE blocks SET flags=?, review_queue=1 WHERE id=?", (json.dumps(flags + [text], ensure_ascii=False), bid))


def build(ctx: Ctx, cid: int, sid: int, title: str, blocks: list[dict], flag: bool = True) -> dict:
    """The Section's Listen script: {"sentences": [{n, block_id, start, end, text, language}], "flagged": [block ids]}.
    A sentence that still holds a backslash, dollar, underscore, caret or brace after maths-to-speech is spoken as the formula on
    screen, and its Block goes to the Review Queue."""
    course_lang = ctx.db.execute("SELECT language FROM courses WHERE id=?", (cid,)).fetchone()["language"]
    todo = []  # (block id or None, [(language, Markdown paragraph)])
    todo.append((None, [(course_lang if course_lang != "mixed" else detect(title), title + ".")]))
    for b in blocks:
        if course_lang != "mixed":
            todo.append((b["id"], [(course_lang, p) for p in lines_of(b, course_lang)]))
        elif b["origin"] == "from_source" and b["citations"]:  # a quote keeps the language of its pages
            lang = detect(" ".join(p["text"] or "" for p in page_texts(ctx, cid, b["citations"])))
            todo.append((b["id"], [(lang, p) for p in lines_of(b, lang)]))
        else:  # the model's own words: each paragraph in the language it is written in (an English title must not make French text English)
            lang = detect(" ".join(lines_of(b, "en")))
            todo.append((b["id"], [(detect(p, lang), p) for p in lines_of(b, lang)]))
    spoken = maths_words([(lang, p) for _, ps in todo for lang, p in ps])
    sentences, flagged, bad = [], [], {}
    for bid, paragraphs in todo:
        at = 0
        for lang, p in paragraphs:
            for s in sayable(p, lang, spoken, bad, bid):
                sentences.append({"n": len(sentences), "block_id": bid, "start": at, "end": at + len(s), "text": s, "language": lang})
                at += len(s) + 1
    for bid, latex in bad.items():
        if bid is not None:
            flagged.append(bid)
            if flag:  # audio made ahead while a Course is written leaves flags to the owner's Listen, after auto-resolve
                flag_block(ctx, bid, "listen:", FLAG + latex[:80])
    return {"sentences": sentences, "flagged": flagged}


def spoken(ctx: Ctx, cid: int, text: str, lang: str, voice: str, speaker: str | None) -> Path:
    """A sentence's audio in a Voice, kept per Course and Voice: switching back to a Voice, or a Section or Video that says the same
    sentence again, reuses the recording instead of speaking it again."""
    key = hashlib.sha1(json.dumps([text, lang, speaker], ensure_ascii=False).encode()).hexdigest()[:20]
    path = ctx.course_dir(cid) / "audio" / voice / f"{key}.wav"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".part")
        part.write_bytes(speak_checked(ctx.media, text, lang, voice, speaker).wav)  # type: ignore[arg-type]
        part.replace(path)
    return path


class Job:
    def __init__(self, cid: int, plan: dict, sentences: list[dict], folder: Path):
        self.cid, self.plan, self.sentences, self.folder = cid, plan, sentences, folder
        self.clips: dict[int, float] = {}
        self.ahead = False  # made ahead: the lane job that registered it runs it
        self.want = 0  # the sentence the listener is waiting for: spoken first, then on from there, then the rest
        self.error: str | None = None
        self.done = False
        self.lock = threading.Lock()


def router(ctx: Ctx, lane) -> APIRouter:
    r = APIRouter()
    db, media = ctx.db, ctx.media
    jobs: dict[Path, Job] = {}
    guard = threading.RLock()  # prepare() retries a failed job from inside the lock

    def section_or_404(cid: int, sid: int):
        row = db.execute("SELECT s.* FROM sections s JOIN chapters c ON c.id=s.chapter_id WHERE s.id=? AND c.course_id=?", (sid, cid)).fetchone()
        if row is None:
            raise HTTPException(404, "no such Section")
        return row

    def generate(job: Job):
        try:
            while True:
                with job.lock:
                    todo = [s for s in job.sentences if s["n"] not in job.clips]
                    if not todo:
                        break
                    s = next((s for s in todo if s["n"] >= job.want), todo[0])
                lane.checkpoint(len(job.sentences) - len(todo), len(job.sentences), "speaking")
                path = job.folder / f"{s['n']}.wav"
                if not path.exists():
                    voice, speaker = job.plan[s["language"]]
                    shutil.copyfile(spoken(ctx, job.cid, s["text"], s["language"], voice, speaker), path)
                with job.lock:
                    job.clips[s["n"]] = wav_length(path.read_bytes())
            (job.folder / "complete").write_text("1")
        except Stopped as e:
            job.error = str(e)
        except Exception as e:
            job.error = f"{type(e).__name__}: {e}"[:600]
        finally:
            job.done = True

    def prepare(cid: int, sid: int, block: int | None = None, ahead: bool = False):
        """The Section's script and its audio job, started on the media lane unless it is running or made (`ahead`: the caller,
        already on the lane, runs it)."""
        sec = section_or_404(cid, sid)
        blocks = [{"id": b["id"], "component": b["component"], "data": json.loads(b["data"]), "origin": b["origin"], "citations": json.loads(b["citations"])}
                  for b in db.execute("SELECT * FROM blocks WHERE section_id=? ORDER BY position", (sid,))]
        script = build(ctx, cid, sid, sec["title"], blocks, flag=not ahead)
        sentences = script["sentences"]
        if len(sentences) < 2:
            raise HTTPException(409, "there is nothing in this Section to read aloud")
        try:
            plan = {lang: (v, voices.speaker_of(voices.settings(db), v, lang))
                    for lang in {s["language"] for s in sentences} for v, _ in [voices.voice_for(ctx, lang)]}
        except LookupError as e:
            raise HTTPException(409, str(e))
        chosen = voices.settings(db)["voice"]
        digest = hashlib.sha1(json.dumps([[s["text"], s["language"]] for s in sentences] + [sorted(plan.items())], ensure_ascii=False).encode()).hexdigest()[:16]
        base = ctx.course_dir(cid) / "listen" / str(sid)
        folder = base / f"{chosen}-{digest}"
        want = next((x["n"] for x in sentences if block is not None and x["block_id"] == block), 0)
        with guard:
            job = jobs.get(folder)
            if job is not None and not job.done and not ahead:
                job.want = want
            if job is None:
                for old in base.glob(f"{chosen}-*"):  # the Section changed: its audio for this Voice is stale
                    if old != folder and not (jobs.get(old) and not jobs[old].done):  # never under a job still speaking into it
                        shutil.rmtree(old, ignore_errors=True)
                        jobs.pop(old, None)
                folder.mkdir(parents=True, exist_ok=True)
                job = jobs[folder] = Job(cid, plan, sentences, folder)
                job.want = want
                if (folder / "complete").exists():
                    job.clips = {s["n"]: wav_length((folder / f"{s['n']}.wav").read_bytes()) for s in sentences}
                    job.done = True
                elif ahead:
                    job.ahead = True
                else:
                    lane.submit(generate, job, kind="listen", label=f"Listen · {sec['title']} ({chosen})", course=cid, stoppable=True)
            elif job.done and job.error:  # a failed job is retried by the next Listen
                del jobs[folder]
                return prepare(cid, sid, block, ahead)
        return job, script, chosen, digest, plan

    def ahead(cid: int, sid: int):
        """On the media lane: the Section's audio in the chosen Voice, made while the Course is written, so Listen starts at once."""
        try:
            job = prepare(cid, sid, ahead=True)[0]
        except HTTPException:
            return  # nothing to read, or no Voice for its language
        if job.ahead:
            job.ahead = False
            generate(job)

    def listen_ahead(sid: int):
        row = db.execute("SELECT s.title, c.course_id FROM sections s JOIN chapters c ON c.id=s.chapter_id WHERE s.id=?", (sid,)).fetchone()
        if row:
            lane.submit(ahead, row["course_id"], sid, kind="listen", label=f"Listen ahead · {row['title']}", course=row["course_id"],
                        background=True, stoppable=True)
    ctx.listen_ahead = listen_ahead

    @r.post("/api/courses/{cid}/sections/{sid}/listen")
    def listen(cid: int, sid: int, block: int | None = None):
        """Reads the Section: server-sent events "script" (every sentence), then a "clip" as each is spoken, then "done". The first
        time it starts a background job; the audio is then kept, so later calls only replay it. With `block`, that Block's
        sentences are spoken first, so listening from a Block starts without waiting for the Section's start."""
        job, script, chosen, digest, plan = prepare(cid, sid, block)
        sentences = script["sentences"]

        def events():
            yield sse("script", {"voice": chosen, "key": digest, "sentences": sentences, "flagged": script["flagged"],
                                 "plan": {l: v for l, (v, _) in plan.items()}})
            sent: set[int] = set()
            while True:
                with job.lock:
                    new = sorted((n, d) for n, d in job.clips.items() if n not in sent)
                    finished, error = job.done, job.error
                for n, d in new:
                    sent.add(n)
                    yield sse("clip", {"n": n, "duration": d, "url": f"/api/courses/{cid}/sections/{sid}/listen/{chosen}/{digest}/{n}.wav"})
                if error:
                    yield sse("error", {"message": error})
                    return
                if finished and len(sent) == len(job.clips):
                    yield sse("done", {})
                    return
                time.sleep(0.1)
        return StreamingResponse(events(), media_type="text/event-stream")

    @r.get("/api/courses/{cid}/sections/{sid}/listen/{voice}/{digest}/{n}.wav")
    def clip(cid: int, sid: int, voice: str, digest: str, n: int):
        section_or_404(cid, sid)
        path = ctx.course_dir(cid) / "listen" / str(sid) / f"{voice}-{digest}" / f"{n}.wav"
        if voice not in voices.REGISTRY or not re.fullmatch(r"[0-9a-f]{16}", digest) or not path.is_file():
            raise HTTPException(404, "no such clip")
        return FileResponse(path, media_type="audio/wav")

    @r.post("/api/courses/{cid}/dictate")
    def dictate(cid: int, audio: UploadFile = File(...)):
        """Speech to text: the recording is transcribed on the CPU in the Course language (and English) and deleted at once."""
        row = db.execute("SELECT language FROM courses WHERE id=?", (cid,)).fetchone()
        if row is None:
            raise HTTPException(404, "no such Course")
        folder = ctx.course_dir(cid) / "dictation"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{uuid.uuid4().hex}{Path(audio.filename or '').suffix[:8] or '.webm'}"
        try:
            data = audio.file.read(MAX_AUDIO + 1)
            if len(data) > MAX_AUDIO:
                raise HTTPException(413, "that recording is too long to dictate")
            path.write_bytes(data)
            try:
                text = media.transcribe(path, ["en"] if row["language"] == "en" else ["fr", "en"])  # type: ignore[union-attr]
            except Exception as e:
                raise HTTPException(502, f"could not transcribe: {e}")
            return {"text": text}
        finally:
            path.unlink(missing_ok=True)

    return r
