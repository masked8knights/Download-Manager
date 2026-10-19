"""Frozen-aware path resolution (R38).

The same code runs from source (python -m app) and inside a PyInstaller
bundle (one-file or one-dir). Two roots matter, and they are NOT the same
in a frozen build:

BUNDLE_ROOT — read-only resources shipped with the app (icon.ico). In a
    frozen build these live inside the bundle (sys._MEIPASS); in a
    one-file build that is a temporary unpack dir that disappears at exit,
    so nothing writable may ever point here.

USER_ROOT — writable files that must persist across runs (.env, state.json,
    presets.json, downloads/, data/). In a frozen build these live next to
    the executable itself, never inside the temporary unpack dir. Inside an
    AppImage the executable sits on a read-only mount, so the writable root
    is the folder holding the AppImage file itself (the $APPIMAGE env var
    PyInstaller-under-AppImage exposes).

R39 additionally installs the bundled CA certificate: a PyInstaller build
carries the build machine's OpenSSL, whose default CA paths do not exist
on every target OS (Ubuntu's /etc/ssl vs Fedora's /etc/pki/tls), so HTTPS
would fail certificate verification there. The spec bundles cacert.pem and
this module points SSL_CERT_FILE at it before any request is made.

From source both roots are the project root (the parent of app/), so every
existing behavior is unchanged. No secrets are ever printed or logged here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))


def _source_root() -> Path:
    # app/apppaths.py -> the project root.
    return Path(__file__).resolve().parent.parent


def _bundle_root() -> Path:
    if FROZEN:
        # sys._MEIPASS is where PyInstaller unpacks bundled data files.
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return _source_root()


def _user_root() -> Path:
    if FROZEN:
        # Inside an AppImage sys.executable lives on a read-only mount;
        # the AppImage file itself is the portable "next to the exe".
        appimage = os.environ.get("APPIMAGE")
        if appimage:
            return Path(appimage).resolve().parent
        return Path(sys.executable).resolve().parent
    return _source_root()


BUNDLE_ROOT = _bundle_root()
USER_ROOT = _user_root()

# Historical name: most of the app calls the writable root "ROOT".
ROOT = USER_ROOT


def _install_bundled_ca() -> None:
    """Point Python's TLS at the CA certificate bundled in the exe.

    urllib builds its default SSL context from OpenSSL's compile-time
    paths, which match the BUILD machine, not the machine the app runs
    on. If the bundle ships a cacert.pem, use it. setdefault keeps a
    user's own SSL_CERT_FILE (corporate proxy, custom CA) in charge.
    """
    if not FROZEN:
        return
    ca = BUNDLE_ROOT / "cacert.pem"
    if ca.is_file():
        os.environ.setdefault("SSL_CERT_FILE", str(ca))


_install_bundled_ca()
