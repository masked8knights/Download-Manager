"""Download + consolidation + unpack engine (todo task 4).

Every Torbox API call goes through app/torbox.py's TorboxClient — no Torbox
HTTP code is re-implemented here. This module owns the local side:

- DownloadStore: durable JSON state (default <project root>/state.json, the
  path is a constructor argument), thread-safe, written atomically
  (state.json.tmp then os.replace). One record per download, keyed by btih
  infohash: {"downloads": {<infohash>: {name, magnet, torbox_id, status,
  folder, files: [{file_id, name, size, done}], created_at, gofile_link,
  unpack_dest, unpacked, uploaded_at, archived_at}}}. status is one of:
  adding | held | downloading | complete | failed | unpacking | unpacked.
  delete(infohash) removes one record and saves atomically.
- DownloadEngine: add(magnet) -> infohash, refresh() -> changed records,
  unpack(infohash, dest) on explicit request only. HOLD-BY-DEFAULT: with
  auto_download=False (the default since round R9) a torrent that reaches
  Torbox's complete/cached state goes to status "held" and its files are NOT
  fetched; release(infohash) starts the actual PC download. With
  auto_download=True the pre-R9 flow is kept: refresh() submits pending
  files as soon as the torrent is complete on Torbox. Downloads run in a
  ThreadPoolExecutor owned by the engine (max 3 workers by default);
  refresh() submits pending files non-blocking and reconciles the .results
  future map, finalizing a record to "complete" once every file is done.
  The TorboxClient is a constructor argument (injected), so tests can pass a
  fake object; engine.py itself stays standalone-importable via sys.path.

Proven-live facts respected (see also app/torbox.py's notes):
- request_file_link() returns a CDN URL string, and that URL carries the API
  key as its "token" query param — download links are therefore NEVER
  printed, logged, or stored by this module. They are only ever opened and
  their bytes written to disk; the engine never follows a link anywhere else.
- The CDN answers HTTP 403 to the default Python-urllib User-Agent, so every
  direct file download sends a browser-like User-Agent header
  ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) TorboxDownloader/1.0").
- A freshly created torrent can be status "cached" immediately, and mylist
  rows are matched by infohash (find_by_hash); the create call may also
  answer "Download already queued." for a magnet the account already holds —
  torbox.py's create_torrent tracks the existing torrent in that case, so
  add() simply keeps the infohash key and moves on.
- requestdl needs the API key as the token query param and controltorrent
  delete takes a JSON body — both handled inside torbox.py.

unpack() is EXPLICIT and separate: the poll/refresh path never unpacks. It
extracts .zip pieces with stdlib zipfile; .rar pieces (including multi-part
.part1.rar/.r00 sets) need an external tool found on PATH — 7z, 7za, unrar,
in that order. Nothing is bundled. Pieces stay in the download folder; only
extracted files land in the destination (the pieces folder is what GoFile
gets, task 5).

No secrets are ever printed or logged by this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from apppaths import ROOT  # noqa: F401  (re-exported for callers; R38)

__all__ = [
    "DownloadStore",
    "DownloadEngine",
    "make_folder_name",
    "find_rar_tool",
    "first_rar_part",
    "ROOT",
]

# The browser-like User-Agent: Torbox's CDN 403s the default Python-urllib one
# (proven live). Same header value torbox.py sends for API calls.
DOWNLOAD_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TorboxDownloader/1.0"

READ_CHUNK = 256 * 1024  # 256 KiB chunks, per the design brief
DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_BACKOFF = 5.0  # seconds between attempts, shortened per try
DOWNLOAD_TIMEOUT = 120.0  # per urlopen, not per file

ACTIVE_STATUSES = ("adding", "downloading", "failed")
DONE_MARKERS = ("cached", "complete", "finished")  # lowercase substring match


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _utc_now_iso() -> str:
    """UTC wall-clock ISO timestamp (naive string, UTC by convention).

    Used for gofile_created / gofile_removed_at. Naive-on-disk is deliberate:
    every reader treats a missing tz as UTC (see _parse_utc_iso), so the
    timestamps stay comparable across the Windows test machine and Linux."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def _parse_utc_iso(value) -> Optional[datetime]:
    """Parse a stored ISO timestamp into an aware UTC datetime, or None.

    Missing/garbled values return None (callers treat that as "not tracked").
    A trailing Z is stripped; a naive timestamp is assumed UTC. ISO strings
    that carry an offset are converted to UTC."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1]
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _infohash(magnet: str) -> str:
    """Extract the btih infohash from a magnet URI (lowercase, '' if absent).

    Kept here only as a fallback key check; the engine's matching itself goes
    through torbox.py's find_by_hash()."""
    raw = str(magnet)
    query = raw.split("?", 1)[1] if "?" in raw else raw
    for kv in query.split("&"):
        if kv.lower().startswith("xt=urn:btih:"):
            return kv.split(":", 2)[2].strip().lower()
    return ""


def _torrent_file_infohash(path) -> str:
    """Compute the btih infohash of a local .torrent file (R15).

    Stdlib-only: a minimal bencode scanner finds the raw bytes of the
    top-level "info" dict value and SHA1-hashes them exactly as BitTorrent
    clients do. Returns '' when the file has no usable info dict."""
    blob = Path(path).read_bytes()

    def _decode(buf: bytes, i: int):
        # Returns (value, next_index); dicts/lists/tuples are markers only —
        # the caller re-slices raw bytes for the info dict, so correctness
        # matters for indices, not the reconstructed containers.
        c = buf[i:i + 1]
        if c == b"i":
            j = buf.index(b"e", i)
            return int(buf[i + 1:j]), j + 1
        if c == b"l":
            i += 1
            out = []
            while buf[i:i + 1] != b"e":
                _, i = _decode(buf, i)
            return out, i + 1
        if c == b"d":
            i += 1
            while buf[i:i + 1] != b"e":
                _, i = _decode(buf, i)   # key (string)
                _, i = _decode(buf, i)   # value
            return {}, i + 1
        j = buf.index(b":", i)
        n = int(buf[i:j])
        return buf[j + 1:j + 1 + n], j + 1 + n

    try:
        # Top level must be a dict; walk its keys to find "info" and record
        # the raw slice of its value.
        i = 0
        assert blob[i:i + 1] == b"d"
        i += 1
        while blob[i:i + 1] != b"e":
            key, i = _decode(blob, i)
            value_start = i
            _value, i = _decode(blob, i)
            if key == b"info":
                raw_info = blob[value_start:i]
                return hashlib.sha1(raw_info).hexdigest().lower()
        return ""
    except Exception:
        return ""


def make_folder_name(name: str, max_len: int = 150) -> str:
    """A filesystem-safe folder name for a torrent (Windows + Linux safe).

    Strips/replaces characters invalid on Windows folder names, removes
    control characters, collapses whitespace, and caps the length (~150).
    UTF-8 letters (Arabic, CJK, accented Latin, ...) are kept as-is."""
    text = str(name or "")
    bad = '<>:"/\\|?*'
    cleaned = []
    for char in text:
        if ord(char) < 32 or ord(char) == 127 or char in bad:
            cleaned.append("_")
        else:
            cleaned.append(char)
    text = "".join(cleaned)
    text = re.sub(r"\s+", " ", text).strip().strip("._ ")
    if not text:
        text = "download"
    if len(text) > max_len:
        text = text[:max_len].rstrip().rstrip("._ ")
    return text or "download"


def _new_file(file_id: int, name: str, size: int) -> dict:
    return {"file_id": int(file_id), "name": str(name), "size": int(size),
            "done": False, "error": ""}


class DownloadStore:
    """Durable JSON state for downloads, safe to touch from several threads.

    The whole file is rewritten on every mutation, atomically: a .tmp sibling
    is written first and os.replace()d over the real file, so a crash mid-save
    leaves the previous state intact. A missing or broken state file starts
    the store empty; the app must never die on its own state file."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._downloads: dict = {}
        self.load()

    # ------------------------------------------------------------ persistence

    def load(self) -> None:
        with self._lock:
            self._downloads = {}
            try:
                raw = self.path.read_text(encoding="utf-8")
                data = json.loads(raw) if raw.strip() else {}
            except FileNotFoundError:
                return
            except (OSError, ValueError):
                return  # broken state file: start empty, never crash
            rows = data.get("downloads") if isinstance(data, dict) else None
            if not isinstance(rows, dict):
                rows = {}
            for key, record in rows.items():
                if isinstance(record, dict):
                    self._downloads[str(key)] = record

    def save(self) -> None:
        with self._lock:
            payload = {"downloads": self._downloads}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp, self.path)

    # ---------------------------------------------------------------- queries

    def get(self, infohash: str) -> Optional[dict]:
        with self._lock:
            record = self._downloads.get(str(infohash))
            return dict(record) if record is not None else None

    def all(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._downloads.items()}

    def has_downloading(self) -> bool:
        """R36 optimization: one flat pass over the statuses, no per-record
        dict copies. The UI's one-second progress tick calls this first and
        skips the whole-store deep copy when nothing is downloading."""
        with self._lock:
            return any(v.get("status") == "downloading"
                       for v in self._downloads.values())

    def has_active(self) -> bool:
        """R36 optimization: True while any record is still moving on
        Torbox or to the PC. The poll loop skips its network pass when this
        is False (nothing to refresh), which is most of the app's idle
        life — the old code polled the account every 3 s regardless."""
        with self._lock:
            return any(v.get("status") in ACTIVE_STATUSES
                       for v in self._downloads.values())

    # --------------------------------------------------------------- mutators

    def upsert(self, record: dict) -> str:
        """Insert or replace one download record (copied). Keyed by infohash."""
        key = str(record.get("infohash") or _infohash(record.get("magnet", "")))
        if not key:
            raise ValueError("record needs an infohash or a magnet with a btih xt")
        with self._lock:
            fresh = dict(record)
            fresh["infohash"] = key
            self._downloads[key] = fresh
            self.save()
        return key

    def update(self, infohash: str, **fields) -> Optional[dict]:
        """Set fields on one record. Returns the updated copy, or None if absent."""
        with self._lock:
            record = self._downloads.get(str(infohash))
            if record is None:
                return None
            record.update(fields)
            self.save()
            return dict(record)

    def delete(self, infohash: str) -> bool:
        """Remove one record entirely and save atomically.

        Local files are NOT touched here — deleting a record's folder is the
        caller's job (the UI does it with a download-root safety check).
        Returns True if the record existed, False if it did not."""
        with self._lock:
            key = str(infohash)
            if key not in self._downloads:
                return False
            del self._downloads[key]
            self.save()
        return True

    def mark_file(self, infohash: str, file_id: int, done: bool = True,
                  error: str = "") -> None:
        with self._lock:
            record = self._downloads.get(str(infohash))
            if record is None:
                return
            file_id = int(file_id)
            for finfo in record.get("files", []):
                if int(finfo.get("file_id", 0)) == file_id:
                    finfo["done"] = bool(done)
                    finfo["error"] = "" if done else str(error)
                    break
            self.save()

    def files_done_count(self, infohash: str) -> int:
        record = self.get(infohash)
        if record is None:
            return 0
        return sum(1 for f in record.get("files", []) if f.get("done"))


# -------------------------------------------------------------- rar tooling


def find_rar_tool():
    """Locate an external .rar extractor on PATH: 7z, then 7za, then unrar.

    Returns (tool_name, path) or ("", ""). Nothing is bundled — when none is
    found, .rar unpacking is impossible and the caller must say so clearly.
    (7z handles multi-part sets; unrar too when given the first .part file.)"""
    for tool in ("7z", "7za", "unrar"):
        path = shutil.which(tool)
        if path:
            return tool, path
    return "", ""


def first_rar_part(folder) -> Optional[Path]:
    """The first .partNN.rar of a multi-part set in folder (or the single .rar).

    Extracting the lowest part with 7z/unrar pulls in the whole set as long as
    all parts sit in the same folder (they do: one folder per download)."""
    folder = Path(folder)
    part_files, plain = [], []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".rar":
            continue
        match = re.search(r"\.part(\d+)\.rar$", path.name, re.IGNORECASE)
        if match:
            part_files.append((int(match.group(1)), path))
        else:
            plain.append(path)
    if part_files:
        part_files.sort(key=lambda pair: pair[0])
        return part_files[0][1]
    if plain:
        return plain[0]
    return None


def _extract_with_tool(tool: str, tool_path: str, archive: Path, dest: Path) -> bool:
    dest.mkdir(parents=True, exist_ok=True)
    if tool in ("7z", "7za"):
        command = [tool_path, "x", "-y", f"-o{dest}", str(archive)]
    else:  # unrar: destination needs a trailing separator to be read as a folder
        command = [tool_path, "x", "-y", str(archive), str(dest) + os.sep]
    try:
        result = subprocess.run(command, capture_output=True, timeout=3600)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _extract_zip(archive: Path, dest: Path) -> bool:
    """stdlib zipfile extraction; tolerant of only the failures it can have."""
    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
        return True
    except (OSError, zipfile.BadZipFile, EOFError, ValueError):
        return False


# ------------------------------------------------------------ download fetch


class DownloadCancelled(RuntimeError):
    """Raised mid-stream when the app's Stop button cancels a download.

    Carries no link text (links may carry the API key). Callers clean up the
    .part file and leave the record for a later release() to retry."""


def _fetch_to_file(link: str, dest_path: Path,
                   should_stop: Optional[Callable[[], bool]] = None) -> None:
    """Stream one CDN link into dest_path in chunks. Writes nothing else.

    Sends the browser-like User-Agent (the CDN 403s the default Python one,
    proven live). The link is used for exactly one thing: its bytes to disk.
    It is never printed, logged, or stored — the requestdl link carries the
    API key as a query param. should_stop, when given, is checked before
    every chunk read and raises DownloadCancelled so a Stop takes effect
    mid-file rather than only between files."""
    request = urllib.request.Request(
        link, headers={"User-Agent": DOWNLOAD_USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
        with open(dest_path, "wb") as fh:
            while True:
                if should_stop is not None and should_stop():
                    raise DownloadCancelled("download cancelled")
                chunk = response.read(READ_CHUNK)
                if not chunk:
                    break
                fh.write(chunk)


# ---------------------------------------------------------------- the engine


class DownloadEngine:
    """Adds torrents to Torbox, polls the account, and pulls the files down
    into one folder per download (named after the torrent). Consolidation
    only: unpack() and any GoFile step are separate, explicit calls.

    The TorboxClient is injected (constructor argument) so tests can pass a
    fake; production code passes torbox.TorboxClient(api_key). No secrets are
    ever printed or logged.

    auto_download (default False since round R9): False = hold on Torbox — a
    complete/cached torrent goes to "held" and nothing is fetched until
    release(infohash) is called; True = the old behavior, files are fetched
    automatically as soon as the torrent is complete on Torbox."""

    def __init__(self, api_key: str, state_path, download_root,
                 max_workers: int = 3, client: Optional[Any] = None,
                 auto_download: bool = False):
        if client is None:
            from torbox import TorboxClient  # deferred: engine stays importable
            client = TorboxClient(api_key)
        self.client = client
        self.store = DownloadStore(state_path)
        self.download_root = Path(download_root)
        self.auto_download = bool(auto_download)
        self.max_workers = max(1, int(max_workers))
        self._pool = ThreadPoolExecutor(max_workers=self.max_workers,
                                        thread_name_prefix="dl")
        self._results: dict = {}  # (infohash, file_id) -> Future
        self._results_lock = threading.Lock()
        self._cancel_lock = threading.Lock()
        self._cancelled: set = set()  # infohashes cancelled by the Stop button

    # ------------------------------------------------------------- life cycle

    def shutdown(self, wait: bool = True) -> None:
        """Stop the worker pool (the tkinter app calls this at exit)."""
        self._pool.shutdown(wait=wait)

    # -------------------------------------------------------------- stopping

    def cancel(self, infohash: str) -> None:
        """Stop this download (the app's Stop button): any in-flight chunk
        read aborts, pending .part files are cleaned up by the workers, the
        record goes back to "held" (so the activity bar stops showing it and
        refresh() stops resubmitting), and further submissions are refused
        until release() runs again. Resume = press Download again."""
        with self._cancel_lock:
            self._cancelled.add(infohash)
        record = self.store.get(infohash)
        if record is not None and record.get("status") == "downloading":
            self.store.update(infohash, status="held")

    def resume(self, infohash: str) -> None:
        """Clear a previous cancel() (release() calls it before submitting)."""
        with self._cancel_lock:
            self._cancelled.discard(infohash)

    def _is_cancelled(self, infohash: str) -> bool:
        with self._cancel_lock:
            return infohash in self._cancelled

    # ------------------------------------------------------------------- add

    def add(self, magnet: str, name: str = "") -> str:
        """Add a magnet to the account and the store. Returns the infohash key.

        torbox.py's create_torrent dedupes ("Download already queued.") and
        returns the existing torrent's id, so re-adding is safe. The real name
        comes from find_by_hash when the caller does not supply one; a freshly
        created torrent can already be "cached", so the lookup runs right away
        and refresh() picks it up otherwise."""
        if not magnet or not str(magnet).strip():
            raise ValueError("add() needs a magnet URI")
        magnet = str(magnet).strip()
        infohash = _infohash(magnet)
        if not infohash:
            raise ValueError("magnet URI has no btih infohash")
        torrent_id = self.client.create_torrent(magnet)
        real_name = str(name or "").strip()
        if not real_name:
            try:
                match = self.client.find_by_hash(magnet)
            except Exception:
                match = None
            if match is not None and match.name:
                real_name = match.name
        record = {
            "infohash": infohash,
            "name": real_name,
            "magnet": magnet,
            "torbox_id": int(torrent_id or 0),
            "status": "adding",
            "folder": "",
            "files": [],
            "created_at": _now(),
            "gofile_link": None,
            "unpack_dest": "",
            "unpacked": False,
            "uploaded_at": None,
            "archived_at": None,
        }
        self.store.upsert(record)
        return infohash

    def add_torrent_file(self, path, name: str = "") -> str:
        """Add a local .torrent file to the account and the store (R15).

        Drag-and-drop path: upload the file bytes via createtorrent's file
        variant, derive the infohash locally (stdlib bencode + SHA1) so the
        store needs no magnet, and reuse find_by_hash for the real name.
        Returns the infohash key. Mirrors add()'s record shape exactly."""
        blob_path = Path(path)
        if not blob_path.is_file():
            raise ValueError(f"not a file: {blob_path}")
        infohash = _torrent_file_infohash(blob_path)
        if not infohash:
            raise ValueError(f"{blob_path.name} has no usable info dict (infohash)")
        torrent_id = self.client.create_torrent_file(str(blob_path))
        real_name = str(name or "").strip()
        if not real_name:
            try:
                match = self.client.find_by_hash(infohash)
            except Exception:
                match = None
            if match is not None and match.name:
                real_name = match.name
        if not real_name:
            real_name = blob_path.stem
        record = {
            "infohash": infohash,
            "name": real_name,
            "magnet": "",
            "torbox_id": int(torrent_id or 0),
            "status": "adding",
            "folder": "",
            "files": [],
            "created_at": _now(),
            "gofile_link": None,
            "unpack_dest": "",
            "unpacked": False,
            "uploaded_at": None,
            "archived_at": None,
        }
        self.store.upsert(record)
        return infohash

    def adopt(self, torrent) -> str:
        """Track a torrent that is ALREADY on the Torbox account (R21).

        The TORBOX FILES panel lists account torrents the app never added
        itself; making a GoFile link for one needs a store record first.
        This builds one straight from a TorrentInfo and never calls
        createtorrent (the torrent exists on the account already). If the
        store already tracks that infohash, the existing record is left
        exactly as it is and returned. HOLD-MODE semantics: a torrent
        already complete/cached on Torbox is stored with its file list and
        status "held" (release() then fetches it on request); anything else
        goes in as "adding", so the ordinary refresh() pass picks it up and
        holds it when Torbox finishes. Returns the infohash."""
        infohash = str(getattr(torrent, "hash", "") or "").strip().lower()
        if not infohash:
            raise ValueError("that torrent has no infohash, so it cannot be tracked")
        if self.store.get(infohash) is not None:
            return infohash
        status = str(getattr(torrent, "status", "") or "").lower()
        done = any(marker in status for marker in DONE_MARKERS)
        files = []
        if done:
            # file_id 0 is a REAL Torbox answer, not a missing id: cached
            # single-file torrents come back with id 0 (proven live on 241
            # of 760 account torrents, and requestdl accepts file_id=0).
            # Filtering it out here left such torrents with an empty file
            # list forever — the "bar shows nothing, bottom says Linking"
            # bug of October 2026.
            for tf in getattr(torrent, "files", None) or []:
                files.append({"file_id": int(getattr(tf, "file_id", 0) or 0),
                              "name": str(tf.name or ""),
                              "size": int(tf.size or 0),
                              "done": False})
        self.store.upsert({
            "infohash": infohash,
            "name": str(getattr(torrent, "name", "") or infohash),
            "magnet": "",
            "torbox_id": int(getattr(torrent, "id", 0) or 0),
            "status": "held" if done else "adding",
            "folder": "",
            "files": files,
            "created_at": _now(),
            "gofile_link": None,
            "unpack_dest": "",
            "unpacked": False,
            "uploaded_at": None,
            "archived_at": None,
        })
        return infohash

    # --------------------------------------------------------------- refresh

    def refresh(self) -> dict:
        """One poll pass over the account. Returns {infohash: record} for the
        downloads whose status or file set changed.

        Locates every active record via find_by_hash first, then torbox_id in
        mylist(). Not found + "adding" = still processing on Torbox's side,
        left alone. HOLD MODE (auto_download=False, the default): a torrent
        that reaches Torbox's complete/cached state while its record is still
        "adding" goes to "held" — the file list is stored but nothing is
        fetched until release(infohash). Old mode (auto_download=True): the
        pending files are submitted to the worker pool right away. In both
        modes a record already "downloading" keeps its pending files
        submitting (resume-by-size unchanged), and when all files are done
        the record flips to "complete". Per-file failures keep the record
        "downloading" with an error note; a later refresh() retries them."""
        changed: dict = {}
        # R36 optimization: with no record in an active state there is
        # nothing to refresh, so the account is not polled at all — the old
        # pass hit mylist() every 3 s even on a completely idle app.
        if not self.store.has_active():
            return changed
        try:
            torrents = self.client.mylist()
        except Exception as exc:
            raise RuntimeError(f"Torbox poll failed: {exc}") from exc
        by_id = {t.id: t for t in torrents if t.id}
        for infohash, record in list(self.store.all().items()):
            if record.get("status") not in ACTIVE_STATUSES:
                continue
            torrent = None
            try:
                torrent = self.client.find_by_hash(record.get("magnet", ""))
            except Exception:
                torrent = None
            if torrent is None:
                torrent = by_id.get(record.get("torbox_id") or 0)
            if torrent is None:
                # "adding" rows may still be processing; leave them for later.
                continue
            fields = {"torbox_id": int(torrent.id)}
            if torrent.name and torrent.name != record.get("name"):
                fields["name"] = torrent.name
                record["name"] = torrent.name
                if record.get("folder"):
                    # The folder name is fixed at first download; keep it in
                    # step with the real name when it was still unknown.
                    pass
            record.update(fields)
            self.store.update(infohash, **fields)

            status = (torrent.status or "").lower()
            if not any(marker in status for marker in DONE_MARKERS):
                # Torbox is still fetching the torrent itself. In old-mode a
                # record leaves "adding" now; in hold-mode it stays "adding"
                # until Torbox completes, then goes to "held".
                if self.auto_download and record.get("status") == "adding":
                    self.store.update(infohash, status="downloading")
                    record["status"] = "downloading"
                    changed[infohash] = self.store.get(infohash)
                continue
            if not torrent.files:
                continue

            if not self.auto_download and record.get("status") == "adding":
                # Hold: remember the file list, fetch nothing. Id 0 kept —
                # see the note in adopt().
                if not record.get("files"):
                    file_list = [_new_file(f.file_id, f.name, f.size)
                                 for f in torrent.files]
                    self.store.update(infohash, files=file_list)
                    record["files"] = file_list
                self.store.update(infohash, status="held")
                record["status"] = "held"
                changed[infohash] = self.store.get(infohash)
                continue

            changed[infohash] = self._fetch_files(infohash, record,
                                                  torrent.files)
        self._reap_finished()
        return changed

    def release(self, infohash: str) -> None:
        """Start fetching a held (or failed) download's files to this PC.

        Sets the status back to "downloading" and submits the pending files
        through the same internal path the old auto flow used. The file list
        was stored when the record was held; if it never was (an older record
        that went straight to held with no files seen), one lookup against
        Torbox fills it in before submitting. Never touches the Torbox
        account beyond the read-only lookups."""
        record = self.store.get(infohash)
        if record is None:
            raise KeyError(f"no download with infohash {infohash}")
        if record.get("status") not in ("held", "failed"):
            raise ValueError(
                f"'{record.get('name') or infohash}' is not held "
                f"(status: {record.get('status')}); nothing to release")
        if not record.get("files"):
            torrent = None
            try:
                torrent = self.client.find_by_hash(record.get("magnet", ""))
            except Exception:
                torrent = None
            if torrent is None or not torrent.files:
                try:
                    by_id = {t.id: t for t in self.client.mylist() if t.id}
                    torrent = by_id.get(record.get("torbox_id") or 0)
                except Exception:
                    torrent = None
            if torrent is not None and torrent.files:
                file_list = [_new_file(f.file_id, f.name, f.size)
                             for f in torrent.files]
                self.store.update(infohash, files=file_list)
                record["files"] = file_list
        if not record.get("files"):
            raise ValueError(
                f"'{record.get('name') or infohash}' has no file list yet; "
                "try again once Torbox lists the torrent's files")
        if self._is_cancelled(infohash):
            # R23: the Stop button may have been pressed while this release
            # was starting. Refuse instead of silently resuming — the
            # explicit Download button calls resume() first when the user
            # deliberately starts the download again.
            raise ValueError(
                f"'{record.get('name') or infohash}' was stopped; "
                "press Download again to resume it")
        self._fetch_files(infohash, record)

    def _fetch_files(self, infohash: str, record: dict,
                     torrent_files: Optional[list] = None) -> dict:
        """The shared submission path: store the file list if it is not there
        yet, submit pending files to the pool non-blocking, and finalize the
        record to "complete" once every file is done. Used by refresh()'s
        auto path and by release(). Returns the updated record."""
        folder = self._folder_for(record)
        if torrent_files and not record.get("files"):
            file_list = [_new_file(f.file_id, f.name, f.size)
                         for f in torrent_files]
            self.store.update(infohash, files=file_list)
            record["files"] = file_list
        files = record.get("files", [])
        pending = [f for f in files if not f.get("done")]
        if pending:
            self.store.update(infohash, status="downloading")
            record["status"] = "downloading"
            if self._per_file_safe(files):
                self._submit_pending(infohash, record, pending, folder)
            else:
                # No usable per-file ids (Torbox answers id 0 for some files
                # of multi-file torrents too — 519 of 760 on one account):
                # per-file requestdl links would collide or miss files, so
                # the whole torrent comes down as one zip instead.
                self._submit_zip(infohash, record, folder)
        if self._all_done(infohash):
            self.store.update(infohash, status="complete")
            record["status"] = "complete"
        return self.store.get(infohash)

    def _folder_for(self, record: dict) -> Path:
        """The download's folder: <download_root>/<safe name>, created once and
        reused (the name comes from the torrent's real name once known)."""
        name = record.get("name") or record.get("infohash") or "download"
        folder = self.download_root / make_folder_name(name)
        if not record.get("folder") and record.get("infohash"):
            self.store.update(record["infohash"], folder=str(folder))
            record["folder"] = str(folder)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _submit_pending(self, infohash: str, record: dict,
                        pending: list, folder: Path) -> None:
        """Submit pending files to the pool, non-blocking. A file already
        running in the pool is not resubmitted. Submissions are refused while
        the download is cancelled (the Stop button); release() clears that."""
        if self._is_cancelled(infohash):
            return
        with self._results_lock:
            for fileinfo in pending:
                key = (infohash, int(fileinfo["file_id"]))
                existing = self._results.get(key)
                if existing is not None and not existing.done():
                    continue
                future = self._pool.submit(
                    self._download_file, infohash, record, fileinfo, folder)
                self._results[key] = future

    def _reap_finished(self) -> None:
        """Drop finished futures from the map (results were recorded by the
        workers themselves)."""
        with self._results_lock:
            self._results = {k: f for k, f in self._results.items()
                             if not f.done()}

    @staticmethod
    def _per_file_safe(files: list) -> bool:
        """True when every file can get its own requestdl link: a single
        file (its id 0 is proven to work — Torbox answers id 0 for cached
        single-file torrents), or every id present, positive, and unique.
        False means the whole-torrent zip route is needed. An empty list is
        never safe: there is nothing to download per-file."""
        if not files:
            return False
        if len(files) == 1:
            return True
        ids = [int(f.get("file_id") or 0) for f in files]
        return all(i > 0 for i in ids) and len(set(ids)) == len(ids)

    def _submit_zip(self, infohash: str, record: dict, folder: Path) -> None:
        """Submit the whole-torrent zip job once (pool key (infohash, -1));
        a job already running is not resubmitted."""
        with self._results_lock:
            key = (infohash, -1)
            existing = self._results.get(key)
            if existing is not None and not existing.done():
                return
            future = self._pool.submit(self._download_zip_task, infohash,
                                       record, folder)
            self._results[key] = future

    def _download_zip_task(self, infohash: str, record: dict,
                           folder: Path) -> bool:
        """Worker-pool job for the zip route: download the whole torrent as
        one zip (request_zip_link — Torbox's own bulk export) and extract it
        into the download folder, so the pieces on disk match the recorded
        file names and GoFile/unpack see exactly what a per-file download
        would have produced. Three attempts, then the record stays
        "downloading" for a later refresh() to retry — same shape as the
        per-file path. Never logs the link (it may carry the API key)."""
        part_path = folder / ".part-zip"
        last_error = ""
        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            if self._is_cancelled(infohash):
                self._unlink_quietly(part_path)
                return False
            try:
                link = self.client.request_zip_link(
                    int(record.get("torbox_id") or 0))
                _fetch_to_file(link, part_path,
                               should_stop=lambda: self._is_cancelled(infohash))
                break
            except DownloadCancelled:
                self._unlink_quietly(part_path)
                return False
            except (OSError, urllib.error.URLError, ValueError, RuntimeError) as exc:
                last_error = str(exc) or type(exc).__name__
                if attempt < DOWNLOAD_ATTEMPTS:
                    time.sleep(DOWNLOAD_BACKOFF * attempt * 0.2)
        else:
            self.store.update(infohash, error=last_error[:200])
            return False
        if self._is_cancelled(infohash):
            self._unlink_quietly(part_path)
            return False
        if not _extract_zip(part_path, folder):
            # Extraction failed (corrupt zip, or a nested layout): keep the
            # zip itself as the download's piece — unpack() can still work
            # on a .zip sitting in the download folder.
            keep = folder / (make_folder_name(str(record.get("name")
                                                      or infohash)) + ".zip")
            try:
                os.replace(part_path, keep)
            except OSError:
                pass
        else:
            self._unlink_quietly(part_path)
        files = record.get("files", [])
        for f in files:
            f["done"] = True
        self.store.update(infohash, files=files, status="complete")
        return True

    @staticmethod
    def _unlink_quietly(path: Path) -> None:
        try:
            path.unlink()
        except OSError:
            pass

    def _all_done(self, infohash: str) -> bool:
        record = self.store.get(infohash)
        if record is None:
            return False
        files = record.get("files", [])
        return bool(files) and all(f.get("done") for f in files)

    # ------------------------------------------------------------ downloading

    def _download_file(self, infohash: str, record: dict,
                       fileinfo: dict, folder: Path) -> bool:
        """Worker-pool job: fetch one file, 3 attempts with a short backoff.

        Writes to a temp file ".part-<file_id>" in the same folder, then
        os.replace()s it onto the final name (atomic: a half-written file is
        never mistaken for a done one). A final file already at the right size
        means resume: skip. On final failure the record stays "downloading"
        with a per-file error note; a later refresh() retries."""
        file_id = int(fileinfo["file_id"])
        raw_name = str(fileinfo.get("name") or "").replace("/", "_").replace("\\", "_")
        final_name = make_folder_name(raw_name) if raw_name else f"file-{file_id}"
        final_path = folder / final_name
        part_path = folder / f".part-{file_id}"
        expected = int(fileinfo.get("size") or 0)
        try:
            if final_path.exists() and (not expected
                                        or final_path.stat().st_size == expected):
                self.store.mark_file(infohash, file_id, done=True)
                return True
        except OSError:
            pass
        last_error = ""
        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            if self._is_cancelled(infohash):
                self._unlink_quietly(part_path)
                return False
            try:
                link = self.client.request_file_link(int(record.get("torbox_id") or 0),
                                                     file_id)
                _fetch_to_file(link, part_path,
                               should_stop=lambda: self._is_cancelled(infohash))
                os.replace(part_path, final_path)
                self.store.mark_file(infohash, file_id, done=True)
                return True
            except DownloadCancelled:
                # Stop button pressed mid-file: clean up, leave the record
                # alone (cancel() already put it back to "held").
                self._unlink_quietly(part_path)
                return False
            except (OSError, urllib.error.URLError, ValueError, RuntimeError) as exc:
                last_error = str(exc) or type(exc).__name__
                if attempt < DOWNLOAD_ATTEMPTS:
                    time.sleep(DOWNLOAD_BACKOFF * attempt * 0.2)
        try:
            part_path.unlink()
        except OSError:
            pass
        # Stays "downloading" so a later refresh() retries; the error note is
        # per file and never contains the link (it may carry the API key).
        self.store.mark_file(infohash, file_id, done=False,
                             error=last_error[:200])
        return False

    # ---------------------------------------------------------------- unpack

    def unpack(self, infohash: str, dest) -> list:
        """Extract archives from the download folder into dest. EXPLICIT and
        separate — refresh() never calls this; the UI calls it on user choice.

        .zip pieces: stdlib zipfile. .rar pieces (incl. multi-part sets):
        an external tool from PATH — 7z, 7za, unrar, in that order; a clear
        error names the missing tool when none is installed (nothing bundled).
        Pieces stay in the download folder; only extracted files land in dest.
        dest is created if missing. On success: unpacked=True, unpack_dest=dest,
        status stays "complete" (semantics unchanged). Returns the extracted
        paths."""
        record = self.store.get(infohash)
        if record is None:
            raise KeyError(f"no download with infohash {infohash}")
        if record.get("status") != "complete":
            raise ValueError(
                f"'{record.get('name') or infohash}' is not complete "
                f"(status: {record.get('status')}); nothing to unpack yet")
        folder = Path(record.get("folder") or "")
        if not folder.is_dir():
            raise FileNotFoundError(f"download folder missing: {folder}")
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        extracted: list = []
        before = set(self._list_new(dest))
        failed_zips: list = []
        archives = sorted(p for p in folder.iterdir()
                          if p.is_file() and p.suffix.lower() in (".zip", ".rar"))
        for archive in archives:
            if archive.suffix.lower() == ".zip":
                if _extract_zip(archive, dest):
                    extracted.extend(self._list_new(dest))
                else:
                    failed_zips.append(archive.name)
        if any(a.suffix.lower() == ".rar" for a in archives):
            tool, tool_path = find_rar_tool()
            if not tool:
                raise RuntimeError(
                    "no .rar extractor found on PATH: install 7-Zip (7z), "
                    "7za, or unrar to unpack .rar archives")
            first = first_rar_part(folder)
            if first is None:
                raise FileNotFoundError("no .rar file found in the download folder")
            if not _extract_with_tool(tool, tool_path, first, dest):
                raise RuntimeError(f"{tool} failed to extract {first.name}")
            extracted.extend(p for p in self._list_new(dest) if p not in before)
        if failed_zips:
            raise RuntimeError("zip extraction failed for: "
                               + ", ".join(failed_zips))
        extracted = [p for p in extracted if p not in before] or extracted
        self.store.update(infohash, unpacked=True, unpack_dest=str(dest),
                          status="complete")
        return extracted

    @staticmethod
    def _list_new(dest: Path) -> list:
        return sorted(str(p) for p in dest.rglob("*") if p.is_file())

    # ------------------------------------------------------- GoFile TTL (task 7)

    def expire_gofile_links(self, ttl_days: int = 30,
                            deleter: Optional[Callable[[str], bool]] = None,
                            ) -> tuple:
        """Archive downloads whose GoFile content is older than ttl_days.

        Scans the store for records that have gofile_link AND gofile_folder_id
        AND a gofile_created timestamp older than ttl_days (UTC-aware parsing;
        naive stored timestamps are treated as UTC; a missing gofile_created
        means "not tracked" and NEVER expires).

        The actual GoFile deletion is injected: deleter(folder_id) -> bool is
        called once per expiring record (production passes
        lambda fid: self.gofile.delete_contents([fid]); the engine itself has
        no GoFile client). On success the record is archived in place:
        gofile_link / gofile_folder_id / gofile_created are cleared, archived
        is set True, gofile_removed_at records when. Local files are NEVER
        touched by this method. A record whose deleter raises or returns False
        is left untouched this pass (it retries next cycle) and lands in the
        failed list.

        Returns (expired, failed): two lists of infohashes. No links or tokens
        are ever logged or printed here."""
        if not callable(deleter):
            raise ValueError("expire_gofile_links needs a deleter(folder_id) callable")
        try:
            ttl_days = int(ttl_days)
        except (TypeError, ValueError):
            raise ValueError("ttl_days must be an integer") from None
        expired: list = []
        failed: list = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
        snapshot = list(self.store.all().values())
        for record in snapshot:
            infohash = str(record.get("infohash") or "")
            if not infohash:
                continue
            if not (record.get("gofile_link") and record.get("gofile_folder_id")):
                continue
            created = _parse_utc_iso(record.get("gofile_created"))
            if created is None:
                continue  # not tracked: never expires
            if created > cutoff:
                continue  # still fresh
            folder_id = str(record.get("gofile_folder_id"))
            try:
                ok = bool(deleter(folder_id))
            except Exception:
                ok = False
            if not ok:
                failed.append(infohash)
                continue
            self.store.update(infohash,
                              gofile_link=None,
                              gofile_folder_id=None,
                              gofile_created=None,
                              archived=True,
                              gofile_removed_at=_utc_now_iso())
            expired.append(infohash)
        return expired, failed
