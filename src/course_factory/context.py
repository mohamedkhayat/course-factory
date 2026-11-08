import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .pi_step import Backend
from .search import SearchModels

Gate = Literal["found", "outline", "chapter_review"]
Role = Literal["course notes", "exercise sheet", "lab", "past exam", "correction", "personal notes", "data"]
Priority = Literal["focus", "normal", "light", "skip"]


@dataclass
class Ctx:
    """What every Generation Run node needs."""

    db: sqlite3.Connection
    backend: Backend
    data_dir: Path
    search: SearchModels

    def course_dir(self, cid: int) -> Path:
        return self.data_dir / "courses" / str(cid)
