"""`phewas-server` / `python -m phewas_server`: run the browser locally.

Binds 127.0.0.1 on a free port (or --port), generates a per-launch token unless
PHEWAS_TOKEN is set, prints the tokenised URL and opens it in the default browser.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import webbrowser
from pathlib import Path

from .app import create_app
from .settings import Settings


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="phewas-server")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PHEWAS_PORT", 0)) or None)
    ap.add_argument("--home", help="dataset library directory")
    ap.add_argument("--static", help="built frontend directory (apps/web/dist)")
    ap.add_argument("--no-open", action="store_true", help="do not open a browser")
    ap.add_argument("--token", help="fixed token (default: random per launch, or $PHEWAS_TOKEN)")
    a = ap.parse_args(argv)

    settings = Settings.from_env()
    if a.home:
        settings.home = Path(a.home).expanduser()
    if a.static:
        settings.static_dir = Path(a.static).expanduser()
    if a.token:
        settings.token = a.token
    port = a.port or free_port()
    url = f"http://127.0.0.1:{port}/?token={settings.token}"
    # the shell (Tauri) reads these two lines to connect
    print(f"PHEWAS_PORT={port}", flush=True)
    print(f"PHEWAS_URL={url}", flush=True)
    if settings.static_dir is None:
        print("note: frontend not built (apps/web/dist missing); API only", file=sys.stderr)

    import uvicorn

    app = create_app(settings)
    if not a.no_open and settings.static_dir is not None:
        import threading

        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
