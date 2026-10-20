"""qBittorrent WebUI search client (stdlib only).

Drives qBittorrent's WebUI API v2 search endpoints over plain HTTP:
search/start, search/status, search/results, search/stop, search/delete,
search/plugins, plus app/version as a connectivity probe.

The target is the local WebUI (default http://127.0.0.1:8080, usually with
LocalhostAuth=false). R52: /auth/login is performed ONCE for every client,
even with empty credentials — qBittorrent 5.x scopes search jobs to the
WebUI session cookie, and with the localhost bypass on an empty-credential
login still issues the SID cookie. Without it, search/start returns a job
id that search/status and search/results can never see again (proven live
against v5.2.3 on the machine where search "worked" only from the GUI).
The session cookie is kept in a cookie jar shared by all requests.

This module is standalone on purpose: it imports nothing from sibling app
modules, so the TESTS/ scripts can import it directly via sys.path.

No secrets are ever printed or logged by this module.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.cookiejar import CookieJar

__all__ = ["QBitError", "QBitSearchClient", "SearchItem", "human_size"]

DEFAULT_TIMEOUT = 5.0
RESULTS_PAGE_SIZE = 100


class QBitError(Exception):
    """Raised when the qBittorrent WebUI is unreachable or answers with an error."""


@dataclass
class SearchItem:
    """One search result row from qBittorrent's search plugins."""

    name: str
    file_url: str      # magnet: URI or a .torrent URL, ready for Torbox
    size_bytes: int
    seeds: int
    leechers: int
    engine: str        # search plugin name, e.g. "piratebay"
    site: str          # siteUrl the result came from
    category: str
    pub_date: int = 0  # upload date, unix seconds; 0 unknown (API sends -1)


def human_size(num_bytes: float) -> str:
    """Format a byte count as a short human-readable string (e.g. '1.4 GiB')."""
    size = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(size) < 1024.0:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PiB"


def _to_item(row: dict) -> SearchItem:
    """Map one raw API result row to a SearchItem, tolerating missing fields."""
    raw_pub = row.get("pubDate")
    if not isinstance(raw_pub, (int, float)) or isinstance(raw_pub, bool):
        raw_pub = 0
    if raw_pub is None or int(raw_pub) < 0:   # -1 = the engine knows no date
        raw_pub = 0
    return SearchItem(
        name=str(row.get("fileName", "")),
        file_url=str(row.get("fileUrl", "")),
        size_bytes=int(row.get("fileSize") or 0),
        seeds=int(row.get("nbSeeders") or 0),
        leechers=int(row.get("nbLeechers") or 0),
        engine=str(row.get("engineName", "")),
        site=str(row.get("siteUrl", "")),
        category=str(row.get("category", "")),
        pub_date=int(raw_pub),
    )


class QBitSearchClient:
    """Client for qBittorrent's WebUI API v2 search endpoints.

    Thread-safety: one shared opener (with its cookie jar) is guarded by a
    lock, so calls made from a UI worker thread are safe. Every HTTP call
    carries the timeout given at construction.
    """

    def __init__(self, url: str = "http://127.0.0.1", port: int = 8080,
                 username: str = "", password: str = "",
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        # R45: an empty url (blank QBIT_URL= in .env) would build ":8080"
        # and every request would fail with "unknown url type"; fall back
        # to the same default Config uses. Strip first so whitespace-only
        # values count as empty too.
        self.url = (url or "").strip().rstrip("/") or "http://127.0.0.1"
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        # Append the port only when the URL does not already carry one.
        if port and ":" not in self.url.split("://", 1)[-1]:
            self.url = f"{self.url}:{port}"
        self._lock = threading.Lock()
        self._cookie_jar = CookieJar()
        # ProxyHandler({}) keeps localhost traffic away from any HTTP proxy
        # set in the environment.
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self._cookie_jar),
        )
        self._logged_in = False

    # ---- low level -------------------------------------------------------

    def _unreachable_error(self) -> QBitError:
        return QBitError(
            f"qBittorrent WebUI not reachable at {self.url} "
            f"— is qBittorrent running with WebUI enabled?"
        )

    def _login_locked(self) -> None:
        """POST /auth/login once; stores the SID cookie in the shared jar.

        R52: runs for every client, empty credentials included. With the
        localhost bypass on, qBittorrent may answer anything for this call
        (an empty-credential login is not a credential check), so the body
        is only enforced when credentials were actually supplied; the SID
        cookie is what matters and is picked up by the shared cookie jar.
        When the bypass is OFF and credentials are empty, no SID is issued
        and every later request fails with HTTP 401 — the error surfaces
        then, which is the honest answer. Credentials are never included
        in any error message.
        """
        form = urllib.parse.urlencode(
            {"username": self.username, "password": self.password}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.url}/api/v2/auth/login", data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            body = self._opener.open(req, timeout=self.timeout).read()
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403) and not (self.username or self.password):
                # Bypass off and no credentials: the later requests will
                # carry the same failure, so raise the unreachable/needs-
                # credentials message rather than a login one.
                raise QBitError(
                    f"qBittorrent WebUI requires credentials at {self.url} "
                    "(set QBIT_USERNAME/QBIT_PASSWORD, or enable the "
                    "localhost bypass in qBittorrent's WebUI settings)"
                ) from exc
            raise QBitError(f"qBittorrent login failed: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise self._unreachable_error() from exc
        except TimeoutError as exc:
            raise QBitError(f"qBittorrent WebUI timed out after {self.timeout}s") from exc
        if body.decode("utf-8", errors="replace").strip() != "Ok." \
                and (self.username or self.password):
            raise QBitError("qBittorrent login failed: wrong username or password")
        self._logged_in = True

    def _request(self, method: str, path: str, form: dict[str, str] | None = None,
                 query: dict[str, object] | None = None) -> str:
        """Perform one HTTP call against the WebUI; returns the body as text."""
        target = f"{self.url}{path}"
        if query:
            target += "?" + urllib.parse.urlencode(query)
        data = None
        headers: dict[str, str] = {}
        if form is not None:
            data = urllib.parse.urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(target, data=data, headers=headers, method=method)
        with self._lock:
            if not self._logged_in:
                # R52: log in even with empty credentials. With the
                # localhost bypass on, qBittorrent still issues the SID
                # cookie on this call, and 5.x scopes search jobs to that
                # cookie — without it the job id from search/start is
                # orphaned (status returns [] and results says Not Found).
                self._login_locked()
            try:
                with self._opener.open(req, timeout=self.timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                raise QBitError(
                    f"qBittorrent WebUI answered HTTP {exc.code} for {path}: {exc.reason}"
                ) from exc
            except urllib.error.URLError as exc:
                raise self._unreachable_error() from exc
            except TimeoutError as exc:
                raise QBitError(
                    f"qBittorrent WebUI timed out after {self.timeout}s at {self.url}"
                ) from exc

    def _get_json(self, path: str, query: dict[str, object] | None = None) -> object:
        try:
            return json.loads(self._request("GET", path, query=query))
        except json.JSONDecodeError as exc:
            raise QBitError(f"qBittorrent sent a non-JSON answer for {path}") from exc

    # ---- public API ------------------------------------------------------

    def version(self) -> str:
        """qBittorrent version string (e.g. 'v5.2.4'); doubles as a connectivity probe."""
        return self._request("GET", "/api/v2/app/version").strip().strip('"')

    def plugins(self) -> list[dict]:
        """Installed search plugins (useful for a UI dropdown later)."""
        data = self._get_json("/api/v2/search/plugins")
        return data if isinstance(data, list) else []

    def search(self, pattern: str, category: str = "all",
               plugins: str = "all") -> int:
        """Start a search in one category; returns the job id.

        category is qBittorrent's API value ("all", "anime", "books", "games",
        "movies", "music", "pictures", "software", "tv"); the UI maps its
        display names to these before calling. plugins is "all", "enabled",
        or a | separated list of plugin names (R19: the "Search in:" filter,
        verified live against the WebUI API)."""
        body = self._post_form(
            "/api/v2/search/start",
            {"pattern": pattern, "plugins": plugins, "category": category},
        )
        try:
            return int(json.loads(body)["id"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise QBitError(f"qBittorrent did not return a search job id for {pattern!r}") from exc

    def update_plugins(self) -> None:
        """R19: qBittorrent's own plugin-update pass (the same thing the
        GUI's "Check for Updates" button does): each plugin is re-fetched
        from its source and only replaced when a newer version exists."""
        self._post_form("/api/v2/search/updatePlugins", {})

    def poll_status(self, job_id: int) -> dict:
        """Current state of a search job: {'status': 'running'|'stopped', 'total': n, ...}.

        qBittorrent answers with an object normally, but some 5.x builds wrap
        the job in a one-element list even when id is given; accept both.
        """
        data = self._get_json("/api/v2/search/status", query={"id": job_id})
        if isinstance(data, list):
            data = data[0] if data else {}
        return data if isinstance(data, dict) else {}

    def results(self, job_id: int, limit: int = 0, offset: int = 0) -> list[SearchItem]:
        """One page of results for a job; limit=0 asks the API for everything."""
        data = self._get_json(
            "/api/v2/search/results",
            query={"id": job_id, "limit": limit, "offset": offset},
        )
        rows = data.get("results", []) if isinstance(data, dict) else []
        return [_to_item(row) for row in rows if isinstance(row, dict)]

    def stop(self, job_id: int) -> None:
        """Stop a running search job."""
        self._post_form("/api/v2/search/stop", {"id": str(job_id)})

    def delete(self, job_id: int) -> None:
        """Delete a search job and its cached results on the qBittorrent side."""
        self._post_form("/api/v2/search/delete", {"id": str(job_id)})

    # ---- R49: application-level controls used by qbitstart ---------------

    def set_app_preferences(self, prefs: dict) -> None:
        """Merge a partial preferences dict into qBittorrent's settings.

        The same endpoint the GUI's settings dialog saves through; only the
        given keys change, everything else is left as the user set it.
        """
        self._post_form("/api/v2/app/setPreferences",
                        {"json": json.dumps(prefs)})

    def shutdown_app(self) -> None:
        """Ask qBittorrent to quit cleanly through its own shutdown API."""
        self._post_form("/api/v2/app/shutdown", {})

    def _post_form(self, path: str, form: dict[str, str]) -> str:
        return self._request("POST", path, form=form)

    def search_blocking(self, pattern: str, timeout: float = 30.0,
                        poll_interval: float = 0.5) -> list[SearchItem]:
        """Start a search, poll until it finishes, gather every page, clean up the job.

        Some engines never report "stopped" (dead sites keep the job running),
        so if the deadline passes with results already accumulated they are
        returned anyway rather than raising. Raises QBitError only when the
        deadline passes and there is nothing to show.

        Convenience for scripts and tests; the UI should use search() plus
        poll_status()/results() so it never blocks the interface.
        """
        job_id = self.search(pattern)
        try:
            deadline = time.monotonic() + timeout
            stopped = False
            while True:
                if self.poll_status(job_id).get("status") == "stopped":
                    stopped = True
                    break
                if time.monotonic() >= deadline:
                    break
                time.sleep(poll_interval)

            items: list[SearchItem] = []
            offset = 0
            while True:
                page = self.results(job_id, limit=RESULTS_PAGE_SIZE, offset=offset)
                items.extend(page)
                if len(page) < RESULTS_PAGE_SIZE:
                    break
                offset += len(page)
            if not items and not stopped:
                raise QBitError(
                    f"search for {pattern!r} did not finish within {timeout}s "
                    "and no results had arrived yet"
                )
            return items
        finally:
            try:
                self.delete(job_id)
            except QBitError:
                pass  # cleanup is best-effort; never mask the real error
