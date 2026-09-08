"""`phewas-server` / `python -m phewas_server`: run the browser locally.

Binds 127.0.0.1 on a free port (or --port), generates a per-launch token unless
PHEWAS_TOKEN is set, prints the tokenised URL and opens it in the default browser.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlencode

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
    ap.add_argument(
        "--parent-pid", type=int, help="exit when this process disappears (used by the desktop shell)"
    )
    a = ap.parse_args(argv)

    settings = Settings.from_env()
    if a.home:
        settings.home = Path(a.home).expanduser()
    if a.static:
        settings.static_dir = Path(a.static).expanduser()
    if a.token:
        settings.token = a.token
    port = a.port or free_port()
    url = f"http://127.0.0.1:{port}/?{urlencode({'token': settings.token})}"
    print(f"PHEWAS_PORT={port}", flush=True)
    if settings.static_dir is None:
        print("note: frontend not built (apps/web/dist missing); API only", file=sys.stderr)
    if a.parent_pid:
        watch_parent(a.parent_pid)

    import threading

    import uvicorn

    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():
            print("server failed to start", file=sys.stderr)
            return 1
        time.sleep(0.02)
    # the shell (Tauri) waits for this line: printed only once the socket is listening
    print(f"PHEWAS_HOME={settings.home.resolve()}", flush=True)
    print(f"PHEWAS_URL={url}", flush=True)
    if not a.no_open and settings.static_dir is not None:
        webbrowser.open(url)
    try:
        thread.join()
    except KeyboardInterrupt:
        server.should_exit = True
        thread.join(timeout=5)
    return 0


def _parent_alive(pid: int) -> bool:
    if sys.platform.startswith("win"):
        import ctypes

        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel.GetExitCodeProcess.restype = ctypes.c_int
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return os.getppid() != 1 if pid == os.getppid() else True


def watch_parent(pid: int) -> None:
    """Exit when the process that launched us is gone (the shell crashed or was killed),
    so no orphaned server keeps a RUO dataset open."""
    import threading

    def loop() -> None:
        while True:
            time.sleep(2)
            if not _parent_alive(pid):
                os._exit(0)

    threading.Thread(target=loop, name="parent-watchdog", daemon=True).start()


if __name__ == "__main__":
    sys.exit(main())
