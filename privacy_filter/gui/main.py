"""Privacy Filter GUI — entry point.

Starts a local Flask server and opens a native window (pywebview)
or falls back to the system browser.
"""

import os
import sys
import socket
import threading
import time
import argparse
from pathlib import Path


def _setup_bundled_tesseract():
    """Configure PATH and TESSDATA_PREFIX for PyInstaller/AppImage bundles."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        tess_dir = os.path.join(base, "tesseract")
        if os.path.isdir(tess_dir):
            os.environ["PATH"] = tess_dir + os.pathsep + os.environ.get("PATH", "")
            tessdata = os.path.join(tess_dir, "tessdata")
            if os.path.isdir(tessdata):
                os.environ["TESSDATA_PREFIX"] = tessdata


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Api:
    """JS-callable API exposed to pywebview for native file operations."""

    def __init__(self, port: int):
        self._port = port

    def save_file(self, url: str, filename: str) -> str:
        """Download a file from the local server and save to Downloads folder."""
        import urllib.request
        from urllib.parse import quote
        downloads = Path.home() / "Downloads"
        downloads.mkdir(exist_ok=True)
        dest = downloads / filename
        counter = 1
        stem, ext = dest.stem, dest.suffix
        while dest.exists():
            dest = downloads / f"{stem} ({counter}){ext}"
            counter += 1
        encoded_url = quote(url, safe="/:?=&")
        urllib.request.urlretrieve(
            f"http://127.0.0.1:{self._port}{encoded_url}", str(dest)
        )
        return str(dest)


_last_heartbeat = 0.0
_HEARTBEAT_TIMEOUT = 60


def _heartbeat_watchdog():
    """Shut down if no heartbeat received for _HEARTBEAT_TIMEOUT seconds."""
    global _last_heartbeat
    while True:
        time.sleep(5)
        if _last_heartbeat > 0 and (time.time() - _last_heartbeat) > _HEARTBEAT_TIMEOUT:
            os._exit(0)


def main():
    _setup_bundled_tesseract()

    parser = argparse.ArgumentParser(description="Privacy Filter GUI")
    parser.add_argument("--port", type=int, default=0, help="Port (0 = auto)")
    parser.add_argument("--no-window", action="store_true",
                        help="Skip native window, use browser only")
    args = parser.parse_args()

    port = args.port or _find_free_port()

    from privacy_filter.gui.server import create_app
    app = create_app()

    is_browser_mode = False

    @app.route("/api/heartbeat")
    def heartbeat():
        global _last_heartbeat
        _last_heartbeat = time.time()
        return "", 204

    @app.route("/api/shutdown", methods=["POST"])
    def shutdown():
        threading.Thread(
            target=lambda: (time.sleep(0.5), os._exit(0)), daemon=True
        ).start()
        return "", 204

    server_ready = threading.Event()

    def run_server():
        import logging
        log = logging.getLogger("werkzeug")
        log.setLevel(logging.WARNING)
        server_ready.set()
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)

    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    server_ready.wait(timeout=5)

    url = f"http://127.0.0.1:{port}"

    if args.no_window:
        is_browser_mode = True

    if not is_browser_mode:
        try:
            import webview
            api = _Api(port)
            webview.create_window(
                "Privacy Filter — TANUH DPI",
                url,
                width=1280,
                height=860,
                min_size=(900, 600),
                js_api=api,
            )
            webview.start()
            return
        except Exception:
            is_browser_mode = True

    if is_browser_mode:
        _start_heartbeat_watchdog()
        _open_browser(url, port)


def _start_heartbeat_watchdog():
    global _last_heartbeat
    _last_heartbeat = time.time()
    threading.Thread(target=_heartbeat_watchdog, daemon=True).start()


def _open_browser(url: str, port: int):
    import webbrowser
    webbrowser.open(url)
    print(f"Privacy Filter GUI running at {url}")
    print("Server will auto-stop ~60s after the browser tab is closed.")
    print("Press Ctrl+C to exit manually.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
