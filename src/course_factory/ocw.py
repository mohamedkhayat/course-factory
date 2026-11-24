"""MIT OpenCourseWare as a source of material: search its courses and download one course's files into a folder, one
sub-folder per OCW kind ("Lecture Notes", "Exams"), so the Run's Role proposals can read the kind from the path."""

import html
import json
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

API = "https://api.learn.mit.edu/api/v1"
SITE = "https://ocw.mit.edu"
KEEP = {".pdf", ".ipynb", ".py", ".csv", ".txt", ".json"}  # what the Run can read; MATLAB scripts, images and videos are left out
MAX_FILES = 200
MAX_BYTES = 60_000_000  # one file; a scanned textbook beyond this is skipped
TAGS = re.compile(r"<[^>]+>")


def fetch(url: str) -> bytes:
    if not url.startswith((API + "/", SITE + "/")):  # only the two hosts this module talks to
        raise ValueError(f"not an OCW address: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "course-factory"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"too large: {url}")
    return data


def search(q: str, limit: int = 20) -> list[dict]:
    """OCW courses matching q, as the New Course dialog lists them."""
    qs = urllib.parse.urlencode({"q": q, "offered_by": "ocw", "resource_type": "course", "limit": limit})
    out = []
    for r in json.loads(fetch(f"{API}/learning_resources_search/?{qs}"))["results"]:
        run = (r.get("runs") or [{}])[0]
        numbers = (r.get("course") or {}).get("course_numbers") or [{}]
        text = html.unescape(TAGS.sub(" ", r.get("description") or "")).split()
        out.append({"id": r["id"], "title": r["title"], "number": numbers[0].get("value"), "semester": run.get("semester"),
                    "year": run.get("year"), "url": r.get("url"), "features": r.get("course_feature") or [],
                    "description": " ".join(text[:60]) + (" …" if len(text) > 60 else ""),
                    "image": (r.get("image") or {}).get("url")})
    return out


def files(resource_id: int) -> list[dict]:
    """The course's downloadable files the Run can read: each one's resource page, name and OCW kind."""
    url, out = f"{API}/contentfiles/?resource_id={int(resource_id)}&limit=100", []
    while url and len(out) < MAX_FILES:
        page = json.loads(fetch(url))
        for f in page["results"]:
            name = PurePosixPath(f.get("title") or "").name
            if (f.get("file_extension") or "").lower() in KEEP and name not in ("", ".", ".."):  # pages have no extension
                if not name.lower().endswith(f["file_extension"].lower()):
                    name += f["file_extension"]
                kind = (f.get("content_feature_type") or ["Other"])[0]
                out.append({"page": f["url"], "name": name, "kind": re.sub(r"[^\w\- ]", "", kind) or "Other"})
        url = page.get("next")
    return out[:MAX_FILES]


def file_url(page: str, name: str) -> str:
    """The direct link on a resource page: OCW serves files as /courses/<course>/<hash>_<name>."""
    m = re.search(r'href="(/courses/[^"]+/[0-9a-f]{32}_' + re.escape(name) + ')"', fetch(page).decode("utf-8", "replace"))
    if not m:
        raise ValueError(f"no download link on {page}")
    return SITE + m.group(1)


def download(resource_id: int, folder: Path) -> list[str]:
    """Downloads the course's files into folder; returns what was saved. A file that fails is skipped, not fatal."""
    wanted = files(resource_id)

    def one(f: dict) -> str | None:
        try:
            data = fetch(file_url(f["page"], f["name"]))
        except (OSError, ValueError):
            return None
        dest = folder / f["kind"] / f["name"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return f"{f['kind']}/{f['name']}"

    with ThreadPoolExecutor(8) as pool:
        return [s for s in pool.map(one, wanted) if s]
