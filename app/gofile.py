"""GoFile API client (stdlib only).

Talks to the GoFile API over plain urllib. Auth is the account token sent only
in the "Authorization: Bearer" header — it is never put in a URL or a JSON
body, never printed, never logged.

Endpoints used (research-material/gofile-api-docs.md, the user's pasted docs):
- POST api.gofile.io/accounts                 mint a guest account -> data.token
                                              (only used when no token is configured;
                                              the caller persists the minted token)
- POST api.gofile.io/contents/createFolder    new folder; body parentFolderId +
                                              folderName; the response carries the
                                              folder id and its 8-char share code
- POST upload.gofile.io/uploadfile            ONE file per call, multipart/form-data,
                                              field "folderId" + the file part.
                                              NOTE: uploads go to a different host
                                              than the API, and there is no recursive
                                              folder upload — folders are built by
                                              creating one folder and uploading the
                                              files into it one by one.
- GET  api.gofile.io/contents/{id}            read a folder/file. Gated behind a
                                              dynamic website-token signature
                                              (X-Website-Token, R25): the SHA-256
                                              of "userAgent::language::accountToken::
                                              window::salt", window = unix time
                                              floored to 4 hours, salt scraped live
                                              from gofile.io/js/wt.obf.js (a
                                              hex-escaped 14-char literal that GoFile
                                              rotates; constants kept as fallback).
                                              With a valid token free accounts can
                                              read folder listings — get_content()
                                              wraps this, resolve_content_id() turns
                                              a /d/ short code into its folder UUID,
                                              and that is how Remove link deletes
                                              direct-transfer uploads (R25, proven
                                              live). Without the signature the gate
                                              answers error-notPremium, so
                                              get_folder_link() still returns None.
- PUT  api.gofile.io/contents/{id}/update     one attribute per call, body
                                              {"attribute": ..., "attributeValue": ...}.
                                              update_expiry() uses attribute "expiry"
                                              (unix seconds). Scheduler task 7 uses it.
- DELETE api.gofile.io/contents               body {"contentsId": "id1,id2"}.
                                              delete_contents() wraps it for the
                                              scheduler task.

Envelope: every response is {"status": "ok", "data": {...}} or
{"status": "error-..."}; the docs warn to branch on status, not the HTTP code
alone. Anything not "ok" raises GofileError; HTTP 401 maps to a hint to check
GOFILE_API_TOKEN in .env.

Rate limiting (R26): every request this module sends — API calls, uploads and
the wt.obf.js salt scrape alike — passes through one shared throttle
(_rate_wait) that keeps at least RATE_MIN_INTERVAL seconds between any two
GoFile HTTP requests from this process, and _request automatically backs off
(RATE_429_RETRY_DELAYS: 10 s then 20 s, honouring Retry-After) and retries
when GoFile answers 429 / error-rateLimit. If even that exhausts, the request
raises and the app layer (R26b) puts the job on a scheduled retry queue
(~30 minutes later) instead of dead-ending it. Streamed multipart uploads are
sent once only: their body cannot be replayed, so they raise on a 429 instead
of retrying.

This module is standalone on purpose: it imports nothing from sibling app
modules, so TESTS/ scripts can import it directly via sys.path.

No secrets are ever printed or logged by this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

__all__ = ["GofileError", "GofileClient"]

API_BASE = "https://api.gofile.io"
UPLOAD_URL = "https://upload.gofile.io/uploadfile"
DOWNLOAD_BASE = "https://gofile.io/d"

# ---- rate limiting (R26) ------------------------------------------------------
# GoFile does not publish its exact limits, but free-tier accounts that hammer
# the API get throttled (HTTP 429 / status error-rateLimit) and repeated abuse
# earns a temporary ban. The app's own volume is tiny, so the safe play is a
# strict minimum spacing between any two GoFile HTTP requests from this
# process, plus an automatic back-off-and-retry when GoFile says 429 anyway.
RATE_MIN_INTERVAL = 1.2        # seconds between any two GoFile HTTP requests
RATE_429_RETRY_DELAYS = (10.0, 20.0)   # backoff after an explicit 429: 10 s, then 20 s

_rate_lock = threading.Lock()
_rate_last = [0.0]             # monotonic timestamp of the last request sent
_rate_sleep = time.sleep       # patch points for tests
_rate_now = time.monotonic


def _rate_wait() -> None:
    """Block until RATE_MIN_INTERVAL has passed since the last GoFile request
    sent by this process, then record this slot. Module-level state on
    purpose: every GofileClient instance shares one outgoing pipe, so the
    spacing must be shared too. Called before every request, including the
    wt.obf.js salt scrape."""
    while True:
        with _rate_lock:
            gap = _rate_last[0] + RATE_MIN_INTERVAL - _rate_now()
            if gap <= 0:
                _rate_last[0] = _rate_now()
                return
        _rate_sleep(gap)

# ---- dynamic website token (R25) --------------------------------------------
# GoFile's GET /contents gate validates an X-Website-Token the official web
# client computes in JS: sha256("UA::language::accountToken::window::salt").
# The salt lives obfuscated (hex-escaped literals) in gofile.io/js/wt.obf.js
# and is rotated by GoFile, so it is scraped live and cached; the constants
# are past rotation values kept as a fallback when the scrape fails.
WT_JS_URL = "https://gofile.io/js/wt.obf.js"
WT_WINDOW_SECONDS = 14400  # 4 hours
WT_LANGUAGE = "en-US"
# MUST match the User-Agent header actually sent with the request, or the
# server's recomputed hash differs and the gate answers error-notPremium.
WT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TorboxDownloader/1.0"
WT_SALT_FALLBACKS = ("12af056dacea0b", "5d4f7g8sd45fsd", "9844d94d963d30")
WT_CACHE_MAX_AGE = 14400.0  # re-scrape after 4 hours (same cadence as rotation)

_WT_SALT_RE = re.compile(r"'((?:\\x[0-9a-fA-F]{2})+)'")


def _extract_wt_salt(script_text: str) -> Optional[str]:
    """Pull the 14-char hex salt out of the obfuscated wt.obf.js source.
    The literals are hex-escaped strings like '\\x31\\x32...'; the salt is the
    one that decodes to exactly 14 hex characters."""
    for raw in _WT_SALT_RE.findall(script_text):
        try:
            decoded = bytes.fromhex(raw.replace("\\x", "")).decode("utf-8", "ignore")
        except ValueError:
            continue
        if len(decoded) == 14 and all(c in "0123456789abcdef" for c in decoded):
            return decoded
    return None

ProgressCallback = Callable[[int, int], None]  # (bytes_sent_so_far, total_bytes)


class GofileError(Exception):
    """Raised when the GoFile API is unreachable, rejects the token, or answers with an error."""


def _friendly_status(status: str, http_code: Optional[int]) -> str:
    """Map an API error status / HTTP code to a human message. Never mentions the token value."""
    if http_code == 401 or status in ("error-token", "error-notPremium", "error-owner", "error-notOwner"):
        if status == "error-notPremium":
            return (
                "GoFile says this endpoint needs a Premium account "
                "(folder listings via GET contents are Premium-gated)."
            )
        return "GoFile rejected the token — check GOFILE_API_TOKEN in .env"
    if http_code == 429 or status == "error-rateLimit":
        return "GoFile rate limit hit — back off and retry later."
    if status == "error-limits":
        return "GoFile account quota exceeded (storage or 10,000-content cap on free accounts)."
    if status == "error-notFound":
        return "GoFile: unknown content id (or it belongs to another account)."
    if status == "error-protectedFolder":
        return "GoFile: the root folder (or recycle bin) cannot be changed that way."
    if status.startswith("error-field"):
        return f"GoFile rejected a parameter ({status})."
    return f"GoFile error {status or 'unknown'}" + (f" (HTTP {http_code})" if http_code else "")


class GofileClient:
    """Minimal GoFile client. Construct with token=None and call mint_guest_token()
    when no token is configured; the caller is responsible for persisting the result."""

    def __init__(self, token: Optional[str] = None, timeout: int = 120) -> None:
        self._token = (token or "").strip() or None
        self._timeout = timeout
        # Share codes seen on createFolder/upload responses, folder id -> 8-char code.
        self._folder_codes: dict[str, str] = {}
        # Resolved lazily: the token's account id and its root folder UUID.
        self._root_folder_id: Optional[str] = None
        # R25 website-token machinery: the scraped salt (cached on disk with a
        # timestamp sidecar so it survives restarts), and when it was fetched.
        self._wt_salt: Optional[str] = None
        self._wt_salt_time: float = 0.0
        self._wt_cache_path = Path(tempfile.gettempdir()) / "torboxdownloader-wt-cache.js"

    @property
    def token(self) -> str:
        """The GoFile API token in use ('' when running anonymously).

        Read by the direct Torbox->GoFile transfer (R24), which passes it
        per request to the Torbox integration; the value itself is never
        logged or shown."""
        return self._token or ""

    # ------------------------------------------------------------------ plumbing

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: Optional[dict] = None,
        data: Any = None,
        headers: Optional[dict] = None,
    ) -> dict:
        """One API call. Returns the parsed envelope dict (status/data). Raises GofileError."""
        req_headers = {"Accept": "application/json"}
        if self._token:
            # The token travels only in this header; it never appears in URLs or bodies.
            req_headers["Authorization"] = f"Bearer {self._token}"
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        if headers:
            req_headers.update(headers)

        # A streamed multipart body (a generator) cannot be replayed after a
        # partial send, so 429 retries are limited to plain-bytes requests.
        retryable = data is None or isinstance(data, (bytes, bytearray))
        attempt = 0
        while True:
            _rate_wait()   # R26: never send two GoFile requests closer than RATE_MIN_INTERVAL
            req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    raw = resp.read()
            except urllib.error.HTTPError as exc:
                raw = b""
                try:
                    raw = exc.read()
                except Exception:
                    pass
                status = ""
                try:
                    payload = json.loads(raw.decode("utf-8", "replace")) if raw else {}
                    status = str(payload.get("status", "")) if isinstance(payload, dict) else ""
                except Exception:
                    payload = {}
                # R26: GoFile said 429 (by HTTP code or by envelope status).
                # Back off — honouring Retry-After when present — and retry
                # while the schedule has attempts left, then give up loudly.
                if (exc.code == 429 or status == "error-rateLimit") and retryable \
                        and attempt < len(RATE_429_RETRY_DELAYS):
                    delay = RATE_429_RETRY_DELAYS[attempt]
                    attempt += 1
                    retry_after = ""
                    try:
                        retry_after = str(exc.headers.get("Retry-After") or "")
                    except Exception:
                        retry_after = ""
                    if retry_after:
                        try:
                            delay = max(delay, float(retry_after))
                        except ValueError:
                            pass
                    _rate_sleep(delay)
                    continue
                if not status:
                    raise GofileError(_friendly_status("", exc.code)) from None
                if isinstance(payload, dict) and payload.get("status") == "ok":
                    return payload
                raise GofileError(_friendly_status(status, exc.code)) from None
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                raise GofileError(f"Could not reach GoFile (network): {exc}") from None

            try:
                payload = json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                raise GofileError(f"GoFile answered with non-JSON (HTTP-quoted body, {len(raw)} bytes).") from None
            if not isinstance(payload, dict):
                raise GofileError("GoFile answered with an unexpected envelope shape.")
            status = str(payload.get("status", ""))
            if status != "ok":
                # The docs warn: branch on status, not the HTTP code alone.
                if status == "error-rateLimit" and retryable \
                        and attempt < len(RATE_429_RETRY_DELAYS):
                    _rate_sleep(RATE_429_RETRY_DELAYS[attempt])
                    attempt += 1
                    continue
                raise GofileError(_friendly_status(status, None))
            return payload

    @staticmethod
    def _data(payload: dict) -> dict:
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------ auth

    def mint_guest_token(self) -> str:
        """POST /accounts — mint a guest account and return its token.
        Does not require a configured token. The caller persists it (local state store)."""
        payload = self._request("POST", f"{API_BASE}/accounts")
        token = str(self._data(payload).get("token", "")).strip()
        if not token:
            raise GofileError("GoFile did not return a guest token (unexpected response shape).")
        return token

    def get_account_id(self) -> str:
        """GET /accounts/getid — resolve the account behind the configured token."""
        payload = self._request("GET", f"{API_BASE}/accounts/getid")
        account_id = str(self._data(payload).get("id", "")).strip()
        if not account_id:
            raise GofileError("GoFile did not return an account id for the token.")
        return account_id

    def get_root_folder(self) -> str:
        """The account's root folder UUID (accounts/getid, then accounts/{id}).
        Cached after the first call; create_folder uses it for parent "root"."""
        if self._root_folder_id:
            return self._root_folder_id
        account_id = self.get_account_id()
        payload = self._request("GET", f"{API_BASE}/accounts/{account_id}")
        root = str(self._data(payload).get("rootFolder", "")).strip()
        if not root:
            raise GofileError("GoFile did not return the account's root folder.")
        self._root_folder_id = root
        return root

    # ------------------------------------------------------------------ folders

    def create_folder(self, parent_folder_id: str = "root", name: str = "") -> str:
        """POST /contents/createFolder. Returns the new folder's id (UUID).
        parent_folder_id "root" (or empty) resolves to the account's real root
        folder UUID via get_root_folder() — GoFile rejects the literal "root".
        The docs' body parameter is "folderName" (name is optional there); the
        share code comes back on the response too and is kept for link lookups."""
        parent = (parent_folder_id or "root").strip().lower()
        if parent == "root":
            parent = self.get_root_folder()
        body: dict[str, Any] = {"parentFolderId": parent}
        if name:
            body["folderName"] = name
        data = self._data(self._request("POST", f"{API_BASE}/contents/createFolder", json_body=body))
        folder_id = str(data.get("id", "")).strip()
        if not folder_id:
            raise GofileError("GoFile created a folder but did not return its id.")
        code = str(data.get("code", "")).strip()
        if code:
            self._folder_codes[folder_id] = code
        return folder_id

    def get_folder_link(self, folder_id: str) -> Optional[str]:
        """The gofile.io/d/<code> share link for a folder, or None when it cannot be read.
        Reading folder contents is Premium-gated on free accounts (error-notPremium),
        so None is a normal outcome there; upload responses carry downloadPage /
        parentFolderCode instead, which upload_folder() prefers."""
        try:
            data = self._data(self._request("GET", f"{API_BASE}/contents/{folder_id}"))
        except GofileError:
            return self._link_from_code(self._folder_codes.get(folder_id, ""))
        return self.link_from_data(data) or self._link_from_code(self._folder_codes.get(folder_id, ""))

    @staticmethod
    def _link_from_code(code: str) -> Optional[str]:
        code = (code or "").strip()
        return f"{DOWNLOAD_BASE}/{code}" if code else None

    @staticmethod
    def link_from_data(data: dict) -> Optional[str]:
        """Pull a share link out of a contents/upload response, tolerating field variants."""
        for key in ("downloadPage", "publicLink"):
            link = str(data.get(key, "")).strip()
            if link.startswith("http"):
                return link
        for key in ("code", "parentFolderCode", "shareCode"):
            link = GofileClient._link_from_code(str(data.get(key, "")))
            if link:
                return link
        return None

    # ------------------------------------------------------------- website token (R25)

    def _ensure_wt_salt(self, force: bool = False) -> str:
        """The current signature salt: scraped from wt.obf.js, cached on disk,
        refreshed after WT_CACHE_MAX_AGE or when force=True. Falls back to the
        constants when the scrape fails. Never raises."""
        age = time.time() - self._wt_salt_time
        if not force and self._wt_salt and age < WT_CACHE_MAX_AGE:
            return self._wt_salt
        # stale disk cache from a previous run?
        try:
            if not force and self._wt_cache_path.exists():
                age = time.time() - self._wt_cache_path.stat().st_mtime
                if age < WT_CACHE_MAX_AGE:
                    salt = _extract_wt_salt(self._wt_cache_path.read_text(
                        encoding="utf-8", errors="replace"))
                    if salt:
                        self._wt_salt, self._wt_salt_time = salt, time.time()
                        return salt
        except OSError:
            pass
        try:
            _rate_wait()   # R26: the scrape counts against the same pipe
            req = urllib.request.Request(WT_JS_URL, headers={"User-Agent": WT_USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                script = resp.read().decode("utf-8", "replace")
            salt = _extract_wt_salt(script) if len(script) > 1000 else None
            if salt:
                self._wt_salt, self._wt_salt_time = salt, time.time()
                try:
                    self._wt_cache_path.write_text(script, encoding="utf-8")
                except OSError:
                    pass
                return salt
        except Exception:
            pass
        self._wt_salt_time = time.time()
        self._wt_salt = self._wt_salt or WT_SALT_FALLBACKS[0]
        return self._wt_salt

    def _website_token(self, account_token: str) -> str:
        """sha256('UA::language::accountToken::window::salt') — the value the
        web client puts in X-Website-Token. window = unix time // 14400."""
        window = str(int(time.time() // WT_WINDOW_SECONDS))
        salt = self._ensure_wt_salt()
        raw = f"{WT_USER_AGENT}::{WT_LANGUAGE}::{account_token}::{window}::{salt}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get_content(self, content_id: str, account_token: str = "",
                    page_size: int = 100) -> dict:
        """GET /contents/{id} WITH the dynamic X-Website-Token signature —
        readable on FREE accounts (proven live, R25; without the signature the
        gate answers error-notPremium). content_id may be a UUID or a /d/
        short code. account_token defaults to the configured token. Returns
        the response data dict (id, name, type, size, children, ...).
        On a signature rejection the salt is re-scraped once and the read
        retried once (GoFile rotates the salt; a window-boundary miss is
        covered the same way since the retry recomputes the window)."""
        token = (account_token or self._token or "").strip()
        if not token:
            raise GofileError("No GoFile token available for the content read.")
        headers = {
            "User-Agent": WT_USER_AGENT,
            "X-BL": WT_LANGUAGE,
            "Referer": "https://gofile.io/",
            "Origin": "https://gofile.io",
        }
        url = (f"{API_BASE}/contents/{content_id}"
               f"?page=1&pageSize={int(page_size)}&sortField=name&sortDirection=1")
        try:
            payload = self._request(
                "GET", url,
                headers={**headers,
                         "Authorization": f"Bearer {token}",  # override _request's default
                         "X-Website-Token": self._website_token(token)},
            )
        except GofileError:
            # Salt may have rotated (or a window boundary was crossed):
            # re-scrape and retry exactly once before giving up.
            payload = self._request(
                "GET", url,
                headers={**headers,
                         "Authorization": f"Bearer {token}",
                         "X-Website-Token": self._website_token(token)},
            )
        return self._data(payload)

    def resolve_content_id(self, code_or_link: str, account_token: str = "") -> str:
        """A /d/ short code (bare, a link, or a downloadPage URL) -> the content
        UUID behind it, via the signed free-tier read. Raises GofileError when
        the read fails (rate limit, gate change) — the caller decides what to
        tell the user."""
        code = (code_or_link or "").strip()
        if "/d/" in code:
            code = code.rsplit("/d/", 1)[1].split("?", 1)[0].strip("/")
        code = code.strip()
        if not code:
            raise GofileError("No GoFile content code to resolve.")
        data = self.get_content(code, account_token=account_token)
        content_id = str(data.get("id", "")).strip()
        if not content_id:
            raise GofileError("GoFile read the content but did not return its id.")
        return content_id

    def delete_link(self, folder_id: str, code: str = "",
                    account_token: str = "") -> tuple:
        """Delete a GoFile upload server-side. A known folder UUID deletes
        directly (works free, proven live). A bare /d/ code is resolved to its
        UUID first through the signed read. Returns (ok, detail) where detail
        is a human sentence for the log; the token value never appears in it."""
        folder_id = (folder_id or "").strip()
        if not folder_id:
            code = (code or "").strip()
            if not code:
                return False, "no folder id and no share code to delete"
            try:
                folder_id = self.resolve_content_id(code, account_token=account_token)
            except GofileError as exc:
                return False, (f"the share code could not be resolved to a "
                               f"deletable id ({exc})")
        return self.delete_contents([folder_id]), "its GoFile files were deleted"

    # ------------------------------------------------------------------ upload

    def upload_file(
        self,
        folder_id: str,
        file_path: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> dict:
        """POST upload.gofile.io/uploadfile — ONE file per call, into folder_id.
        Returns the parsed response data (id, name, size, downloadPage, ...).
        on_progress(sent, total) fires as bytes leave, if given."""
        if not self._token:
            raise GofileError("No GoFile token configured — set GOFILE_API_TOKEN or mint a guest token.")
        file_path = os.fspath(file_path)
        if not os.path.isfile(file_path):
            raise GofileError(f"Not a file: {os.path.basename(file_path)}")
        total_size = os.path.getsize(file_path)
        filename = os.path.basename(file_path)

        boundary = uuid.uuid4().hex
        # folderId field + the file part, exactly the parameters the docs list.
        # (No join wrapper: the adjacent bytes literals below concatenate into
        # one bytes object, and join() over a single bytes object would walk
        # its ints instead.)
        fields_head = (
            b"--" + boundary.encode("ascii") + b"\r\n"
            b'Content-Disposition: form-data; name="folderId"\r\n\r\n'
            + folder_id.encode("utf-8")
            + b"\r\n"
        )
        file_head = (
            b"--" + boundary.encode("ascii") + b"\r\n"
            b'Content-Disposition: form-data; name="file"; filename="'
            + filename.encode("utf-8").replace(b'"', b"")
            + b'"\r\n'
            b"Content-Type: application/octet-stream\r\n\r\n"
        )
        tail = (b"\r\n--" + boundary.encode("ascii") + b"--\r\n")
        content_length = len(fields_head) + len(file_head) + total_size + len(tail)

        with open(file_path, "rb") as fh:
            def body_iter():
                sent = 0
                yield fields_head
                yield file_head
                sent += len(fields_head) + len(file_head)
                if on_progress:
                    on_progress(sent, content_length)
                while True:
                    chunk = fh.read(256 * 1024)
                    if not chunk:
                        break
                    yield chunk
                    sent += len(chunk)
                    if on_progress:
                        on_progress(sent, content_length)
                yield tail
                if on_progress:
                    on_progress(content_length, content_length)

            payload = self._request(
                "POST",
                UPLOAD_URL,
                data=body_iter(),
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Content-Length": str(content_length),
                },
            )
        return self._data(payload)

    def upload_folder(
        self,
        folder_path: str,
        name: str = "",
        on_progress: Optional[ProgressCallback] = None,
    ) -> tuple[str, Optional[str]]:
        """Convenience: create a GoFile folder named `name` (default: the local
        folder's basename) under the account root, then upload every file in the
        local folder into it ONE BY ONE (no recursive upload exists). Returns
        (folder_id, link|None). The link prefers the upload responses' downloadPage;
        a folder GET (Premium-gated) is only the fallback.
        R22b: on_progress, when given, is called as on_progress(file_path, sent,
        total) — the file's full local path plus byte counts for THAT file."""
        folder_path = os.fspath(folder_path)
        if not os.path.isdir(folder_path):
            raise GofileError(f"Not a folder: {folder_path}")
        files = sorted(
            entry for entry in os.listdir(folder_path)
            if os.path.isfile(os.path.join(folder_path, entry))
        )
        folder_id = self.create_folder("root", name or os.path.basename(folder_path) or "upload")
        link: Optional[str] = self._link_from_code(self._folder_codes.get(folder_id, ""))
        for filename in files:
            # R22b: per-file progress now carries WHICH file it is (full
            # local path), so a caller can build folder-level progress
            # ("file 2 of 5, 45%") from the same callback.
            file_path = os.path.join(folder_path, filename)

            def _file_progress(sent: int, total: int, _p: str = file_path) -> None:
                if on_progress:
                    on_progress(_p, sent, total)

            data = self.upload_file(folder_id, file_path, on_progress=_file_progress)
            link = link or self.link_from_data(data)
        return folder_id, link

    # ------------------------------------------------------------------ update / delete (scheduler task 7)

    def update_expiry(self, content_id: str, expires_epoch: int) -> bool:
        """PUT /contents/{id}/update with attribute "expiry" (unix seconds, one
        attribute per call per the docs). For the scheduler task; not used yet."""
        try:
            self._request(
                "PUT",
                f"{API_BASE}/contents/{content_id}/update",
                json_body={"attribute": "expiry", "attributeValue": int(expires_epoch)},
            )
        except GofileError:
            return False
        return True

    def update_name(self, content_id: str, name: str) -> bool:
        """PUT /contents/{id}/update with attribute "name" (one attribute
        per call per the docs). R28: renames the folder Torbox created for
        a direct transfer (it names folders with its own short id) to the
        release name. Returns True when GoFile accepted the rename."""
        if not str(name or "").strip():
            return False
        try:
            self._request(
                "PUT",
                f"{API_BASE}/contents/{content_id}/update",
                json_body={"attribute": "name", "attributeValue": str(name).strip()},
            )
        except GofileError:
            return False
        return True

    def delete_contents(self, ids: list[str]) -> bool:
        """DELETE /contents with {"contentsId": "id1,id2"}. Folder deletes are
        recursive. For the scheduler task; not used yet."""
        if not ids:
            return True
        try:
            self._request("DELETE", f"{API_BASE}/contents", json_body={"contentsId": ",".join(ids)})
        except GofileError:
            return False
        return True
