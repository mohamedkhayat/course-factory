"""Per-Course change events for open devices: Block writes land here from any thread and fan out to SSE streams."""
import asyncio
import threading

_subs: dict[int, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}
_lock = threading.Lock()


def subscribe(course_id: int) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    with _lock:
        _subs.setdefault(course_id, set()).add((asyncio.get_running_loop(), q))
    return q


def unsubscribe(course_id: int, q: asyncio.Queue) -> None:
    with _lock:
        subs = _subs.get(course_id, set())
        subs -= {s for s in subs if s[1] is q}
        if not subs:
            _subs.pop(course_id, None)


def blocks_changed(course_id, chapter_id, section_id) -> None:
    """Called by the TEMP trigger on blocks (see db.py), inside the writing statement, on whatever thread wrote."""
    if course_id is None:
        return
    with _lock:
        subs = list(_subs.get(course_id, ()))
    for loop, q in subs:
        try:
            loop.call_soon_threadsafe(q.put_nowait, {"type": "blocks", "chapter_id": chapter_id, "section_id": section_id})
        except RuntimeError:
            pass  # that stream's loop closed; its finally unsubscribes
