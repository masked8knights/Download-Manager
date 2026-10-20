"""R47: find and start qBittorrent when the app launches and its WebUI
is not reachable (user ask: "the qbittorrent app has to be running as
well. can we make it start when the app starts?").

Stdlib only, standalone on purpose (no sibling imports) so the TESTS/
scripts can exercise it directly. Never raises: every failure is
reported through the log callback and the app keeps working, search
just keeps pointing at the usual hint.

No secrets are ever printed or logged by this module.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

__all__ = ["find_qbittorrent_command", "ensure_running"]

FLATPAK_ID = "org.qbittorrent.qBittorrent"


def _flatpak_available() -> bool:
    """True when qBittorrent is installed as a flatpak (common on Nobara)."""
    if not shutil.which("flatpak"):
        return False
    try:
        probe = subprocess.run(
            ["flatpak", "info", FLATPAK_ID],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def find_qbittorrent_command() -> list[str] | None:
    """Locate a launchable qBittorrent, OS-agnostic.

    Order: PATH, then the usual Windows install folders, then the macOS
    bundle, then flatpak (Nobara/Fedora ship it that way). None when
    nothing is found — the caller logs the manual hint instead.
    """
    found = shutil.which("qbittorrent")
    if found:
        return [found]
    if sys.platform == "win32":
        import os
        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "qBittorrent" / "qbittorrent.exe",
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "qBittorrent" / "qbittorrent.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
            / "qBittorrent" / "qbittorrent.exe",
        ]
        for cand in candidates:
            if cand.name and cand.is_file():
                return [str(cand)]
    elif sys.platform == "darwin":
        cand = Path("/Applications/qBittorrent.app/Contents/MacOS/qbittorrent")
        if cand.is_file():
            return [str(cand)]
    if _flatpak_available():
        return ["flatpak", "run", FLATPAK_ID]
    return None


def _launch_detached(cmd: list[str]) -> None:
    """Start qBittorrent so it outlives this process and opens no console."""
    if sys.platform == "win32":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(cmd, creationflags=flags,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(cmd, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_running(client, autostart: bool,
                   log: Callable[[str], None],
                   max_wait: float = 25.0,
                   launcher: Callable[[list[str]], None] = _launch_detached,
                   finder: Callable[[], list[str] | None]
                   = find_qbittorrent_command) -> bool:
    """Make sure qBittorrent's WebUI answers; launch it when allowed.

    Probes client.version(); when it fails and autostart is on, finds a
    qBittorrent, starts it detached and waits up to max_wait seconds for
    the WebUI to come up (qBittorrent needs a few seconds to open the
    port after its window appears). Returns True when the WebUI answers
    at the end. Never raises; every step is narrated through log().
    """
    try:
        client.version()
        return True  # already up — nothing to do
    except Exception:
        pass
    if not autostart:
        return False
    cmd = finder()
    if not cmd:
        log("qBittorrent is not running and could not be found to start "
            "it automatically. Start qBittorrent yourself, then Search.")
        return False
    log("qBittorrent is not running — starting it…")
    try:
        launcher(cmd)
    except Exception as exc:
        log(f"Could not start qBittorrent ({exc or type(exc).__name__}). "
            "Start it yourself, then Search.")
        return False
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        time.sleep(1.0)
        try:
            version = client.version()
            log(f"qBittorrent is up ({version}).")
            return True
        except Exception:
            continue
    log(f"qBittorrent did not answer its WebUI within {int(max_wait)}s of "
        "starting. If it is showing its own window, check Tools → Options → "
        "Web UI (enabled, bypass authentication for localhost), then Search.")
    return False
