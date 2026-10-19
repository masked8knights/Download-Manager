"""Torbox API client (stdlib only).

Talks to the Torbox API (base https://api.torbox.app/v1/api) over plain
urllib, with the API key sent only in the Authorization: Bearer header.
It is never put in a URL, printed, or logged.

Endpoints used:
- POST /torrents/createtorrent   add a magnet (JSON body), returns a torrent id
- GET  /torrents/mylist          torrent list incl. status and full file tree
- GET  /torrents/requestdl       CDN link for one file, or zip_link=true for
                                 the whole torrent as one zip (redirect=false
                                 keeps it a link, we never follow to the file)
- POST /torrents/controltorrent  delete (also resume/reannounce) by torrent id

Notes from research (RESEARCH.md / research-material/torbox-dmm.md):
- The response envelope is {"success": bool, "error": str|None, "data": ...};
  "success": false is raised as TorboxError with the "error" text.
- "data" shapes vary between endpoints and API versions, so every parser here
  is tolerant: a list where a dict is expected, ids under "torrent_id" or
  "id", files under "files" or "file_list", links as a bare string or wrapped.
- controltorrent: the docs route is /torrents/controltorrent (no dash), called
  as POST with operation=delete. (An early plan sketch wrote it as
  GET /torrents/control-torrent; the verified docs route is used instead.)
- seed is sent as a boolean, matching the brief; the docs also mention the
  integer forms 1=auto, 2=seed, 3=don't seed for this field.

This module is standalone on purpose: it imports nothing from sibling app
modules, so TESTS/ scripts can import it directly via sys.path.

No secrets are ever printed or logged by this module.
"""

from __future__ import annotations

import json
import socket
import uuid
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

__all__ = ["TorboxError", "TorboxClient", "TorrentInfo", "TorrentFile",
           "parse_timestamp"]

import calendar
import re

# Proven live (R17): mylist carries created_at as an ISO 8601 UTC string,
# e.g. "2026-10-16T11:21:55Z". Unix seconds are accepted too (older API
# versions and defensive parsing).
_ISO_TS = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})")


def parse_timestamp(raw: object) -> int:
    """Read a timestamp field as unix seconds (UTC), 0 when unknown.

    Accepts int/float unix seconds, digit strings, and ISO 8601 datetime
    strings ("2026-10-16T11:21:55Z", also with a space separator and a
    +00:00 offset). Anything else — bool, None, prose — is 0."""
    if isinstance(raw, bool) or raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw).strip()
    if not text:
        return 0
    if text.replace(".", "", 1).isdigit():
        try:
            return int(float(text))
        except (ValueError, OverflowError):
            return 0
    match = _ISO_TS.search(text)
    if match:
        try:
            return calendar.timegm(tuple(int(match.group(i))
                                         for i in range(1, 7)))
        except (ValueError, OverflowError):
            return 0
    return 0


class TorboxError(Exception):
    """Raised when the Torbox API is unreachable, rejects the key, or answers with an error."""


@dataclass
class TorrentFile:
    """One file inside a torrent, tolerant of missing fields."""

    file_id: int
    name: str
    size: int

    @classmethod
    def from_raw(cls, raw: dict) -> "TorrentFile":
        raw = raw if isinstance(raw, dict) else {}
        raw_id = raw.get("file_id")
        if raw_id is None:
            raw_id = raw.get("id")
        return cls(
            file_id=int(raw_id or 0),
            name=str(raw.get("name") or raw.get("short_name") or ""),
            size=int(raw.get("size") or 0),
        )


@dataclass
class TorrentInfo:
    """One torrent from mylist, tolerant of missing fields."""

    id: int
    name: str
    status: str
    hash: str
    size: int
    files: list = field(default_factory=list)
    created_at: int = 0   # unix seconds when the torrent entered the account; 0 unknown
    # R24: what Torbox reports while a torrent is still caching there for
    # the first time (progress percent, download speed in bytes/s). 0 when
    # unknown; the GoFile-link job reports these in the log so a slow
    # first-time caching is never silent.
    progress: float = 0.0
    download_speed: float = 0.0

    @classmethod
    def from_raw(cls, raw: dict) -> "TorrentInfo":
        raw = raw if isinstance(raw, dict) else {}
        raw_files = raw.get("files")
        if raw_files is None:
            raw_files = raw.get("file_list")
        if not isinstance(raw_files, list):
            raw_files = []
        raw_id = raw.get("id")
        if raw_id is None:
            raw_id = raw.get("torrent_id")
        raw_created = raw.get("created_at")
        created = parse_timestamp(raw_created)
        try:
            progress = float(raw.get("progress") or 0)
        except (TypeError, ValueError):
            progress = 0.0
        try:
            speed = float(raw.get("download_speed") or 0)
        except (TypeError, ValueError):
            speed = 0.0
        return cls(
            created_at=created,
            id=int(raw_id or 0),
            name=str(raw.get("name") or ""),
            status=str(raw.get("download_state") or raw.get("status") or ""),
            hash=str(raw.get("hash") or ""),
            size=int(raw.get("size") or 0),
            files=[TorrentFile.from_raw(f) for f in raw_files if isinstance(f, dict)],
            progress=max(0.0, min(progress, 100.0)),
            download_speed=max(0.0, speed),
        )


def _first_int(*candidates: Any) -> Optional[int]:
    """Return the first candidate that can be read as a positive int torrent id."""
    for value in candidates:
        if value is None:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        if isinstance(value, dict):
            # queued_id: the createtorrent success response carries the queue
            # id under "queued_id" (proven live: data = {hash, name, queued_id}).
            found = _first_int(value.get("torrent_id"), value.get("queued_id"), value.get("id"))
            if found is not None:
                return found
        if isinstance(value, list) and value:
            found = _first_int(value[0])
            if found is not None:
                return found
    return None


def _infohash(magnet: str) -> str:
    """Extract the btih infohash from a magnet URI (lowercase, '' if absent)."""
    raw = str(magnet)
    query = raw.split("?", 1)[1] if "?" in raw else raw
    for kv in query.split("&"):
        if kv.lower().startswith("xt=urn:btih:"):
            return kv.split(":", 2)[2].strip().lower()
    return ""


def _link_from_data(data: Any) -> Optional[str]:
    """Pull the CDN link out of a requestdl "data" value of any shape."""
    if isinstance(data, str) and data.strip():
        return data.strip()
    if isinstance(data, dict):
        for key in ("data", "link", "url", "download_url"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(data, list) and data:
        return _link_from_data(data[0])
    return None


class TorboxClient:
    """Client for the Torbox API. One instance, one API key, thread-safe enough:
    every request builds its own urllib Request, so calls from a worker thread
    and the UI thread do not share mutable state."""

    def __init__(self, api_key: str, base_url: str = "https://api.torbox.app/v1/api", timeout: float = 15.0):
        if not api_key or not api_key.strip():
            raise TorboxError("No Torbox API key given (TORBOX_API_KEY is empty)")
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    # ------------------------------------------------------------------ plumbing

    def _request(self, method: str, path: str, params: Optional[dict] = None,
                 json_body: Optional[dict] = None,
                 form_body: Optional[dict] = None,
                 file_field: Optional[tuple] = None) -> Any:
        """One API call. Returns the parsed JSON payload (envelope checked).

        json_body sends application/json; form_body sends
        application/x-www-form-urlencoded (createtorrent expects form fields —
        a JSON body there answers HTTP 400 'provide either a file or magnet
        link', proven live). file_field is a (filename, bytes) tuple for the
        multipart/form-data variant of createtorrent (R15: adding .torrent
        files by drag-and-drop); form fields can ride along as form_body."""
        url = f"{self._base_url}/{path.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            # Torbox's CDN 403s the default Python-urllib user agent; a
            # browser-like one gets through (proven live on the test machine).
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TorboxDownloader/1.0",
        }
        if file_field is not None:
            # Minimal multipart/form-data writer (stdlib only). Fields go in
            # first, then the file part named "file" (the API's field name).
            boundary = "----TorboxDownloaderR15" + uuid.uuid4().hex
            chunks = []
            for key, value in (form_body or {}).items():
                chunks.append(
                    f"--{boundary}\r\nContent-Disposition: form-data; "
                    f"name=\"{key}\"\r\n\r\n{value}\r\n".encode("utf-8"))
            filename, blob = file_field
            chunks.append(
                (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                 f"filename=\"{filename}\"\r\n"
                 "Content-Type: application/x-bittorrent\r\n\r\n").encode("utf-8"))
            chunks.append(blob)
            chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
            data = b"".join(chunks)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif form_body is not None:
            data = urllib.parse.urlencode(form_body).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise TorboxError(
                    f"Torbox rejected the API key (HTTP {exc.code}) — check TORBOX_API_KEY in .env"
                ) from None
            detail = ""
            try:
                body = json.loads(exc.read().decode("utf-8", "replace"))
                if isinstance(body, dict):
                    detail = str(body.get("detail") or body.get("error") or "")
            except Exception:
                pass
            suffix = f": {detail}" if detail else ""
            raise TorboxError(f"Torbox API error (HTTP {exc.code}){suffix}") from None
        except urllib.error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), (socket.timeout, TimeoutError)):
                raise TorboxError("Torbox API timed out — check internet connection") from None
            raise TorboxError("Torbox API not reachable — check internet connection") from None
        except (socket.timeout, TimeoutError):
            raise TorboxError("Torbox API timed out — check internet connection") from None
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            raise TorboxError("Torbox API returned a non-JSON answer") from None
        if isinstance(payload, dict) and payload.get("success") is False:
            error = payload.get("error") or payload.get("detail") or "unknown error"
            raise TorboxError(f"Torbox API error: {error}")
        return payload

    @staticmethod
    def _data(payload: Any) -> Any:
        if isinstance(payload, dict) and "data" in payload:
            return payload.get("data")
        return payload

    # ----------------------------------------------------------------- endpoints

    def create_torrent(self, magnet: str, as_queued: bool = False, seed: bool = False) -> int:
        """Add a magnet to the Torbox account. Returns the new torrent id.

        Sent as form fields (see _request): createtorrent rejects a JSON body.
        seed maps to the documented integers: 1=auto, 2=seed, 3=don't seed.
        as_queued defaults to False: True files the torrent into Torbox's
        release-on-demand queue (visible only via /queued/getqueued, never in
        mylist), which is not what the app wants — a download should start
        immediately or fail visibly."""
        if not magnet or not str(magnet).strip():
            raise TorboxError("Cannot create a torrent without a magnet link")
        body = {
            "magnet": str(magnet).strip(),
            "as_queued": "true" if as_queued else "false",
            "seed": "2" if seed else "3",
        }
        try:
            payload = self._request("POST", "torrents/createtorrent", form_body=body)
        except TorboxError as exc:
            # Torbox dedupes: re-adding a magnet it already has answers
            # DIFF_ISSUE "Download already queued." Track the existing torrent
            # instead of failing the download.
            if "already queued" in str(exc).lower():
                existing = self.find_by_hash(magnet)
                if existing is not None and existing.id:
                    return existing.id
            raise
        torrent_id = _first_int(self._data(payload))
        if torrent_id is None:
            raise TorboxError("Torbox did not return a torrent id for the new download")
        return torrent_id

    def create_torrent_file(self, path: str, as_queued: bool = False,
                            seed: bool = False) -> int:
        """Add a local .torrent file to the Torbox account (R15 drag-and-drop).

        Posts the file as multipart/form-data field "file" (the documented
        variant of createtorrent for file uploads); magnet, name, as_queued
        and seed are the documented optional siblings. Returns the new torrent
        id, same dedupe handling as create_torrent."""
        blob_path = Path(path)
        blob = blob_path.read_bytes()
        body = {
            "as_queued": "true" if as_queued else "false",
            "seed": "2" if seed else "3",
        }
        try:
            payload = self._request(
                "POST", "torrents/createtorrent", form_body=body,
                file_field=(blob_path.name, blob))
        except TorboxError as exc:
            if "already queued" in str(exc).lower():
                raise TorboxError(
                    "Torbox already has this torrent") from None
            raise
        torrent_id = _first_int(self._data(payload))
        if torrent_id is None:
            raise TorboxError("Torbox did not return a torrent id for the new download")
        return torrent_id

    def find_by_hash(self, magnet_or_hash: str) -> Optional[TorrentInfo]:
        """Find the account torrent whose infohash matches a magnet (or raw hash).
        Returns None when no row matches. Case-insensitive; mylist hashes and
        magnet infohashes may differ in case."""
        target = _infohash(magnet_or_hash) or str(magnet_or_hash).strip().lower()
        if not target:
            return None
        for torrent in self.mylist():
            if torrent.hash and torrent.hash.strip().lower() == target:
                return torrent
        return None

    def mylist(self) -> list:
        """The account's torrent list as TorrentInfo objects (bypasses the API's cache)."""
        payload = self._request("GET", "torrents/mylist", params={"bypass_cache": "true"})
        data = self._data(payload)
        if isinstance(data, dict):
            # Some API versions wrap the rows: {"data": {"data": [...]}} or {"torrents": [...]}
            rows = data.get("data")
            if not isinstance(rows, list):
                rows = data.get("torrents")
        else:
            rows = data
        if not isinstance(rows, list):
            rows = []
        return [TorrentInfo.from_raw(row) for row in rows if isinstance(row, dict)]

    def get_queued(self) -> list:
        """The account's release-on-demand queue (GET /queued/getqueued).

        Items land here when created with as_queued=true; they never appear
        in mylist until released. Returns raw dicts (id, name, magnet, type)."""
        payload = self._request("GET", "queued/getqueued", params={"bypass_cache": "true"})
        data = self._data(payload)
        if isinstance(data, dict):
            data = data.get("data") or data.get("queued") or []
        if not isinstance(data, list):
            data = []
        return [row for row in data if isinstance(row, dict)]

    def request_file_link(self, torrent_id: int, file_id: int) -> str:
        """CDN download link for one file of one torrent (redirect=false: a link, not the file).

        requestdl requires the API key as the "token" query param — header auth
        alone answers HTTP 422 "query token field required" (proven live)."""
        payload = self._request(
            "GET", "torrents/requestdl",
            params={"token": self._api_key, "torrent_id": torrent_id,
                    "file_id": file_id, "redirect": "false"},
        )
        link = _link_from_data(self._data(payload))
        if not link:
            raise TorboxError("Torbox did not return a download link for the requested file")
        return link

    def request_zip_link(self, torrent_id: int) -> str:
        """CDN link for the whole torrent as one zip (zip_link=true takes precedence over file_id)."""
        payload = self._request(
            "GET", "torrents/requestdl",
            params={"token": self._api_key, "torrent_id": torrent_id,
                    "zip_link": "true", "redirect": "false"},
        )
        link = _link_from_data(self._data(payload))
        if not link:
            raise TorboxError("Torbox did not return a zip link for the requested torrent")
        return link

    def delete_torrent(self, torrent_id: int) -> bool:
        """Delete a torrent from the account (POST /torrents/controltorrent, operation=delete).

        The fields go in a JSON body: query params answer 422 "body field
        required" and a urlencoded body answers 422 "input should be a valid
        dictionary"; the JSON body deletes cleanly (proven live)."""
        self._request(
            "POST", "torrents/controltorrent",
            json_body={"torrent_id": torrent_id, "operation": "delete"},
        )
        return True

    # ------------------------------------------------- Torbox -> GoFile transfer (R24)
    # Live-verified 2026-10-17: POST /integration/gofile with a JSON body whose
    # torrent field is named "id" ("torrent_id" answers 422 "Field required").
    # The whole-torrent form is {"id": <tid>, "zip": true, "gofile_token":
    # <token>} — the token is passed PER REQUEST, so the Torbox dashboard never
    # needs it stored. The integration offers NO parent-folder parameter: every
    # candidate folder field name is silently ignored (probed 2026-10-17).
    # Job statuses observed live: "preparing" -> "uploading" -> "completed" /
    # "failed"; progress is a 0..1 float; the finished job carries download_url.

    def queue_gofile_job(self, torrent_id: int, gofile_token: str,
                         zip_all: bool = True) -> int:
        """Queue a Torbox->GoFile cloud-transfer job. Returns the job id.

        gofile_token is the caller's own GoFile API token (GOFILE_API_TOKEN
        from .env), never anything stored on the Torbox dashboard. zip_all
        (default) asks for the whole torrent as one zip — the user accepted
        zip output for sharing."""
        if not str(gofile_token or "").strip():
            raise TorboxError("No GoFile token available for the Torbox transfer")
        body = {"id": int(torrent_id), "zip": bool(zip_all),
                "gofile_token": str(gofile_token)}
        payload = self._request("POST", "integration/gofile", json_body=body)
        data = self._data(payload)
        job_id = data
        if isinstance(data, dict):
            job_id = data.get("job_id")
            if job_id is None:
                job_id = data.get("id")
        try:
            return int(job_id)
        except (TypeError, ValueError):
            raise TorboxError(
                "Torbox did not return a job id for the GoFile transfer") from None

    def get_integration_job(self, job_id: int) -> dict:
        """One integration job as a raw dict (id, hash, status, progress,
        download_url, file_name, ...). Missing/garbled answers become {}."""
        payload = self._request("GET", f"integration/job/{int(job_id)}")
        data = self._data(payload)
        return data if isinstance(data, dict) else {}

    def get_integration_jobs(self, infohash: str = "") -> list:
        """Integration jobs as raw dicts, optionally narrowed to one infohash."""
        params = {"hash": infohash} if infohash else None
        payload = self._request("GET", "integration/jobs", params=params)
        data = self._data(payload)
        if isinstance(data, dict):
            data = data.get("data") or data.get("jobs") or []
        if not isinstance(data, list):
            data = []
        return [row for row in data if isinstance(row, dict)]

    def cancel_integration_job(self, job_id: int) -> bool:
        """Delete one integration job row (DELETE /integration/job/{id}).

        This cancels only the transfer JOB the app itself queued (e.g. when
        the user presses Stop); the GoFile content already uploaded is not
        touched by this call, and no torrent on the account is affected."""
        self._request("DELETE", f"integration/job/{int(job_id)}")
        return True
