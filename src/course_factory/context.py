import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .pi_step import Backend
from .kernels import Kernels, Launcher, LocalLauncher
from .search import SearchModels

Gate = Literal["found", "outline"]
Role = Literal["course notes", "exercise sheet", "lab", "past exam", "correction", "personal notes", "data"]
Priority = Literal["focus", "normal", "light", "skip"]


@dataclass
class Ctx:
    """What every Generation Run node needs."""

    db: sqlite3.Connection
    backend: Backend
    data_dir: Path
    search: SearchModels
    kernels: "Kernels" = field(default_factory=lambda: Kernels())
    labs_launcher: Callable[[int], "Launcher"] = field(default=lambda cid: LocalLauncher())  # create_app sets Docker

    def course_dir(self, cid: int) -> Path:
        return self.data_dir / "courses" / str(cid)
