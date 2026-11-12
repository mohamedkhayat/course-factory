import os
import socket
from pathlib import Path


def main() -> None:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")  # bge models come from the local HF cache only
    import uvicorn

    from .app import create_app
    from .pi_step import PiBackend

    data_dir = Path(os.environ.get("CF_DATA", Path.home() / ".local/share/course-factory"))
    port = int(os.environ.get("CF_PORT", "8765"))
    # CF_HOST may list several addresses ("127.0.0.1,100.80.43.34" adds the Tailscale one); loopback stays the unpaired host
    hosts = [h.strip() for h in os.environ.get("CF_HOST", "127.0.0.1").split(",") if h.strip()]
    sockets = [socket.create_server((h, port), family=socket.AF_INET6 if ":" in h else socket.AF_INET) for h in hosts]
    uvicorn.Server(uvicorn.Config(create_app(data_dir, PiBackend()), port=port)).run(sockets=sockets)
