"""R48: a system tray icon so the app can open into the tray and leave
no icon behind when it closes (user ask: "make it open it in tray and
close when the app closes on both windows and linux").

Uses pystray + Pillow (both installed with the app; tkinter has no tray
support of its own). The tray shows the app icon with two entries:
Show (the default action, also fired by a plain left-click) and Quit.

Design rules this module follows (same as qbitstart.py):
- Standalone on purpose: imports nothing from sibling app modules, so
  the TESTS/ scripts can exercise it directly.
- Never raises: if pystray/Pillow are missing, no usable backend exists
  (some Wayland sessions ship no tray at all), or the backend refuses
  detached running, create() returns None and the caller opens the
  window normally — the app must never end up invisible.
- stop() is idempotent and swallows errors; called on app close so the
  icon is removed instead of lingering as a ghost. R48b: stop() runs on
  a daemon thread with a join timeout — a backend whose stop() never
  returns (verified live: the Xorg backend blocks on a display without
  a systray manager) must not freeze the app's close.
- R48b: pystray's visible flag is True even when the icon never docked
  (verified live on X: "Failed to dock icon" logged in the backend
  thread while visible stays True), so visible alone would let the app
  hide its window with nothing in any tray. Backends that expose their
  dock state (_systray_manager on Xorg) must report actually docked;
  backends without that attribute (win32, appindicator) keep visible
  as the authority.

No secrets are ever printed or logged by this module.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

__all__ = ["TrayHandle", "create"]

# How long to wait for the backend to report the icon visible before
# deciding the tray is not actually usable on this desktop.
VISIBLE_WAIT_S = 2.0


# How long stop() waits for the backend to finish before abandoning it
# on its daemon thread (the app must close even if the backend hangs).
STOP_JOIN_S = 3.0


class TrayHandle:
    """A running tray icon; stop() removes it. Idempotent, never raises."""

    def __init__(self, icon) -> None:
        self._icon = icon
        self._stopped = False

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        icon = self._icon

        def _do_stop():
            try:
                icon.stop()
            except Exception:
                pass

        # R48b: the Xorg backend's stop() can block forever when no
        # systray manager owns the selection; run it on a daemon thread
        # and wait only briefly, so app close never freezes on it.
        worker = threading.Thread(target=_do_stop, daemon=True)
        worker.start()
        worker.join(STOP_JOIN_S)

    @property
    def stopped(self) -> bool:
        return self._stopped


def _tray_image(icon_path: str):
    """Load the tray icon image, or None when it cannot be read."""
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        image = Image.open(icon_path)
        image.load()
        return image
    except Exception:
        return None


def create(icon_path: str, title: str,
           on_show: Callable[[], None], on_quit: Callable[[], None],
           log: Callable[[str], None]) -> TrayHandle | None:
    """Build and run a tray icon detached; None when the tray is unusable.

    on_show/on_quit are the app's own callbacks; the tray menu wraps
    them (pystray passes its own icon/item arguments, which are
    discarded here). When create() returns None the caller must keep
    the window visible — that is the fallback for desktops with no
    usable tray.
    """
    try:
        import pystray
    except Exception:
        log("Tray support not installed (pystray missing) — starting in "
            "the window instead.")
        return None

    image = _tray_image(icon_path)
    if image is None:
        log("Tray icon image unreadable — starting in the window instead.")
        return None

    def _show(_icon=None, _item=None) -> None:
        try:
            on_show()
        except Exception:
            pass

    def _quit(_icon=None, _item=None) -> None:
        try:
            on_quit()
        except Exception:
            pass

    try:
        menu = pystray.Menu(
            pystray.MenuItem("Show", _show, default=True),
            pystray.MenuItem("Quit", _quit),
        )
        icon = pystray.Icon("TorboxDownloader", image, title, menu)
        icon.run_detached()
    except Exception as exc:
        log(f"Tray unavailable ({type(exc).__name__}) — starting in the "
            "window instead.")
        return None

    # A backend that sets up but never becomes visible would leave the
    # app invisible once the window is withdrawn, so confirm visibility
    # before the caller may hide anything. R48b: visible alone lies on
    # the Xorg backend (True even when nothing docked), so where the
    # backend exposes its dock state it must also say docked. The
    # abort itself goes through TrayHandle so a hanging backend stop
    # cannot stall this function either.
    handle = TrayHandle(icon)
    deadline = time.monotonic() + VISIBLE_WAIT_S
    while time.monotonic() < deadline and not getattr(icon, "visible", False):
        time.sleep(0.1)
    visible_ok = bool(getattr(icon, "visible", False))
    dock_state = getattr(icon, "_systray_manager", "n/a")
    docked_ok = dock_state == "n/a" or bool(dock_state)
    if not (visible_ok and docked_ok):
        handle.stop()
        log("Tray icon did not appear — starting in the window instead.")
        return None
    return handle
