import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from .pi_step import Backend
from .kernels import Kernels, Launcher, LocalLauncher
from .search import SearchModels

if TYPE_CHECKING:
    from .media import Media

Gate = Literal["found", "outline", "chapter_review"]
Role = Literal["course notes", "exercise sheet", "lab", "past exam", "correction", "personal notes", "data"]
Priority = Literal["focus", "normal", "light", "skip"]
Profile = Literal["problem", "recall", "hands_on"]  # Cram Profile: how a Chapter is crammed


@dataclass
class Ctx:
    """What every Generation Run node needs."""

    db: sqlite3.Connection
    backend: Backend
    data_dir: Path
    search: SearchModels
    kernels: "Kernels" = field(default_factory=lambda: Kernels())
    media: "Media | None" = None  # create_app sets it: the local engines (Voices, Dictation), faked in tests
    videos: object = None  # create_app sets it: the Video renderer (videos.Videos), which the Run tells about written Sections
    listen_ahead: object = None  # create_app sets it: makes a written Section's Listen audio in the background (listen.router)
    labs_launcher: Callable[[int], "Launcher"] = field(default=lambda cid: LocalLauncher())  # create_app sets Docker
    files_box: Callable[[int], AbstractContextManager[str]] | None = None  # create_app sets it: the chat's Course files container (sandbox.course_box)

    def course_dir(self, cid: int) -> Path:
        return self.data_dir / "courses" / str(cid)
