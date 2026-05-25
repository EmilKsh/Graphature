"""Desktop launcher for Graphature.

This keeps Graphature as a local Streamlit app internally, but presents it in
its own desktop window via pywebview.
"""

from __future__ import annotations

import atexit
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TextIO


ROOT = Path(__file__).resolve().parent
APP_FILE = ROOT / "app.py"
PROJECT_DIR = ROOT / "graphature_project"
LOG_DIR = PROJECT_DIR / "logs"
LOG_FILE = LOG_DIR / "desktop.log"
HOST = "127.0.0.1"
STARTUP_TIMEOUT_SECONDS = 45.0


def main() -> int:
    """Start Streamlit and open Graphature in a desktop window."""

    try:
        import webview
    except ImportError:
        _show_error(
            "Graphature Desktop",
            "pywebview is not installed.\n\nRun:\n  pip install -r requirements.txt\n\n"
            "Then launch Graphature again.",
        )
        return 1

    port = _find_free_port()
    url = f"http://{HOST}:{port}"
    process: subprocess.Popen[str] | None = None
    log_handle: TextIO | None = None

    try:
        process, log_handle = _start_streamlit(port)
        atexit.register(_stop_streamlit, process)
        _wait_for_streamlit(url, process)

        webview.create_window(
            "Graphature",
            url,
            width=1420,
            height=920,
            min_size=(1040, 720),
            background_color="#ffffff",
        )
        webview.start(debug=False)
        return 0
    except Exception as exc:  # noqa: BLE001
        _show_error(
            "Graphature Desktop",
            f"Graphature could not start.\n\n{exc}\n\nLog file:\n{LOG_FILE}",
        )
        return 1
    finally:
        if process is not None:
            _stop_streamlit(process)
        if log_handle is not None:
            log_handle.close()


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def _start_streamlit(port: int) -> tuple[subprocess.Popen[str], TextIO]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = LOG_FILE.open("a", encoding="utf-8")
    command = _streamlit_command(port)
    env = os.environ.copy()
    env.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=creationflags,
    )
    return process, log_handle


def _streamlit_command(port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP_FILE),
        f"--server.address={HOST}",
        f"--server.port={port}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]


def _wait_for_streamlit(url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Streamlit exited early with code {process.returncode}.")
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if 200 <= response.status < 500:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for Streamlit at {url}. Last error: {last_error}")


def _stop_streamlit(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=6)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=6)


def _show_error(title: str, message: str) -> None:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
            return
        except Exception:
            pass
    print(f"{title}: {message}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
