import os
from pathlib import Path


def main() -> None:
    import uvicorn

    from .app import create_app
    from .pi_step import PiBackend

    data_dir = Path(os.environ.get("CF_DATA", Path.home() / ".local/share/course-factory"))
    uvicorn.run(create_app(data_dir, PiBackend()), host=os.environ.get("CF_HOST", "127.0.0.1"), port=int(os.environ.get("CF_PORT", "8765")))
