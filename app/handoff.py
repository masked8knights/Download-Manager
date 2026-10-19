"""Single-instance handoff and OS glue for Torbox Downloader (R36).

Round R36 adds the plumbing a desktop app needs once it is launched from
things that are not a terminal: opening a .torrent from a file manager or
a magnet: link from a browser while the app is already running should hand
the new items to the running window and exit, quietly.

This module is stdlib-only and does three jobs. One: a localhost TCP
handoff (claim the port, or forward the startup items to whoever already
holds it). Two: a minimal bencode reader so a double-clicked .torrent can
be turned into a magnet URI without any third-party library. Three: the
self-registration of file associations (.torrent, magnet:) and desktop
toasts, best-effort everywhere, because a helper that throws inside a
tkinter callback is worse than no helper.

Everything here is safe to call from any thread and nothing here ever
raises: the app keeps working if the OS says no.
"""

import hashlib
import json
import socket
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import quote

# Windows-only import, kept inside the functions that need it (winreg does
# not exist on Linux and importing it at module level would break import
# on every non-Windows machine the app runs on).

HANDOFF_PORT = 51717
HANDOFF_MAGIC = b"TORBOX-DOWNLOADER-HANDOFF\n"

_APP_AUMID = "Thaura.TorboxDownloader"
_APP_NAME = "Torbox Downloader"

# R38: what double-clicking a .torrent launches. From source that is the
# interpreter running app/__main__.py; in a frozen build the packed
# executable IS the app, so the file path is passed straight to it.
if getattr(sys, "frozen", False):
    _WIN_OPEN_COMMAND = f'"{sys.executable}" "%1"'
    _LINUX_EXEC_LINE = f'Exec="{sys.executable}" %u\n'
else:
    _MAIN_PY = Path(__file__).resolve().parent / "__main__.py"
    _WIN_OPEN_COMMAND = f'"{sys.executable}" "{_MAIN_PY}" "%1"'
    _LINUX_EXEC_LINE = f'Exec="{sys.executable}" "{_MAIN_PY}" %u\n'


def parse_cli_args(argv: list[str]) -> list[str]:
    """Clean raw argv into items the app understands.

    Strings starting with "magnet:" pass through verbatim. Everything
    else is treated as a path, resolved to an absolute one, and kept
    only if it exists and is a file; directories and phantoms are
    dropped without comment.
    """
    out: list[str] = []
    for arg in argv:
        if arg.startswith("magnet:"):
            out.append(arg)
            continue
        try:
            path = Path(arg).resolve()
        except OSError:
            continue
        try:
            if path.is_file():
                out.append(str(path))
        except OSError:
            continue
    return out


def _bdecode(data: bytes, pos: int = 0):
    """Decode one bencode value starting at pos; return (value, next_pos).

    Raises ValueError on anything malformed or truncated. Strings come
    back as bytes, which is what a torrent's insides actually are.
    """
    c = data[pos:pos + 1]
    if c == b"":
        raise ValueError("truncated bencode data")
    if c == b"i":
        end = data.index(b"e", pos)
        return int(data[pos + 1:end]), end + 1
    if c == b"l":
        pos += 1
        out = []
        while data[pos:pos + 1] != b"e":
            value, pos = _bdecode(data, pos)
            out.append(value)
        return out, pos + 1
    if c == b"d":
        pos += 1
        out = {}
        while data[pos:pos + 1] != b"e":
            key, pos = _bdecode(data, pos)
            if not isinstance(key, bytes):
                raise ValueError("dict key is not a byte string")
            value, pos = _bdecode(data, pos)
            out[key] = value
        return out, pos + 1
    # Byte string: "<decimal length>:<that many bytes>".
    colon = data.index(b":", pos)
    length = int(data[pos:colon])
    start = colon + 1
    if start + length > len(data):
        raise ValueError("byte string runs past end of data")
    return data[start:start + length], start + length


def _bdecode_top_dict(data: bytes):
    """Decode a top-level bencode dict, also keeping each value's raw
    byte slice (start, end). The info dict's slice is hashed in place,
    so no re-encoding is ever needed and the hash matches every other
    client's byte for byte."""
    if data[:1] != b"d":
        raise ValueError("not a bencode dict")
    pos = 1
    values = {}
    slices = {}
    while data[pos:pos + 1] != b"e":
        colon = data.index(b":", pos)
        klen = int(data[pos:colon])
        key = data[colon + 1:colon + 1 + klen]
        pos = colon + 1 + klen
        start = pos
        value, pos = _bdecode(data, pos)
        values[key] = value
        slices[key] = (start, pos)
    return values, slices


def torrent_to_magnet(path: str) -> str:
    """Turn a .torrent file into a magnet URI, or "" on any failure.

    The xt is the sha1 of the bencoded info dict exactly as it sits in
    the file. Trackers come from announce-list first, then the top-level
    announce, deduplicated in first-seen order. Reads are capped at
    10 MB, which is already a bloated metainfo file.
    """
    try:
        file = Path(path)
        if not file.is_file():
            return ""
        with open(file, "rb") as fh:
            data = fh.read(10 * 1024 * 1024)
        values, slices = _bdecode_top_dict(data)
        if b"info" not in slices:
            return ""
        start, end = slices[b"info"]
        info_hash = hashlib.sha1(data[start:end]).hexdigest()
        info = values.get(b"info")
        name = ""
        if isinstance(info, dict) and isinstance(info.get(b"name"), bytes):
            name = info[b"name"].decode("utf-8", "replace")
        trackers: list[str] = []
        seen: set[str] = set()
        candidates: list[bytes] = []
        announce_list = values.get(b"announce-list")
        if isinstance(announce_list, list):
            for group in announce_list:
                if isinstance(group, list):
                    for item in group:
                        if isinstance(item, bytes):
                            candidates.append(item)
        announce = values.get(b"announce")
        if isinstance(announce, bytes):
            candidates.append(announce)
        for raw in candidates:
            text = raw.decode("utf-8", "replace").strip()
            if text and text not in seen:
                seen.add(text)
                trackers.append(text)
        parts = ["xt=urn:btih:" + info_hash]
        if name:
            parts.append("dn=" + quote(name, safe=""))
        for tracker in trackers:
            parts.append("tr=" + quote(tracker, safe=""))
        return "magnet:?" + "&".join(parts)
    except Exception:
        return ""


def _read_line(sock: socket.socket, cap: int = 65536) -> bytes:
    """Read one \\n-terminated line from a socket, capped, without any
    readline buffering surprises. Empty result means the peer hung up."""
    buf = bytearray()
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
        nl = buf.find(b"\n")
        if nl != -1:
            return bytes(buf[:nl])
        if len(buf) > cap:
            raise ValueError("handoff line exceeds 64 KB")
    return bytes(buf)


class SingleInstance:
    """Second-launch handoff: the first app instance holds the port; the
    second one forwards its items to it and exits."""

    def __init__(self, on_items):
        self._on_items = on_items
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.startup_items: list[str] = []

    def claim(self) -> bool:
        """Try to take the handoff port. True means this instance is the
        one that runs. False means another instance answered: forward
        the startup items to it (best-effort) and let the caller exit."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # No SO_REUSEADDR here on purpose: on Windows it would let two
        # instances bind the same port and silently split handoffs.
        try:
            sock.bind(("127.0.0.1", HANDOFF_PORT))
        except OSError:
            sock.close()
            send_items(self.startup_items)
            return False
        try:
            sock.listen(4)
        except OSError:
            sock.close()
            send_items(self.startup_items)
            return False
        self._listener = sock
        return True

    def start(self) -> None:
        """Begin accepting handoff connections in a daemon thread."""
        self._thread = threading.Thread(
            target=self._serve, name="handoff-listener", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Close the listener; the serve loop notices within half a
        second and the thread exits."""
        self._stop.set()
        listener = self._listener
        self._listener = None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass

    def _serve(self) -> None:
        listener = self._listener
        if listener is None:
            return
        try:
            listener.settimeout(0.5)
        except OSError:
            pass
        while not self._stop.is_set():
            try:
                conn, _addr = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._handle(conn)
            except Exception:
                # A malformed handoff must never take the app down; the
                # loop just goes on waiting for the next one.
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _handle(self, conn: socket.socket) -> None:
        magic = _read_line(conn)
        if magic + b"\n" != HANDOFF_MAGIC:
            return
        payload = _read_line(conn)
        if not payload:
            return
        items = json.loads(payload.decode("utf-8", "replace"))
        if not isinstance(items, list):
            return
        items = [item for item in items if isinstance(item, str)]
        cleaned = parse_cli_args(items)
        if cleaned:
            self._on_items(cleaned)


def send_items(items: list[str]) -> bool:
    """Client half of the handoff: push items to the running instance.
    True if it accepted them, False on any failure. Never raises, so the
    second instance can exit quietly either way."""
    try:
        payload = json.dumps(items).encode("utf-8")
        if len(payload) > 65536:
            return False
        with socket.create_connection(("127.0.0.1", HANDOFF_PORT), timeout=2) as sock:
            sock.settimeout(2)
            sock.sendall(HANDOFF_MAGIC + payload + b"\n")
        return True
    except Exception:
        return False


def _win_set_default(key_path: str, value: str) -> None:
    """Create an HKCU key and set its default (unnamed) value."""
    import winreg

    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
    try:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, value)
    finally:
        key.Close()


def register_associations() -> str:
    """Register .torrent and magnet: handlers for this app, best-effort,
    never raises. Returns a human-readable summary for the app log."""
    try:
        command = _WIN_OPEN_COMMAND
        if sys.platform == "win32":
            registered = []
            _win_set_default(r"Software\Classes\.torrent", "TorboxDownloader.Torrent")
            registered.append(r"HKCU\Software\Classes\.torrent -> TorboxDownloader.Torrent")
            _win_set_default(
                r"Software\Classes\TorboxDownloader.Torrent", "Torrent (Torbox Downloader)"
            )
            registered.append(
                r"HKCU\Software\Classes\TorboxDownloader.Torrent -> friendly name"
            )
            from apppaths import BUNDLE_ROOT
            icon = BUNDLE_ROOT / "icon.ico"
            if icon.is_file():
                _win_set_default(
                    r"Software\Classes\TorboxDownloader.Torrent\DefaultIcon", str(icon)
                )
                registered.append("DefaultIcon -> " + str(icon))
            _win_set_default(
                r"Software\Classes\TorboxDownloader.Torrent\shell\open\command", command
            )
            registered.append(".torrent open command -> " + command)
            _win_set_default(r"Software\Classes\magnet\shell\open\command", command)
            registered.append("magnet: open command -> " + command)
            return "registered: " + "; ".join(registered)
        if sys.platform.startswith("linux"):
            desktop_dir = Path.home() / ".local" / "share" / "applications"
            desktop_dir.mkdir(parents=True, exist_ok=True)
            desktop_file = desktop_dir / "torbox-downloader.desktop"
            entry = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                f"Name={_APP_NAME}\n"
                + _LINUX_EXEC_LINE
                + "MimeType=application/x-bittorrent;x-scheme-handler/magnet\n"
                + "NoDisplay=true\n"
            )
            desktop_file.write_text(entry, encoding="utf-8")
            for mime in ("application/x-bittorrent", "x-scheme-handler/magnet"):
                try:
                    subprocess.run(
                        ["xdg-mime", "default", "torbox-downloader.desktop", mime],
                        timeout=15,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                except Exception:
                    # xdg-mime missing or grumpy: the .desktop file is
                    # still in place for the user's own settings tool.
                    pass
            return (
                "registered: " + str(desktop_file)
                + " for application/x-bittorrent and x-scheme-handler/magnet"
            )
        return "file associations are not supported on this platform"
    except Exception as exc:
        return f"file association registration failed: {exc}"


def _ps_quote(text: str) -> str:
    """Make a string safe inside a PowerShell single-quoted literal."""
    return text.replace("'", "''")


def notify(title: str, body: str) -> None:
    """Desktop notification, best-effort, never raises. A toast that
    fails to show is nobody's emergency."""
    try:
        if sys.platform == "win32":
            # ToastText02 has two text nodes: bold title, then body.
            # InnerText XML-escapes the text we hand it, and the single
            # quotes are doubled for PowerShell's own quoting.
            script = (
                "try {\n"
                "  [Windows.UI.Notifications.ToastNotificationManager,"
                " Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null\n"
                "  $t = [Windows.UI.Notifications.ToastNotificationManager]"
                "::GetTemplateContent("
                "[Windows.UI.Notifications.ToastTemplateType]::ToastText02)\n"
                "  $texts = $t.GetElementsByTagName('text')\n"
                f"  $texts.Item(0).InnerText = '{_ps_quote(title)}'\n"
                f"  $texts.Item(1).InnerText = '{_ps_quote(body)}'\n"
                "  $toast = [Windows.UI.Notifications.ToastNotification]::new($t)\n"
                f"  [Windows.UI.Notifications.ToastNotificationManager]"
                f"::CreateToastNotifier('{_APP_AUMID}').Show($toast)\n"
                "} catch {}"
            )
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-WindowStyle",
                    "Hidden",
                    "-Command",
                    script,
                ],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=15,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return
        if sys.platform.startswith("linux"):
            subprocess.run(
                ["notify-send", "-a", _APP_NAME, title, body],
                timeout=15,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return
    except Exception:
        return


def _bencode(obj) -> bytes:
    """Tiny bencode writer, only for the self-test below: build a real
    .torrent in memory without shipping a torrent library."""
    if isinstance(obj, bool):
        raise ValueError("bools have no bencode form here")
    if isinstance(obj, int):
        return b"i" + str(obj).encode("ascii") + b"e"
    if isinstance(obj, bytes):
        return str(len(obj)).encode("ascii") + b":" + obj
    if isinstance(obj, str):
        raw = obj.encode("utf-8")
        return str(len(raw)).encode("ascii") + b":" + raw
    if isinstance(obj, list):
        return b"l" + b"".join(_bencode(item) for item in obj) + b"e"
    if isinstance(obj, dict):
        entries = []
        for key, value in obj.items():
            kraw = key if isinstance(key, bytes) else key.encode("utf-8")
            entries.append((kraw, _bencode(value)))
        entries.sort(key=lambda pair: pair[0])
        return b"d" + b"".join(
            str(len(kraw)).encode("ascii") + b":" + kraw + encoded
            for kraw, encoded in entries
        ) + b"e"
    raise ValueError(f"cannot bencode {type(obj).__name__}")


if __name__ == "__main__":
    # Self-test: pure local, nothing network-facing, no UI.
    kept = parse_cli_args(
        ["magnet:?xt=urn:btih:deadbeef", "definitely-missing.torrent", "magnet:?dn=x"]
    )
    assert kept == ["magnet:?xt=urn:btih:deadbeef", "magnet:?dn=x"], kept
    print("PASS parse_cli_args: magnets kept verbatim, missing paths dropped")

    if len(sys.argv) > 1:
        result = torrent_to_magnet(sys.argv[1])
        print("PASS torrent_to_magnet on given path ->", result or "(empty)")
    else:
        info = {
            b"piece length": 16384,
            b"pieces": b"0123456789abcdef0123",
            b"name": b"selftest.bin",
            b"length": 4,
        }
        tracker_a = "http://tracker.example/announce"
        tracker_b = "http://backup.example/announce"
        blob = _bencode(
            {
                b"announce": tracker_a,
                b"announce-list": [[tracker_a], [tracker_b]],
                b"info": info,
            }
        )
        test_file = Path("handoff-selftest.torrent")
        try:
            test_file.write_bytes(blob)
            magnet = torrent_to_magnet(str(test_file))
            expected_hash = hashlib.sha1(_bencode(info)).hexdigest()
            expected = (
                "magnet:?xt=urn:btih:" + expected_hash
                + "&dn=" + quote("selftest.bin", safe="")
                + "&tr=" + quote(tracker_a, safe="")
                + "&tr=" + quote(tracker_b, safe="")
            )
            assert magnet == expected, (magnet, expected)
            print("PASS torrent_to_magnet round-trip:", magnet)
            print("PASS torrent_to_magnet bad path ->", torrent_to_magnet("no-such.torrent") or "(empty)")
        finally:
            test_file.unlink(missing_ok=True)
    print("PASS self-test complete")
