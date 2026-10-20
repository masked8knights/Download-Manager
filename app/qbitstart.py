"""R47: find and start qBittorrent when the app launches and its WebUI
is not reachable (user ask: "the qbittorrent app has to be running as
well. can we make it start when the app starts?").

R49: the tray belongs to qBittorrent, not the app (user: "I wanted it to
start up qbit torrent when it started, and for qbit to be trayed, not
the app"). Before a FRESH launch — only then; a qBittorrent that was
already running keeps its own settings — the app sets qBittorrent's own
config file so it opens hidden into its tray icon. When the app closes,
it closes the qBittorrent it started ("close when the app closes")
through qBittorrent's own shutdown API — never a qBittorrent the app
did not start itself.

R49b, why the config file and not the WebUI: qBittorrent 5.x dropped
every tray/window preference from the WebUI API (verified in
src/webui/api/appcontroller.cpp — neither /app/preferences nor
setPreferences expose anything tray-related; the live read-back on
v5.2.3 returned None for the old 4.x-era keys). The behavior now lives
in the config file instead: [GUI] StartUpWindowState=Hidden plus the
systray and minimize-to-tray preferences. It is written only in the
fresh-launch path — qBittorrent is not running then, so the edit is
safe, and qBittorrent rewrites this file on exit so a running instance
would just overwrite it. Defaults keep this safe even where the file is
missing or unreadable: qBittorrent then simply opens as a normal window.

Stdlib only, standalone on purpose (no sibling imports) so the TESTS/
scripts can exercise it directly. Never raises: every failure is
reported through the log callback and the app keeps working, search
just keeps pointing at the usual hint.

No secrets are ever printed or logged by this module.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

__all__ = ["find_qbittorrent_command", "ensure_running", "TRAY_CONF",
           "apply_tray_config", "find_qbittorrent_conf_path",
           "shutdown_started"]

# R49b: the qBittorrent config-file keys that put it in the tray, as
# (section, key, value) in the INI qBittorrent itself writes. Verified
# against the v5_2_x sources: StartUpWindowState lives under [GUI] and
# migrates away the old StartMinimized; SystrayEnabled defaults true and
# MinimizeToTray defaults false, so all three are set explicitly. With
# these, qBittorrent opens hidden into its tray icon and minimizing
# parks it there too — it never takes a taskbar slot.
TRAY_CONF: tuple[tuple[str, str, str], ...] = (
    ("GUI", "StartUpWindowState", "Hidden"),
    ("Preferences", "General\\SystrayEnabled", "true"),
    ("Preferences", "General\\MinimizeToTray", "true"),
)

# R49: qBittorrent processes THIS app launched. An instance the app found
# already running is never recorded here, so shutdown_started() can tell
# the difference and leave it alone.
_LAUNCHED_LOCK = threading.Lock()
_LAUNCHED: list[subprocess.Popen] = []

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


def find_qbittorrent_conf_path(cmd: list[str] | None = None) -> Path | None:
    """Where this qBittorrent keeps its settings file, best-effort.

    QSettings IniFormat under the org/app name "qBittorrent": the
    standard config dir on Linux (~/.config/qBittorrent/qBittorrent.conf)
    and %APPDATA%/qBittorrent/qBittorrent.ini on Windows. A flatpak
    launch keeps its config inside the sandbox
    (~/.var/app/<id>/config/...). None when the platform or the command
    gives nothing to go on — the caller then just skips the tray setup.
    """
    if cmd and cmd[:2] == ["flatpak", "run"]:
        base = Path.home() / ".var" / "app" / FLATPAK_ID / "config" / "qBittorrent"
        return base / "qBittorrent.conf"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        return Path(appdata) / "qBittorrent" / "qBittorrent.ini"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Preferences" / "qBittorrent" \
            / "qBittorrent.ini"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "qBittorrent" / "qBittorrent.conf"


def apply_tray_config(conf_path: Path | None,
                      log: Callable[[str], None] | None = None
                      ) -> bool:
    """Write the tray keys into qBittorrent's own config file.

    The file (INI, as QSettings writes it) is preserved key for key: only
    the three TRAY_CONF entries are added or replaced, in their sections;
    everything else — the user's own settings included — is left exactly
    as it was. A missing file is created with just those entries
    (qBittorrent merges the rest from its defaults). Never raises; True
    when the file now carries the tray keys, False when nothing could be
    written (conf path unknown, unreadable, ...).
    """
    try:
        if conf_path is None:
            return False
        if conf_path.exists():
            text = conf_path.read_text(encoding="utf-8", errors="replace")
        else:
            text = ""
        lines = text.splitlines()
        wanted: dict[tuple[str, str], str] = {
            (section, key): value for section, key, value in TRAY_CONF}
        seen: set[tuple[str, str]] = set()
        current = ""
        out: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                # Leaving a section: append any of our keys it still lacks,
                # then start the new section.
                for (section, key), value in wanted.items():
                    if section == current and (section, key) not in seen:
                        out.append(f"{key}={value}")
                        seen.add((section, key))
                current = stripped[1:-1]
                out.append(line)
                continue
            replaced = False
            for (section, key), value in wanted.items():
                if section == current and stripped.startswith(f"{key}="):
                    if (section, key) not in seen:
                        out.append(f"{key}={value}")
                        seen.add((section, key))
                    replaced = True
                    break
            if replaced:
                continue
            out.append(line)
        def section_line(name: str) -> str:
            return f"[{name}]"

        for (section, key), value in wanted.items():
            if (section, key) in seen:
                continue
            # Into the section's own header when the file already carries
            # one (it may sit anywhere), a fresh section at the end when
            # it does not — never a duplicate header.
            header_at = None
            insert_at = None
            for idx, line in enumerate(out):
                stripped = line.strip()
                if header_at is not None and stripped.startswith("[") \
                        and stripped.endswith("]"):
                    insert_at = idx  # end of the section: next header
                    break
                if stripped == section_line(section):
                    header_at = idx
            if header_at is not None:
                out.insert(insert_at if insert_at is not None else len(out),
                           f"{key}={value}")
            else:
                out.append(section_line(section))
                out.append(f"{key}={value}")
            seen.add((section, key))
        if out and out[-1] != "":
            out.append("")
        new_text = "\n".join(out)
        if new_text == text:
            return True  # already correct — nothing to write
        conf_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(conf_path.parent), prefix=".qbt-conf-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(new_text)
            os.replace(tmp_name, conf_path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return True
    except Exception as exc:
        if log is not None:
            log(f"qBittorrent tray config could not be written "
                f"({exc or type(exc).__name__}); it will open as a normal "
                "window this time.")
        return False


def _launch_detached(cmd: list[str]) -> subprocess.Popen | None:
    """Start qBittorrent so it outlives this process and opens no console.

    R47b: on POSIX a frozen (PyInstaller one-file) app runs with
    LD_LIBRARY_PATH pointing at its own extracted bundle. Inherited by
    qBittorrent, that makes the system loader resolve qBittorrent's
    libraries against the bundle's older copies and it dies on the spot
    (verified live on Nobara: "libssl.so.3: version `OPENSSL_3.2.0' not
    found"). The child is launched with the loader variables stripped, so
    it sees the system's own libraries, and an early exit is reaped so it
    cannot linger as a zombie under the long-lived app process.
    """
    if sys.platform == "win32":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        proc = subprocess.Popen(cmd, creationflags=flags,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        # R52c: return the handle so ensure_running() records the launch
        # and shutdown_started() can close this qBittorrent when the app
        # closes — before this it returned None on Windows and the app
        # never owned the qBittorrent it had started.
        threading.Timer(10.0, proc.poll).start()
        return proc
    env = {name: value for name, value in os.environ.items()
           if name not in ("LD_LIBRARY_PATH", "LD_PRELOAD",
                           "PYTHONPATH", "PYTHONHOME")}
    proc = subprocess.Popen(cmd, start_new_session=True, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    threading.Timer(10.0, proc.poll).start()
    return proc


def ensure_running(client, autostart: bool,
                   log: Callable[[str], None],
                   max_wait: float = 25.0,
                   launcher: Callable[[list[str]], subprocess.Popen | None]
                           = _launch_detached,
                   finder: Callable[[], list[str] | None]
                   = find_qbittorrent_command,
                   conf_applier: Callable[[list[str]], bool] | None = None
                   ) -> bool:
    """Make sure qBittorrent's WebUI answers; launch it when allowed.

    Probes client.version(); when it fails and autostart is on, finds a
    qBittorrent, sets its config file for the tray (fresh launch only),
    starts it detached and waits up to max_wait seconds for the WebUI to
    come up (qBittorrent needs a few seconds to open the port after its
    window appears). Returns True when the WebUI answers at the end.
    Never raises; every step is narrated through log().
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
    # R49b: the tray treatment happens HERE, on the config file, before
    # the process exists — only a fresh launch reaches this line, so a
    # qBittorrent the user opened themselves keeps the settings they
    # chose. qBittorrent rewrites its config on exit, which is exactly
    # why this must precede the launch.
    if conf_applier is None:
        def conf_applier(cmd_: list[str]) -> bool:
            return apply_tray_config(find_qbittorrent_conf_path(cmd_), log)
    if conf_applier(cmd):
        log("qBittorrent set to open in the tray (starts hidden, "
            "minimizes to tray).")
    try:
        proc = launcher(cmd)
    except Exception as exc:
        log(f"Could not start qBittorrent ({exc or type(exc).__name__}). "
            "Start it yourself, then Search.")
        return False
    if proc is not None:
        # R49: remember this instance as ours so app close can shut it
        # down; a qBittorrent found already running never lands here.
        with _LAUNCHED_LOCK:
            _LAUNCHED.append(proc)
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


def shutdown_started(client) -> bool:
    """R49: close the qBittorrent this app launched, via its own API.

    Called from the app's on_close. When the app never started a
    qBittorrent (the WebUI was already up at launch, or autostart is off),
    nothing is touched and False comes back — an instance the user opened
    themselves outlives the app. Best-effort by design: any WebUI failure
    is swallowed, the app's own close must never stall on this.
    """
    with _LAUNCHED_LOCK:
        ours = bool(_LAUNCHED)
    if not ours:
        return False
    try:
        client.shutdown_app()
    except Exception:
        pass  # already gone, or the WebUI went away first — either is fine
    return True
