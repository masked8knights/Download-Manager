"""Torbox Downloader: a small self-contained desktop app (tkinter, stdlib only).

Run with:  python -m app   (from the TorboxDownloader folder)

Task 6 + round R10. One window, top to bottom: header, SEARCH section
(query, category dropdown, Search), RESULTS section (Name/Size/Seeds/
Engine; the Name/Size/Seeds headings sort), DOWNLOADS section (R14 split
per the user: Download / Make GoFile link ABOVE the downloads table,
Download & Unpack / Remove from PC BELOW it; the table is Name/Status/
Files/Link with the Show archived toggle), the selected download's
clickable GoFile link, the LOG section (R13: clearable via a Clear log
button), and the status line with the drawn PNG cog and folder icons
(R14: real icons instead of Unicode glyphs) and the status text.

Round R10 behavior: the window and taskbar share the app icon (iconbitmap
on the bundled .ico, iconphoto as fallback). A qBittorrent-style category
filter scopes searches. Plugin error rows (negative size, "Jackett:" or
"][Error]:" names) are hidden and counted. Pressing Search while a search
runs replaces it (cancel event + best-effort stop/delete on the old job
from a tiny daemon thread) instead of being refused. "Download & Unpack"
releases a held/failed record to the PC, waits for completion (up to 30
min), then unpacks to the default preset; for an already-complete record
it runs just the unpack part. R9 hold mode still applies: adding a
download only puts the torrent on Torbox; "Remove from PC" deletes the
selected download's local files and list entry; the Torbox account is
never touched from local list management. Search results stream in row by
row while the engines run, like qBittorrent's own search UI.

Round R11: on Windows the app declares an AppUserModelID and keeps a
matching Start Menu shortcut (icon included) registered, so the taskbar
button resolves to the app icon instead of the Python logo; the shortcut
re-registers itself at launch if missing. A Clear button next to Search
cancels a running search and empties the results and the query box, and a
"⚙" button left of the status line opens
an in-app Settings popup (R11 amendment) for editing the .env values: the
file itself is never opened in an editor, values are shown masked and are
never logged, and saving rewrites .env atomically (comments and unknown
keys preserved); a restart applies the new values. R11b: the layout
weight moved onto the content column so the window no longer leaves dead
space on its right side.

Threading convention (design spec): ALL network and disk work runs in daemon
worker threads; the UI thread only reads the event queue in _drain() via
.after(100) and updates widgets. No UI callback ever blocks on the network.

Round R19: the SEARCH row gains a second filter, "Search in:" (All plugins /
each installed plugin name), fed live from qBittorrent's plugin list, and
search plugins are updated automatically once at startup plus on demand from
Settings via qBittorrent's own /search/updatePlugins pass. Round R20: the
dropdown lists only ENABLED plugins (disabled ones are hidden and the
"only enabled/only disabled" choices are gone), and the Trending button
fills the search box with the wildcard '*' — verified live to return ~100
real all-time results with seed counts, where an empty pattern gives
nothing but plugin errors and a year only surfaces one year. Round R20a:
that all-time '*' query gets its own 2-minute deadline instead of the
30-second one — the user saw a trending search end mid-work at 30 seconds.
Round R21: double-clicking a row in TORBOX FILES makes a GoFile link for
that account torrent: it is adopted into the download list (engine.adopt,
never re-added to the account), fetched to the PC when needed, then
uploaded through the ordinary Make-GoFile-link path. Round R22 replaced
that with SELECT-THEN-PRESS: clicking a row in ANY table (results,
downloads, torbox) just remembers the row; the "Make GoFile link" and
"Download" buttons then act on that row. Make GoFile link on a search
RESULT runs the full chain (add to Torbox, wait for it to finish there,
fetch to the PC, upload); on a TORBOX row it adopts/fetches/uploads; on a
DOWNLOADS row it uploads what is already here. Download fetches a search
result to the account, or fetches a torbox/downloads row to this PC
without uploading. The links table at the bottom lists every GoFile link
(including direct drops) and opens one on DOUBLE-click. The old "Show
archived" toggle is gone (R22b): archived records simply stay in the
downloads table with an "archived <date>" status, and the links table now
shows them too with state "archived <date>" — selecting an archived row
there and pressing Make GoFile link makes a FRESH link from the files
still on disk (a re-upload; direct drops are re-linked from their
original file). A link job also
waits for Torbox to list a cached torrent's files before fetching, so the
old "has no file list yet" error is gone. Trending keeps the top 1000
rows by seed count. R22c adds the top activity bar (a mini Steam-style
download menu): one slim bar + text in the header showing live percent,
download/upload speeds, and what is moving — downloads read byte progress
from the store plus the on-disk .part-<file_id> files, uploads register a
per-job accumulator fed by gofile's on_progress callbacks. Search still
needs qBittorrent installed and running with its WebUI enabled: the app has
no search engines of its own, it drives qBittorrent's plugins through the
WebUI API.

Round R26b: when GoFile still rate-limits a job after the quick in-request
retries (10 s then 20 s, R26), the job is parked on a scheduled retry queue
(~30 minutes later, up to 3 scheduled retries) instead of failing for good;
a parked job wears a "queued for GoFile (retry HH:MM)" state in the
downloads and links tables so the wait is visible. The DOWNLOADS Where
column is now a hyperlink in all three of its states: "On PC" opens the
local folder, "Torbox only" opens the Torbox dashboard (never the raw CDN
link, which carries the API key and expires), and "GoFile only" opens the
share link.

Round R28 (per the user, 2026-10-17): a record whose only remaining piece
is its GoFile link now lives in the GOFILE links table alone (user: "just
move this to the link table") — DOWNLOADS shows active work, queued jobs,
anything with local files, and Torbox-only records; a Download press on a
links row fetches the record back to the PC (direct drops still refuse,
there is no torrent behind them). Direct Torbox->GoFile transfers rename
the folder Torbox created (it names folders with its own short id) to the
release name, best-effort, so GOFILE STORAGE reads sensibly. Layout pass:
the two bottom titles sit on one line (the dashboard link got its own row
above Remove link, mirroring the crumbs row), every column of every table
is centered, and the button sizes are consistent (Search/Clear/Trending
alike; File/Folder alike and half of Add).

Round R29: the Name column of every table is left-aligned again (user:
"name should always be on the left"); only the narrow columns stay
centered. And folders created by direct transfers BEFORE R28 keep the
short ids Torbox gave them — the rename only runs at transfer time — so a
one-shot repair pass runs a few seconds after startup: every record that
remembers its GoFile folder id gets one best-effort PUT rename to its
release name, throttled by the usual limiter, with a log line saying how
many were fixed.

Round R23 fixes the "progress bar shows nothing, bottom says Linking" bug:
Torbox returns file id 0 for a cached SINGLE-FILE torrent, and the old code
filtered id 0 out everywhere, so the file list stayed empty, the bar had no
bytes to measure, and the release went through the whole-torrent zip route.
Id 0 is now accepted as a normal file id (adopt, refresh, release, the
file-list wait, and _per_file_safe, which routes to the zip path only when
several ids collide or the list is empty). R23 also adds the Stop button on
the activity bar: one press ends every in-flight job — Torbox→PC downloads
(cancel() flips the record back to "held" and aborts the .part stream) and
PC→GoFile uploads and relinks (a cancel-aware on_progress raises
_UploadStopped, which aborts gofile's streamed body cleanly). Closing the
window stops everything the same way. A stopped download resumes only by
pressing Download again: the engine refuses to release while a stop is
still registered, so a background link job can never silently undo a stop.

Round R24 (per the user, 2026-10-17): "Make GoFile link" runs a DIRECT
Torbox->GoFile cloud transfer first (POST /integration/gofile, whole torrent
as one zip, the GOFILE_API_TOKEN from .env — never the Torbox dashboard
token): Torbox uploads to GoFile itself and nothing is fetched to the PC.
When the direct transfer fails the app falls back to the old fetch-to-PC +
upload chain, and when that fallback had to fetch the torrent to the PC
itself, the local copy is deleted after the upload succeeds — a torrent the
user pre-downloaded (already complete with a folder when the link was
pressed) is kept. The app NEVER deletes anything on Torbox or GoFile on its
own any more: the 30-day pass is now a REMINDER naming links older than 30
days, and the Delete button in the GOFILE section deletes the
GoFile content when the free tier allows (only links the app uploaded
itself carry a deletable folder UUID; a direct-transfer link is a bare /d/
code that free accounts cannot resolve to a UUID, so those rows are
archived with a note to remove them at gofile.io). The downloads table's
Link column becomes "Where" ("On PC" / "GoFile only" / "Torbox only") and
the stray link label under it is gone: links live only in the GOFILE
table at the bottom. "Remove from PC" on a record that still has a live
GoFile link keeps the record and the link and deletes only the local copy.
R24 additions (per the user, same day): the Stop button is LOCAL-ONLY — it
ends PC-side downloads, link jobs and uploads, and never deletes or cancels
anything on Torbox; a torrent still caching there keeps caching. When a
link job finds the torrent not cached yet, the app stays quiet for about a
minute, then reports what Torbox is doing (caching percent and download
speed from mylist) so a first-time caching is never silent — the cloud
transfer job itself reports each stage too ("preparing", "uploading N%").
Pressing Stop during a cloud transfer cancels ONLY the transfer job the
app itself queued (reported in the log); no torrent and no GoFile content
is touched by Stop. The TORBOX FILES section gains a "Torbox dashboard ↗"
link to https://torbox.app/dashboard, matching the GoFile dashboard link.

GoFile is the ONLY sharing mechanism in this app. The gofile.io share link is
stored in the download record and shown in the UI. Torbox CDN links
(requestdl output) carry the account API key as a query param and expire in
about 3 hours; the engine uses them internally for downloads only, and they
must never reach a log line or the UI. No secret value is ever printed or
logged anywhere in this module.
"""

import json
import queue
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import uuid
import webbrowser
from tkinter import filedialog, messagebox, font as tkfont
from urllib.parse import unquote_plus, urlparse
from pathlib import Path
from tkinter import ttk

# Allow both "python -m app" and "python app/__main__.py" to work.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import Config
from engine import DOWNLOAD_USER_AGENT, DownloadEngine, _infohash, _parse_utc_iso, _utc_now_iso
from gamever import game_version, version_tags
from gofile import GofileClient, GofileError
from presets import Presets
from qbitsearch import QBitError, QBitSearchClient, SearchItem, human_size
from theme import Theme, apply_theme
from icons import cog_photo, folder_photo
from icon import make_photo_image
from torbox import TorboxError
import handoff
import wizard
from translate_en import TitleTranslations, warm_up

# R15: drag-and-drop needs tkinterdnd2 (tkinter itself has no file-drop
# support). It is the app's ONLY third-party runtime dependency and is
# optional: without it the app runs exactly as before, the downloads
# section just ignores drops and a one-line hint goes to the log.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
    _TkBase = TkinterDnD.Tk
except Exception:
    DND_AVAILABLE = False
    _TkBase = tk.Tk

from apppaths import BUNDLE_ROOT, USER_ROOT

# R38: writable root (.env-adjacent state, downloads, data cache). From
# source this is the project root; frozen it is the exe's folder.
ROOT = USER_ROOT

LOG_MAX_LINES = 500

class _UploadJob:
    """R22c: per-upload progress accumulator fed by gofile's on_progress
    callbacks (which fire on the upload worker thread).

    The top activity bar reads two numbers from it: bytes_now (bytes sent
    so far across every file seen) and bytes_all (the folder's total size,
    computed by the worker up front, since per-file totals are only known
    once each file starts). Called from one thread per job; the UI ticker
    reads it under the app's _upload_jobs_lock.
    """

    def __init__(self, key: str, name: str, bytes_all: int = 0) -> None:
        self.key = key
        self.name = name
        self.bytes_all = int(bytes_all)
        self.files: dict[str, list[int]] = {}   # path -> [sent, total]

    def callback(self, path: str, sent: int, total: int) -> None:
        entry = self.files.get(path)
        if entry is None:
            entry = [0, int(total or 0)]
            self.files[path] = entry
        entry[0] = int(sent or 0)
        if total:
            entry[1] = max(entry[1], int(total))

    def bytes_now(self) -> int:
        return sum(max(e[0], 0) for e in self.files.values())


class _UploadStopped(RuntimeError):
    """R23: raised from a cancel-aware on_progress callback so gofile's
    body_iter aborts the in-flight upload cleanly the moment the Stop
    button is pressed. Caught by the upload workers, never shown as an
    error."""


def _fmt_speed(bytes_per_second: float) -> str:
    """'8.4 MB/s' style; sub-kilobyte speeds read as '0 B/s'."""
    bps = max(float(bytes_per_second or 0.0), 0.0)
    if bps < 1024:
        return "0 B/s"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.0f} KB/s"
    if bps < 1024 * 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f} MB/s"
    return f"{bps / (1024 * 1024 * 1024):.2f} GB/s"


def _fmt_eta(remaining_bytes: float, bytes_per_second: float) -> str:
    """Human ETA for the top bar ('ETA 4m 05s'). Empty when nothing useful
    can be estimated (nothing left, or the speed is too low to trust)."""
    if remaining_bytes <= 0 or bytes_per_second < 1024:
        return ""
    secs = int(remaining_bytes / bytes_per_second)
    if secs >= 3600:
        return f"ETA {secs // 3600}h {secs % 3600 // 60:02d}m"
    if secs >= 60:
        return f"ETA {secs // 60}m {secs % 60:02d}s"
    return f"ETA {secs}s"

SEARCH_POLL_INTERVAL = 1.0   # seconds between streaming search polls
SEARCH_DEADLINE = 30.0       # same semantics as qbitsearch.search_blocking
TRENDING_SEARCH_DEADLINE = 120.0  # R20a: the all-time '*' query gathers far
                             # more than a normal query (hundreds of rows,
                             # slow engines), so trending gets 2 minutes; at
                             # 30s the user saw the search end mid-work.
TRENDING_TOP_N = 1000        # R22a: a trending ('*') search keeps only the
                             # top 1000 rows by seed count (user pick).
RESULTS_PAGE_SIZE = 100      # qbitsearch page size
POLL_INTERVAL = 3.0          # seconds between engine.refresh() passes
POLL_FAILURE_ECHO = 60.0     # log repeated poll failures at most once a minute
DOWNLOAD_POLL_INTERVAL = 2.0     # store checks while "Download & Unpack" waits
DOWNLOAD_UNPACK_DEADLINE = 30 * 60.0  # give up waiting for completion after 30 min
TORBOX_NUDGE_WINDOW = 10.0   # R46: min seconds between auto TORBOX refreshes
GOFILE_TTL_INTERVAL = 6 * 3600.0  # seconds between GoFile TTL expiry passes

# R26b: when GoFile still rate-limits a job after the quick in-request
# retries (10 s then 20 s), the job is not failed — it goes on a scheduled
# retry queue and is retried GOFILE_RETRY_AFTER later, up to
# GOFILE_RETRY_MAX times, with the wait visible as a queued/scheduled state.
GOFILE_RETRY_AFTER = 30.0 * 60.0   # seconds until the scheduled retry fires
GOFILE_RETRY_MAX = 3               # scheduled retries before giving up

# qBittorrent-style category filter: display names in the dropdown, API
# values in the search/start POST body.
CATEGORY_LABELS = ("All categories", "Anime", "Books", "Games", "Movies",
                   "Music", "Pictures", "Software", "TV shows")
CATEGORY_API = {"All categories": "all", "Anime": "anime", "Books": "books",
                "Games": "games", "Movies": "movies", "Music": "music",
                "Pictures": "pictures", "Software": "software",
                "TV shows": "tv"}

# R20: the second search filter, mirroring qBittorrent's own "Search in:"
# dropdown. "All plugins" is the only built-in; the names of every ENABLED
# installed plugin are appended at runtime once the plugin list arrives from
# qBittorrent. Disabled plugins are hidden entirely (user's R20 request), so
# there is no "only disabled" choice to make.
PLUGIN_FILTER_LABELS = ("All plugins",)

# R16: Torbox account torrents carry no category metadata, so the TORBOX
# FILES category dropdown filters by the names' own tags — the words
# release groups and indexers put in titles. Best effort by nature; a
# name that avoids every keyword shows in every category. "All categories"
# matches everything. TV additionally matches S01E01-style patterns.
TORBOX_CAT_KEYWORDS = {
    "Anime": ("anime", "episode", "season", "bdrip", "web-dl"),
    "Books": ("book", "epub", "pdf", "mobi", "azw", "comic", "manga"),
    "Games": ("game", "switch", "nsw", "nsp", "xci", "xbox", "playstation",
              "ps4", "ps5", "gog", "steam", "fitgirl", "dodi", "repack",
              "codex", "skidrow", "plaza", "razor", "goldberg", "empress"),
    "Movies": ("movie", "bluray", "blu-ray", "brrip", "dvdrip", "webrip",
               "hdrip", "2160p", "1080p", "720p", "hevc", "x264", "x265"),
    "Music": ("mp3", "flac", "320kbps", "album", "discography", "single",
              "vinyl", "rip"),
    "Pictures": ("jpg", "jpeg", "png", "photo", "wallpaper", "image",
                 "picture"),
    "Software": ("software", "installer", "setup", "portable", "windows",
                 "office", "adobe", "macos", "linux", "iso", "tool"),
    "TV shows": ("tv", "s01", "s02", "season", "episode", "series"),
}


# R17: the RESULTS Version cell means the game's own version/update NUMBER
# ("v1.0.1") for games, and the upload date for everything else (movies,
# TV, music...). These helpers decide which of the two a row gets.
_TITLE_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")


def _looks_like_tv(name: str) -> bool:
    """R18d: season/episode markers in a release name. A TV season pack
    often carries game-flavoured words ("S01 Complete Repack" — repack
    groups like FitGirl tag games that way), so a marker like S01E07,
    S01, "Season 2" or "Episode 12" must win over the game keywords."""
    low = (name or "").lower()
    if re.search(r"\bs\d{1,2}\s?e\s?\d{1,3}\b", low):
        return True
    if (re.search(r"\bseason[\s._-]?\d{1,2}\b", low)
            or re.search(r"\bepisode[\s._-]?\d{1,3}\b", low)):
        return True
    return bool(re.search(r"\bs\d{1,2}\b", low))


_MOVIE_MARKER_RE = re.compile(
    r"\b(?:480p|576p|720p|1080p|1080i|2160p|4k|bluray|blu-ray|bdrip|brrip"
    r"|dvdrip|dvdscr|hdrip|webrip|web-dl|webdl|hdtv|remux|hevc|h\.?26[45]"
    r"|x26[45]|xvid|av1|aac2|ddp?5|eac3|truehd)\b", re.IGNORECASE)

# R18e: keyword regexes, compiled once per keyword. Matched on a
# separator-normalised copy of the name (dots/dashes/underscores become
# spaces) with word boundaries, so neither "game" inside "The Imitation
# Game" nor "gog" inside "goggles" nor "rip" inside "description" leaks
# across categories.
_KW_RX: dict = {}


def _norm_words(text: str) -> str:
    return re.sub(r"[._\-]+", " ", (text or "").lower())


def _kw_match(normalized: str, keywords) -> bool:
    for kw in keywords:
        kwn = re.sub(r"[._\-]+", " ", kw).strip()
        rx = _KW_RX.get(kwn)
        if rx is None:
            rx = re.compile(r"\b" + re.escape(kwn) + r"\b")
            _KW_RX[kwn] = rx
        if rx.search(normalized):
            return True
    return False


def _looks_like_movie(name: str) -> bool:
    """R18e: movie/TV media markers — resolutions, sources, codecs. A
    name carrying one of these is a video release, not a game, however
    game-flavoured its words are ("The Imitation Game 1080p")."""
    return bool(_MOVIE_MARKER_RE.search(name or ""))


def _looks_like_media(name: str) -> bool:
    return _looks_like_tv(name) or _looks_like_movie(name)


def _looks_like_game(name: str) -> bool:
    """Name-based game detection for 'All categories' searches (the words
    release groups and indexers put in game titles). R18d: a TV
    season/episode marker disqualifies the name. R18e: so do movie
    markers (1080p, x264, BluRay, ...), and the keyword match itself is
    word-boundary based."""
    if _looks_like_media(name):
        return False
    return _kw_match(_norm_words(name), TORBOX_CAT_KEYWORDS["Games"])


def _upload_date_text(item: SearchItem) -> str:
    """When the row is not a game its Version cell shows a date: the
    torrent's upload date when qBittorrent reports one, else a year from
    the title, else nothing."""
    if item.pub_date and item.pub_date > 0:
        try:
            return time.strftime("%Y-%m-%d", time.gmtime(item.pub_date))
        except (ValueError, OverflowError, OSError):
            pass
    match = _TITLE_YEAR.search(item.name or "")
    return match.group(1) if match else ""


def _magnet_display_name(magnet: str) -> str:
    """A display name for a magnet URI: its dn= parameter when present,
    'magnet link' otherwise. Display only — never a secret."""
    query = magnet.split("?", 1)[1] if "?" in magnet else ""
    for kv in query.split("&"):
        if kv.lower().startswith("dn="):
            return unquote_plus(kv[3:]).strip() or "magnet link"
    return "magnet link"


def _url_filename(url: str) -> str:
    """A safe local filename for a pasted http(s) URL, from its path."""
    name = os.path.basename(urlparse(url).path) or "link-download"
    cleaned = "".join(c for c in name if c not in '\\/:*?"<>|').strip()
    return cleaned or "link-download"


def _name_from_file(file_name: str) -> str:
    """R30: a folder named after its single file — extension off, and any
    multi-part ".partN" tail off too ("Show.S01E01.part2.rar" becomes
    "Show.S01E01"). Hidden-file stems (".gitignore") are left alone."""
    stem = file_name.strip()
    dot = stem.rfind(".")
    if dot > 0:
        stem = stem[:dot]
    m = re.match(r"^(?P<base>.*?)\.part\d+$", stem, re.IGNORECASE)
    if m and m.group("base"):
        stem = m.group("base")
    return stem.strip()


def _common_name_from_files(names) -> str:
    """R31: a folder name for a MULTI-file drop — the user's "pinpoint the
    game or movie" ask. Any ".partN" tail comes off each name first (a
    multi-part archive collapses to its base), then the longest common
    prefix of what is left is the identity: "Movie.2023.1080p.mkv" plus
    "Movie.2023.1080p.nfo" gives "Movie.2023.1080p"; "Game (World).3ds"
    plus "Game (World) (Update).3ds" gives "Game (World)". A dangling
    trailing bracket or separator is trimmed away. Empty string when
    nothing meaningful is shared (or the prefix is under two characters):
    the caller leaves the folder alone."""
    stems = []
    for n in names:
        stem = str(n or "").strip()
        dot = stem.rfind(".")
        if dot > 0:
            stem = stem[:dot]
        mm = re.match(r"^(?P<base>.*?)\.part\d+$", stem, re.IGNORECASE)
        if mm and mm.group("base"):
            stem = mm.group("base")
        if stem:
            stems.append(stem)
    if not stems:
        return ""
    prefix = stems[0]
    for s in stems[1:]:
        while prefix and not s.startswith(prefix):
            prefix = prefix[:-1]
        if not prefix:
            return ""
    while prefix and (prefix[-1] in " .-_("
                      or prefix.count("(") > prefix.count(")")):
        prefix = prefix[:-1]
    return prefix if len(prefix) >= 2 else ""


def _gofile_folder_name(name: str) -> str:
    """A GoFile folder name for a release (R28): the release name with
    path separators and characters GoFile's web UI handles badly removed,
    trimmed so long torrent names still fit. Falls back to "upload"."""
    nice = re.sub(r'[\\/:*?"<>|]+', " ", str(name or ""))
    nice = " ".join(nice.split())
    return (nice[:100] or "upload")


def _fetch_url_to(url: str, dest: Path) -> None:
    """Download a URL's bytes to dest (worker threads only). Uses the same
    browser-like User-Agent the engine uses, since some hosts 403 the
    default Python one."""
    request = urllib.request.Request(url,
                                     headers={"User-Agent": DOWNLOAD_USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, \
            open(dest, "wb") as out:
        shutil.copyfileobj(response, out)


# R44: search drives qBittorrent's WebUI, and a fresh qBittorrent has the
# WebUI off, so a "connection refused" on 127.0.0.1:8080 is the single most
# likely reason search fails for a new user. When an exception looks like
# that, the log line carries the exact fix instead of a bare error.
_QBIT_HINT = ("Search needs qBittorrent running with its WebUI on: open "
              "qBittorrent \u2192 Tools \u2192 Options \u2192 Web UI \u2192 "
              "tick \u201cEnable the Web User Interface\u201d AND \u201cBypass "
              "authentication for clients on localhost\u201d \u2192 OK.")


def _qbit_hint(exc: BaseException) -> str:
    """The qBittorrent setup hint when exc looks like a dead WebUI, else ''."""
    text = str(exc).lower()
    if any(needle in text for needle in (
            "connection refused", "connectionreset", "connection reset",
            "name or service not known", "temporarily unavailable",
            "webui", "web ui", "refused", "timed out", "timeout",
            "couldn't connect", "cannot connect")):
        return _QBIT_HINT
    return ""


class _NoKeyClient:
    """Stand-in Torbox client for when TORBOX_API_KEY is missing.

    The engine must be constructible at startup so existing state.json
    records load and show; with no key every engine call fails with this
    clear, secret-free message instead of a traceback. The poll thread is
    not started in that case, so these methods are only ever hit from an
    explicit user action."""

    def _fail(self, *args, **kwargs):
        raise TorboxError("TORBOX_API_KEY missing in .env — set it to use downloads")

    create_torrent = _fail
    create_torrent_file = _fail
    find_by_hash = _fail
    mylist = _fail
    request_file_link = _fail
    request_zip_link = _fail
    delete_torrent = _fail


class App(_TkBase):
    def __init__(self, config: Config, handoff_instance=None):
        super().__init__()
        self.config = config
        # R36: the single-instance peer (None when the port could not even
        # be attempted); the listener starts once the widgets exist.
        self._handoff = handoff_instance
        self.title("Torbox Downloader")
        self.configure(background=Theme.BG)
        self.resizable(True, True)
        # R35: open as a windowed app centered on the screen (user: "opens in
        # the center of the screen at a default windowed size"). The window
        # manager was filling the whole screen; this starts it at a fixed
        # comfortable size instead, never wider/taller than the screen itself,
        # with the rest of the app reachable through the global scrollbar.
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            w = min(sw - 80, 1200)
            h = min(sh - 120, 820)
            x = max((sw - w) // 2, 0)
            y = max((sh - h) // 2, 0)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except tk.TclError:
            pass
        apply_theme(self)
        self._apply_treeview_style()
        # Window/taskbar icon. Round R10: a real .ico handed to iconbitmap()
        # is the reliable taskbar fix on Windows (iconphoto alone leaves the
        # Python logo on the taskbar). The embedded PNG stays as a fallback
        # for when the .ico file is missing or Tcl refuses it. Keep the
        # reference on the App so Tk never garbage-collects it. Cosmetic
        # only — a failure must never block startup.
        self._icon_img = make_photo_image(self)
        ico_path = BUNDLE_ROOT / "icon.ico"
        ico_applied = False
        if ico_path.exists():
            try:
                self.iconbitmap(str(ico_path))
                ico_applied = True
            except tk.TclError:
                pass  # fall through to iconphoto below
        if not ico_applied and self._icon_img is not None:
            try:
                self.iconphoto(True, self._icon_img)
            except tk.TclError:
                self._icon_img = None

        # ---- state -------------------------------------------------------
        self._events: queue.Queue = queue.Queue()   # workers post; _drain applies
        self._results_iids: dict[str, SearchItem] = {}   # results tree iid -> item
        self._results_base = {"name": "Name", "version": "Version",
                              "size": "Size", "seeds": "Seeds",
                              "engine": "Engine"}   # heading texts without indicators
        self._sort_col: str | None = None           # active results sort column
        self._sort_desc = False                     # active results sort direction
        self._download_iids: dict[str, str] = {}    # downloads tree iid -> infohash
        self._searching = False
        self._search_cancel: threading.Event | None = None  # current worker's cancel
        self._search_job_id: int | None = None      # current search's qBit job id
        self._qbit_plugins: list[dict] = []         # R19: last fetched plugin list
        self._closing = False
        self._stop_poll = threading.Event()
        self._asked_complete: set[str] = set()      # infohashes already popup-asked
        self._known_status: dict[str, str] = {}     # infohash -> last seen status
        self._torbox_nudge_last = 0.0   # R46: last auto TORBOX refresh time
        # R26b: GoFile jobs that exhausted their quick rate-limit retries sit
        # here until their scheduled retry time. infohash -> {"name", "kind",
        # "due", "attempts", "reason"}; kind "upload" re-runs _start_upload,
        # kind "remove" re-runs _remove_link_worker.
        self._gofile_scheduled: dict[str, dict] = {}
        self._gofile_sched_lock = threading.Lock()
        self._ttl_lock = threading.Lock()           # guards overlapping TTL passes
        self._torbox_all: list = []                 # R16: cached account rows
        self._torbox_row_meta: dict = {}            # R21: painted row iid -> (infohash, torrent_id, name)
        self._torbox_link_running: set = set()      # R21: infohashes with a link job in flight
        # R36 handoff state: torrents added through the file-association
        # handoff, waiting to be cached on Torbox; and the remembered
        # default applied in memory (a saved default never needs a restart).
        self._handoff_pending: dict = {}            # infohash -> display name
        self._handoff_gofile_on_complete: set = set()
        self._handoff_default_setting: str = ""
        self._action_origin: str | None = None      # R22: table the user last clicked a row in
        # R22c: the top activity bar's live inputs. Uploads register their
        # progress accumulator here (workers write, the UI ticker reads);
        # download progress is computed from the store + .part files on disk.
        self._upload_jobs: dict = {}                # job key -> _UploadJob
        self._upload_jobs_lock = threading.Lock()
        self._progress_last = {"t": 0.0, "down": 0, "up": 0,
                               "down_speed": 0.0, "up_speed": 0.0}
        # R23: the Stop button's plumbing. One cancel event per in-flight
        # job (keyed by the job's infohash or a drop-... key); every worker
        # checks its event in its wait loops and mid-upload, and the Stop
        # button sets them all. The engine has its own cancel() for the
        # per-file downloads running in its pool.
        self._cancel_lock = threading.Lock()
        self._cancel_events: dict[str, threading.Event] = {}
        # R24: infohashes whose Make-GoFile-link job is pulling the files
        # down to this PC itself; the local copy is deleted again once the
        # upload succeeds (a torrent the user pre-downloaded is never in
        # here and keeps its folder).
        self._link_delete_after: dict[str, bool] = {}
        # R17: title translation cache (original → English) on disk, and the
        # stop event that ends an in-flight Translate pass when the app closes.
        self._torbox_en = TitleTranslations(ROOT / "data" / "torbox-english.json")
        self._torbox_translate_stop = threading.Event()
        # R18: sortable Torbox headers + automated translation state.
        self._torbox_sort_col: str | None = None
        self._torbox_sort_desc = False
        self._torbox_translating = False

        # ---- backend objects ----------------------------------------------
        self.presets = Presets()
        if self.config.has("TORBOX_API_KEY"):
            self.engine = DownloadEngine(config.torbox_api_key,
                                         state_path=ROOT / "state.json",
                                         download_root=ROOT / "downloads")
        else:
            # Keep the UI alive and the saved downloads visible without a key.
            self.engine = DownloadEngine("", state_path=ROOT / "state.json",
                                         download_root=ROOT / "downloads",
                                         client=_NoKeyClient())
        self.gofile = GofileClient(config.gofile_api_token)
        self.qbit = QBitSearchClient(config.qbit_url, config.qbit_port,
                                     config.qbit_username, config.qbit_password)

        # ---- widgets -------------------------------------------------------
        self._build_widgets()

        # ---- background poller ----------------------------------------------
        if self.config.has("TORBOX_API_KEY"):
            threading.Thread(target=self._poll_loop, daemon=True,
                             name="engine-poll").start()
        else:
            self.log_line("Background polling disabled (TORBOX_API_KEY missing).")

        # GoFile TTL scheduler (task 7): runs one pass right after startup and
        # then every GOFILE_TTL_INTERVAL (6 hours). Daemon; stops with the app.
        threading.Thread(target=self._ttl_loop, daemon=True,
                         name="gofile-ttl").start()

        # R19: search plugins — fetch the plugin list (feeds the "Search in:"
        # dropdown), run qBittorrent's own plugin-update pass once at startup
        # (the same thing the GUI's "Check for Updates" does), then refetch
        # the list. A forced repeat lives in Settings. Daemon.
        threading.Thread(target=self._plugin_update_worker, args=(False,),
                         daemon=True, name="plugin-update").start()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._drain)
        # R22c: the top activity bar's 1-second refresh tick.
        self.after(1000, self._tick_progress)
        # R25: the GOFILE STORAGE browser loaded the account root once at
        # startup. R27 (user: "since we are rate limited, make it so that
        # the entries in the gofile table persist and only disappear after
        # being checked again"): a cached listing is painted from disk with
        # no GoFile request at all; only a first-ever load (no cache) still
        # fetches. A failure never wipes what is shown.
        self.after(2500, self._gofile_startup_restore)
        # R43 (user ask): TORBOX FILES and GOFILE refresh automatically —
        # a live pass shortly after startup, then the same pass every half
        # hour while the window is open.
        self.after(4000, self._auto_refresh_tables)

        # ---- startup lines ---------------------------------------------------
        self.set_status(True, "Ready")
        self.log_line("App started.")
        if self.config.has("TORBOX_API_KEY"):
            self.log_line("TORBOX_API_KEY found in .env (value hidden).")
        else:
            self.log_line("TORBOX_API_KEY missing in .env.")
        if self.config.has("GOFILE_API_TOKEN"):
            self.log_line("GOFILE_API_TOKEN found in .env (value hidden).")
        else:
            self.log_line("GOFILE_API_TOKEN not set; app will use a guest token.")
        self.log_line(f"qBittorrent API expected at {self.config.qbit_url}:{self.config.qbit_port}")
        existing = len(self.engine.store.all())
        self.log_line(f"Loaded {existing} download(s) from state.json.")
        self.log_line(f"Destination presets: {len(self.presets.list())}"
                      + (f" (default: {self.presets.default})" if self.presets.default else ""))
        self._refresh_downloads_table()
        # R16, per the user: load ALL files in the Torbox account into the
        # TORBOX FILES pane at startup, no Find press needed. Small delay so
        # the window paints first; silently skipped when no key is set.
        if self.config.has("TORBOX_API_KEY"):
            self.after(800, self.on_torbox_search)
        # R18 (the user: "why is it so off centered?"): Tk opens a new window
        # near the top-left of the screen by default, which reads as the
        # whole app sitting lopsided on a large monitor. Place it centered
        # (slightly above true center, which looks more natural) once the
        # widgets have been measured.
        self.after(60, self._center_on_screen)
        # R36: file-association handoff. The single-instance peer was
        # claimed in main() before this window existed; wire its callback
        # here and start the listener, then consume anything this launch
        # itself was started with (a double-clicked .torrent while the app
        # was closed joins the queue as soon as the UI is up).
        if self._handoff is not None:
            self._handoff._on_items = self.on_handoff_items
            try:
                self._handoff.start()
            except Exception as exc:
                self.log_line(f"Handoff listener unavailable: {exc}")
            startup_items = list(getattr(self._handoff, "startup_items", None) or [])
            self._handoff.startup_items = []
            if startup_items:
                self.after(900, lambda: self._consume_handoff_items(startup_items))

    # ------------------------------------------------------------------ styling

    def _apply_treeview_style(self) -> None:
        """Minimal Treeview styling consistent with the theme (the design spec
        does not cover Treeview; this keeps tables on PANEL/PANEL2)."""
        # R41: on Linux the toolkit's default fonts render one step smaller
        # than Windows' Segoe UI, which cramped every button, label and row
        # (user: "why is it so broken / clumped together"). Lift the named
        # fonts to the Windows scale; Windows stays exactly as it was.
        if sys.platform != "win32":
            for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont",
                         "TkMenuFont", "TkTooltipFont"):
                f = tkfont.nametofont(name)
                if 0 < f.actual("size") < 10:
                    f.configure(size=10)
        style = ttk.Style(self)
        # R41: row height follows the UI font so the larger Linux rows never
        # clip; on Windows this stays at roughly the old 24px look.
        rowheight = tkfont.nametofont("TkDefaultFont").metrics("linespace") + 8
        style.configure("Treeview", background=Theme.PANEL, foreground=Theme.TEXT,
                        fieldbackground=Theme.PANEL, rowheight=rowheight,
                        borderwidth=0)
        style.configure("Treeview.Heading", background=Theme.PANEL2,
                        foreground=Theme.TEXT, borderwidth=0)
        style.map("Treeview.Heading", background=[("active", Theme.PANEL2)])
        style.map("Treeview", background=[("selected", Theme.PANEL2)],
                  foreground=[("selected", Theme.TEXT)])

    # ------------------------------------------------------------------ widgets

    def _build_widgets(self) -> None:
        # R33: the whole app now sits inside a scrollable canvas, so a
        # resizable window that is shorter than the content scrolls instead
        # of clipping (user: "you made the app resizable but didn't add a
        # global scroll bar"). When the window is tall enough the scrollbar
        # shows a full thumb and does nothing, so nothing changes visually.
        outer = ttk.Frame(self)
        outer.grid(row=0, column=0, sticky="nsew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        scroll = tk.Canvas(outer, highlightthickness=0, background=Theme.BG)
        vbar = ttk.Scrollbar(outer, orient="vertical", command=scroll.yview)
        hbar = ttk.Scrollbar(outer, orient="horizontal", command=scroll.xview)
        scroll.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        scroll.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)
        container = ttk.Frame(scroll)
        _win = scroll.create_window((0, 0), window=container, anchor="nw")

        def _sync_scroll(_event=None) -> None:
            # the content is at least as wide as the canvas, so full-width
            # rows stretch on a wide window; when the tables' minimum
            # widths need more room, the horizontal bar scrolls instead of
            # clipping. The guard keeps the resize event from looping.
            width = max(int(scroll.winfo_width()), int(container.winfo_reqwidth()))
            if str(width) != (scroll.itemcget(_win, "width") or ""):
                scroll.itemconfigure(_win, width=width)
            # R41: the window item also grows to the canvas height so the
            # weighted table rows can stretch instead of dead space.
            height = max(int(scroll.winfo_height()),
                         int(container.winfo_reqheight()))
            if str(height) != (scroll.itemcget(_win, "height") or ""):
                scroll.itemconfigure(_win, height=height)
            scroll.configure(scrollregion=scroll.bbox("all"))

        scroll.bind("<Configure>", _sync_scroll)
        container.bind("<Configure>", _sync_scroll)

        def _on_wheel(event) -> None:
            # mouse wheel scrolls the page, but never hijacks it from the
            # widgets that scroll themselves (tables, the log, comboboxes)
            w = getattr(event, "widget", None)
            while w is not None:
                if isinstance(w, (ttk.Treeview, tk.Text, tk.Listbox,
                                  ttk.Combobox)):
                    return
                w = getattr(w, "master", None)
            step = (-1 if getattr(event, "delta", 0) > 0 else 1)
            scroll.yview_scroll(step, "units")

        def _on_wheel_linux(event) -> None:
            scroll.yview_scroll(-1 if event.num == 4 else 1, "units")

        # bound app-wide: the content frame covers the canvas, so a plain
        # canvas bind would never fire; the widget check above lets inner
        # scrollables (tables, the log, comboboxes) win the wheel instead
        self.bind_all("<MouseWheel>", _on_wheel)
        self.bind_all("<Button-4>", _on_wheel_linux)
        self.bind_all("<Button-5>", _on_wheel_linux)

        # Row 0: header. R22c: the right side carries the Steam-style
        # activity bar — one slim bar + one line of text that show the
        # progress and speed of every active download (Torbox -> this PC)
        # and upload (this PC -> GoFile), so it is the single live source
        # of truth for what is moving and how fast.
        header_frame = ttk.Frame(container)
        header_frame.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 5))
        header_frame.columnconfigure(1, weight=1)
        ttk.Label(header_frame, text="Torbox Downloader", style="Header.TLabel").grid(
            row=0, column=0, sticky="w")
        self._progress_bar = ttk.Progressbar(header_frame, length=280,
                                             mode="determinate", maximum=100,
                                             style="ProgDown.Horizontal.TProgressbar")
        self._progress_bar.grid(row=0, column=1, sticky="e", padx=(12, 8))
        self._progress_label = ttk.Label(header_frame, text="No active jobs")
        self._progress_label.grid(row=0, column=2, sticky="e")
        # R23: the Stop control lives on the activity bar, next to the jobs
        # it stops: one press ends the in-flight link jobs, uploads and PC
        # downloads.
        self._stop_button = ttk.Button(header_frame, text="Stop", width=6,
                                       command=self.on_stop_pressed)
        self._stop_button.grid(row=0, column=3, sticky="e", padx=(10, 0))
        # R22d: the bar's tint says WHERE the bytes are going, matching the
        # text's route label: blue = Torbox -> this PC, green = this PC ->
        # GoFile, amber = both at once.
        _pb_style = ttk.Style(self)
        for _name, _color in (("ProgDown.Horizontal.TProgressbar", Theme.ACCENT_BRIGHT),
                              ("ProgUp.Horizontal.TProgressbar", Theme.OK),
                              ("ProgMixed.Horizontal.TProgressbar", "#fbbf24")):
            _pb_style.configure(_name, background=_color, troughcolor=Theme.PANEL,
                                lightcolor=_color, darkcolor=_color,
                                bordercolor=Theme.PANEL)

        # R14: each area of the window gets its own small header so the
        # sections read as Search / Results / Downloads / Log from top to
        # bottom, per the user's layout feedback.
        ttk.Label(container, text="SEARCH", style="Section.TLabel").grid(
            row=1, column=0, sticky="w", padx=14, pady=(8, 0))

        # Row 2: search row (Enter key triggers the search too). The category
        # dropdown mirrors qBittorrent's search categories.
        search_frame = ttk.Frame(container)
        search_frame.grid(row=2, column=0, sticky="ew", padx=14, pady=5)
        ttk.Label(search_frame, text="Search:").grid(row=0, column=0, sticky="w", pady=5)
        self.search_entry = ttk.Entry(search_frame, width=34)
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=5)
        self.category_combo = ttk.Combobox(search_frame, values=list(CATEGORY_LABELS),
                                           state="readonly", width=15)
        self.category_combo.grid(row=0, column=2, sticky="w", padx=(0, 8), pady=5)
        self.category_combo.current(0)
        self.category_combo.bind("<<ComboboxSelected>>", self.on_category_changed)
        # R19: second filter — which search plugins run. Starts with the
        # three built-in choices; the installed plugin names are appended
        # once the startup plugin list arrives from qBittorrent.
        ttk.Label(search_frame, text="Search in:").grid(row=0, column=3,
                                                        sticky="w", pady=5)
        self.plugin_combo = ttk.Combobox(search_frame,
                                         values=list(PLUGIN_FILTER_LABELS),
                                         state="readonly", width=13)
        self.plugin_combo.grid(row=0, column=4, sticky="w", padx=(4, 8), pady=5)
        self.plugin_combo.current(0)
        # R28 (user: "search and clear and trending are all the same size"):
        # one shared width for the three of them.
        ttk.Button(search_frame, text="Search", width=10,
                   command=self.on_search).grid(
            row=0, column=5, sticky="e", pady=5)
        ttk.Button(search_frame, text="Clear", width=10,
                   command=self.on_clear_search).grid(
            row=0, column=6, sticky="w", padx=(8, 0), pady=5)
        # R19: Trending — fills the search box with the current year and
        # runs the search, so the table fills with the newest releases and
        # can be sorted by latest (Version) or most seeds.
        ttk.Button(search_frame, text="Trending", width=10,
                   command=self.on_trending).grid(
            row=0, column=7, sticky="w", padx=(8, 0), pady=5)
        search_frame.columnconfigure(1, weight=1)
        self.search_entry.bind("<Return>", lambda _event: self.on_search())

        # Row 4: results table.
        ttk.Label(container, text="RESULTS", style="Section.TLabel").grid(
            row=3, column=0, sticky="w", padx=14, pady=(8, 0))
        results_frame = ttk.Frame(container)
        # R41: nsew + the rowconfigure weights at the end of _build_widgets
        # let the tables absorb the window's extra height instead of leaving
        # dead space under the status line.
        results_frame.grid(row=4, column=0, sticky="nsew", padx=14, pady=5)
        self.results_tree = ttk.Treeview(
            results_frame, columns=("name", "version", "size", "seeds", "engine"),
            show="headings", height=8)
        for col, text, width, anchor in (("name", "Name", 400, "w"),   # R29: name left
                                         ("version", "Version", 120, "center"),
                                         ("size", "Size", 90, "center"),
                                         ("seeds", "Seeds", 70, "center"),
                                         ("engine", "Engine", 130, "center")):
            # R24b: headings take their column's anchor so centered data
            # does not sit under a left-stuck heading.
            self.results_tree.heading(col, text=text, anchor=anchor)
            self.results_tree.column(col, width=width, anchor=anchor)
        # Round R10: Name/Size/Seeds headings sort the rows currently shown
        # (Engine keeps its plain heading). Repeated clicks flip the direction.
        for col in ("name", "version", "size", "seeds"):
            self.results_tree.heading(
                col, command=lambda c=col: self.on_sort_results(c))
        # R22 select-then-press: clicking a result row only remembers it; the
        # Make GoFile link / Download buttons act on the remembered row.
        self.results_tree.bind("<<TreeviewSelect>>",
                               lambda _e: self._remember_selection("results"))
        results_scroll = ttk.Scrollbar(results_frame, command=self.results_tree.yview)
        self.results_tree.configure(yscrollcommand=results_scroll.set)
        self.results_tree.grid(row=0, column=0, sticky="nsew")
        results_scroll.grid(row=0, column=1, sticky="ns")
        results_frame.columnconfigure(0, weight=1)

        # Row 6 (R16): ADD LINK — a place to paste a link directly. My call
        # on scope (the user left it open): a magnet goes straight to Torbox
        # like the qBittorrent results do; a URL ending in .torrent is
        # fetched and added through the file-upload path; any other
        # http(s) link is downloaded into downloads/_links and shared as a
        # GoFile link (Torbox only accepts torrents, not arbitrary files).
        ttk.Label(container, text="ADD LINK", style="Section.TLabel").grid(
            row=5, column=0, sticky="w", padx=14, pady=(8, 0))
        link_row = ttk.Frame(container)
        link_row.grid(row=6, column=0, sticky="ew", padx=14, pady=5)
        self.link_entry = ttk.Entry(link_row)
        self.link_entry.grid(row=0, column=0, sticky="ew")
        self.link_entry.bind("<Return>", lambda _e: self.on_add_link())
        # R28 (user: "file and folder are the same size, but half the size
        # of add"): Add is 16 wide, File and Folder are 8 each.
        ttk.Button(link_row, text="Add", width=16,
                   command=self.on_add_link).grid(
            row=0, column=1, padx=(5, 0))
        # R18 (per the user: drag-and-drop was not working for them): the
        # same dialogs, clickable — "File" picks one or more files, "Folder"
        # picks a folder and adds every .torrent inside it.
        ttk.Button(link_row, text="File", width=8,
                   command=self.on_browse_files).grid(row=0, column=2,
                                                      padx=(4, 0))
        ttk.Button(link_row, text="Folder", width=8,
                   command=self.on_browse_folder).grid(row=0, column=3,
                                                       padx=(4, 0))
        link_row.columnconfigure(0, weight=1)

        # Row 7/8: top action row, ABOVE the downloads table (R14 split, per
        # the user: "download and make file above"). "Download" acts on the
        # selected RESULT; "Make GoFile link" acts on the selected DOWNLOAD.
        ttk.Label(container, text="DOWNLOADS", style="Section.TLabel").grid(
            row=7, column=0, sticky="w", padx=14, pady=(8, 0))
        download_row = ttk.Frame(container)
        download_row.grid(row=8, column=0, sticky="ew", padx=14, pady=5)
        for i, (label, command) in enumerate((("Download", self.on_download),
                                              ("Make GoFile link",
                                               self.on_make_gofile_link))):
            ttk.Button(download_row, text=label, command=command).grid(
                row=0, column=i, sticky="ew",
                padx=(0 if i == 0 else 4, 0))
            download_row.columnconfigure(i, weight=1, uniform="actions")

        # Row 7: downloads table.
        downloads_frame = ttk.Frame(container)
        downloads_frame.grid(row=9, column=0, sticky="nsew", padx=14, pady=5)
        self.downloads_tree = ttk.Treeview(
            downloads_frame, columns=("name", "status", "files", "where"),
            show="headings", height=8)
        # R22d: the user's screenshot — Status/Files/Where were still
        # w/e-anchored here while every other table got centered. Name stays
        # left-aligned (long names read better from the left). R24: the Link
        # column became "Where" (links live only in the GOFILE table).
        for col, text, width, anchor in (("name", "Name", 330, "w"),   # R29: name left
                                         ("status", "Status", 110, "center"),
                                         ("files", "Files", 80, "center"),
                                         ("where", "Where", 110, "center")):
            # R24b: headings take their column's anchor (matches the data).
            self.downloads_tree.heading(col, text=text, anchor=anchor)
            self.downloads_tree.column(col, width=width, anchor=anchor)
        downloads_scroll = ttk.Scrollbar(downloads_frame, command=self.downloads_tree.yview)
        self.downloads_tree.configure(yscrollcommand=downloads_scroll.set)
        self.downloads_tree.grid(row=0, column=0, sticky="nsew")
        downloads_scroll.grid(row=0, column=1, sticky="ns")
        downloads_frame.columnconfigure(0, weight=1)
        # R22b: the "Show archived" toggle is gone (the user asked for its
        # removal now that the links list carries the archived view). Archived
        # records simply stay in this table with an "archived <date>" status,
        # and the GOFILE section below is where they are reinstated.
        # R22 select-then-press: a downloads-row click only remembers the
        # row. R24: the stray link label under the table is gone — links
        # live only in the GOFILE table at the bottom.
        self.downloads_tree.bind(
            "<<TreeviewSelect>>",
            lambda _e: self._remember_selection("downloads"))
        # R25b: a click on the Where cell of an "On PC" row opens that
        # folder in the file manager (see _on_downloads_where_click).
        self.downloads_tree.bind(
            "<Button-1>", self._on_downloads_where_click)
        # R15 drag-and-drop: the downloads section accepts dropped .torrent
        # files (and folders containing them) and adds each to the Torbox
        # account, exactly like a magnet add. Only registered when the
        # optional tkinterdnd2 dependency is importable; otherwise drops are
        # ignored and a one-line hint goes to the log.
        if DND_AVAILABLE:
            downloads_frame.drop_target_register(DND_FILES)
            downloads_frame.dnd_bind("<<Drop>>", self._on_drop_files)

        # Row 8: bottom action row, BELOW the downloads table (R14 split):
        # the two actions that finish the pipeline, acting on the selected
        # DOWNLOAD row.
        unpack_row = ttk.Frame(container)
        unpack_row.grid(row=10, column=0, sticky="ew", padx=14, pady=5)
        for i, (label, command) in enumerate((("Unpack",
                                               self.on_download_unpack),
                                              ("Remove from PC",
                                               self.on_remove_pc))):
            ttk.Button(unpack_row, text=label, command=command).grid(
                row=0, column=i, sticky="ew",
                padx=(0 if i == 0 else 4, 0))
            unpack_row.columnconfigure(i, weight=1, uniform="actions")

        # Row 9 (R24): the old clickable link label was removed — links live
        # only in the GOFILE table at the bottom.

        # Row 10: LOG section, two horizontal halves (R15). Left half: the
        # app log (PANEL bg, Monospace, flat, scrollbar, timestamped,
        # bounded, auto-scroll — unchanged from the earlier tasks). Right
        # half: a live search over the files already in the user's Torbox
        # account — a name filter, a result table (Name/Status/Size) and a
        # count line. Both halves share one row; each carries its own small
        # header.
        log_frame = ttk.Frame(container)
        log_frame.grid(row=11, column=0, sticky="nsew", padx=14, pady=5)

        left = ttk.Frame(log_frame)
        left.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="LOG", style="Section.TLabel").pack(
            anchor="w", pady=(0, 2))
        log_inner = ttk.Frame(left)
        log_inner.pack(fill="both", expand=True)
        self.log = tk.Text(log_inner, height=12, width=40, wrap="word",
                           background=Theme.PANEL, foreground=Theme.TEXT,
                           insertbackground=Theme.TEXT, relief="flat",
                           borderwidth=0, state="disabled",
                           font=(("Consolas", 10) if sys.platform == "win32"
                                 else ("DejaVu Sans Mono", 10)))
        log_scroll = ttk.Scrollbar(log_inner, command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        log_scroll.grid(row=0, column=1, sticky="ns")
        log_inner.columnconfigure(0, weight=1)
        log_inner.rowconfigure(0, weight=1)

        right = ttk.Frame(log_frame)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        # R24: section head carries the Torbox dashboard link, styled like
        # the GoFile dashboard link in the GOFILE head.
        tb_head = ttk.Frame(right)
        tb_head.pack(fill="x", pady=(0, 2))
        ttk.Label(tb_head, text="TORBOX FILES", style="Section.TLabel").pack(
            side="left")
        tb_dash = ttk.Label(tb_head, text="Torbox dashboard ↗",
                            foreground=Theme.ACCENT, cursor="hand2",
                            background=Theme.BG)
        tb_dash.pack(side="right")
        tb_dash.bind("<Button-1>", lambda _e: webbrowser.open(
            "https://torbox.app/dashboard"))
        tb_row = ttk.Frame(right)
        tb_row.pack(fill="x", pady=(0, 3))
        self.torbox_query = ttk.Entry(tb_row)
        self.torbox_query.pack(side="left", fill="x", expand=True)
        self.torbox_query.bind("<Return>", lambda _e: self.on_torbox_search())
        # R16: the "x" clears the query and category and shows every torrent
        # from the cached account list without re-fetching. R35: it sits right
        # beside the search bar now (user: "put the x next to the search bar").
        ttk.Button(tb_row, text="x", width=2, command=self.on_torbox_clear).pack(
            side="left", padx=(3, 0))
        # R16: same category dropdown as the qBittorrent search, scoped to
        # the account list. Torbox stores no categories, so this filters by
        # the names' own tags (see TORBOX_CAT_KEYWORDS) — best effort.
        self.torbox_cat = ttk.Combobox(tb_row, state="readonly", width=13,
                                       values=CATEGORY_LABELS)
        self.torbox_cat.current(0)
        self.torbox_cat.pack(side="left", padx=(5, 0))
        self.torbox_cat.bind("<<ComboboxSelected>>",
                             lambda _e: self.on_torbox_filter_changed())
        ttk.Button(tb_row, text="Find", command=self.on_torbox_search).pack(
            side="left", padx=(5, 0))
        # R34: the user asked for a refresh button for this part. Find already
        # refetches the live account list, so Refresh is the same action with
        # a name that says what it does to someone not filtering by a query.
        ttk.Button(tb_row, text="Refresh", width=8,
                   command=self.on_torbox_search).pack(side="left", padx=(5, 0))
        # R18: translation is automated (a quiet pass runs whenever the
        # account list loads); the forced pass lives in the settings popup.
        # (button removed per the user)
        tb_inner = ttk.Frame(right)
        tb_inner.pack(fill="both", expand=True)
        # R17 originally carried a separate English column; R18 dropped it
        # (translation became automated, search-only) — R40 shows the cached
        # English title IN the Name column again (user, on Linux: "why
        # isn't it translated"). Status sits right of Size. Headers are
        # anchored like their data and clickable to sort (the user missed
        # sorting the Torbox list after the R16 rebuild). R40: the fixed
        # pixel widths were tuned on the laptop; on Linux the toolkit's
        # font renders wider and everything clipped ("so clamped
        # together"), so every width now comes from the actual rendered
        # font instead of hard pixels.
        self.torbox_tree = ttk.Treeview(
            tb_inner, columns=("name", "added", "size", "status"),
            show="headings", height=11, selectmode="browse")
        self._torbox_base = {}
        _f = tkfont.nametofont("TkDefaultFont")

        def _w(*samples, pad=24, floor=46):
            """Pixel width fitting the widest sample in the real UI font."""
            return max(floor, max(_f.measure(s) for s in samples) + pad)

        for col, text, width, anchor in (
                ("name", "Name", max(240, _w("Name")), "w"),        # R29: name left
                ("added", "Added", _w("Added ▼", "0000-00-00"), "center"),
                ("size", "Size", _w("Size ▼", "1024.5 GiB"), "center"),
                ("status", "Status",
                 _w("Status ▼", "Downloading", "Completed", "Cached",
                    "Seeding", "Queued", "Preparing", "Finished",
                    "Paused", "Errored"), "center")):
            self.torbox_tree.heading(col, text=text, anchor=anchor,
                                     command=lambda c=col: self.on_sort_torbox(c))
            self.torbox_tree.column(col, width=width, anchor=anchor,
                                    stretch=(col == "name"))
            self._torbox_base[col] = text
        self.torbox_tree.column("name", minwidth=120)
        self.torbox_tree.column("added", minwidth=70)
        # R22 select-then-press: a torbox-row click only remembers the row;
        # the Make GoFile link / Download buttons act on the remembered row.
        self.torbox_tree.bind("<<TreeviewSelect>>",
                              lambda _e: self._remember_selection("torbox"))
        tb_scroll = ttk.Scrollbar(tb_inner, command=self.torbox_tree.yview)
        self.torbox_tree.configure(yscrollcommand=tb_scroll.set)
        self.torbox_tree.grid(row=0, column=0, sticky="nsew")
        tb_scroll.grid(row=0, column=1, sticky="ns")
        tb_inner.columnconfigure(0, weight=1)
        tb_inner.rowconfigure(0, weight=1)
        self.torbox_count = ttk.Label(right, text="", style="Muted.TLabel")
        self.torbox_count.pack(anchor="w", pady=(2, 0))
        # R16: the user asked for both halves the same size. The right pane's
        # height is content-driven (query row + tree + count label), so once
        # Tk has measured it, the log Text's line count is tuned to match.
        self.after(80, self._match_log_height)

        # Row 12: GOFILE section. R22 made it a links table; R25 split it
        # into two halves (LINKS left, STORAGE right); R32 merged them back
        # into ONE table (user: "any file on gofile has a share link, so
        # there is no point seperating links and storage"): the R31 inline
        # tree — folders expand under their own row, two clicks open the
        # folder's public page — carries the links table's Link/State/Added
        # columns beside the name, and link-only rows (records whose folder
        # is not in the current listing, archived included) are appended so
        # nothing disappears before a real check. Delete and Refresh sit in
        # the title row (R33 removed the old Remove link button, Delete
        # does that job now); the crumbs hint stays right-aligned
        # above Refresh (R25b), the dashboard link at the left end.
        gofile_frame = ttk.Frame(container)
        gofile_frame.grid(row=12, column=0, sticky="nsew", padx=14, pady=(5, 0))

        # R32 (user: "any file on gofile has a share link, so there is no
        # point seperating links and storage"): LINKS and STORAGE are ONE
        # section now. The tree keeps the R31 inline dropdown (one click
        # expands a folder under its own row, two clicks open its public
        # page) and the old links table's columns ride beside it: Link,
        # State, Added. Link-only rows (records whose folder is not in the
        # current listing, archived ones included) are appended so nothing
        # disappears before a real check.
        # Top row: the crumbs hint right-aligned so it still sits directly
        # above Refresh (R25b), with the dashboard link at the left end.
        crumb_row = ttk.Frame(gofile_frame)
        crumb_row.pack(fill="x", pady=(0, 1))
        self.gofile_crumbs = ttk.Label(crumb_row, text="(loading…)",
                                       background=Theme.BG,
                                       foreground=Theme.MUTED, anchor="e")
        self.gofile_crumbs.pack(side="right", fill="x", expand=True)
        dashboard = ttk.Label(crumb_row, text="GoFile dashboard ↗",
                              foreground=Theme.ACCENT, cursor="hand2",
                              background=Theme.BG)
        dashboard.pack(side="left")
        dashboard.bind(
            "<Button-1>", lambda _e: webbrowser.open("https://gofile.io/"))
        # Title row: the three buttons, sized as everywhere else (R28).
        gofile_head = ttk.Frame(gofile_frame)
        gofile_head.pack(fill="x")
        ttk.Label(gofile_head, text="GOFILE",
                  style="Section.TLabel").pack(side="left")
        ttk.Button(gofile_head, text="Refresh", width=8,
                   command=self.on_gofile_storage_refresh).pack(side="right")
        ttk.Button(gofile_head, text="Delete", width=7,
                   command=self.on_gofile_storage_delete).pack(side="right",
                                                               padx=(0, 5))
        # R34: the user asked for an add-file button for any file they might
        # want to add to GoFile. It reuses the dropped-file worker, so the
        # file gets the same treatment as a drop: its own folder named after
        # it, live progress on the activity bar, a store record and a link.
        ttk.Button(gofile_head, text="Add file", width=8,
                   command=self.on_gofile_add_file).pack(side="right",
                                                         padx=(0, 5))
        self.gofile_tree = ttk.Treeview(
            gofile_frame, columns=("link", "state", "added"),
            show="tree headings", height=4, selectmode="extended")
        # R31 (user: "just a drop down with an arrow" / "no way to get
        # back"): folders expand IN PLACE under their own row (the +/-
        # arrow on the left), they never replace the table, and collapsing
        # is the way back. R32: Name left-aligned; the link columns beside.
        # R42: Name stretches to take the table's slack (a 300px cap cut
        # long release names off on both machines); the link/state/added
        # columns are pinned at their fixed widths.
        self.gofile_tree.heading("#0", text="Name", anchor="w")
        self.gofile_tree.column("#0", width=300, anchor="w", stretch=True)
        for col, width, anchor in (("link", 280, "center"),
                                   ("state", 130, "center"),
                                   ("added", 90, "center")):
            self.gofile_tree.heading(col, text=col.capitalize(),
                                     anchor=anchor)
            self.gofile_tree.column(col, width=width, anchor=anchor,
                                    stretch=False)
        self.gofile_tree.pack(fill="both", expand=True, pady=(3, 0))
        # One click on a folder toggles it inline (open shows its children
        # beneath the row, closed hides them), delayed 300 ms so a double
        # click can overtake it and open the public page instead; ctrl/shift
        # clicks (multi-select for Delete) never toggle. The +/- arrow uses
        # the tree's own open event.
        self.gofile_tree.bind("<Button-1>", self.on_gofile_storage_click)
        self.gofile_tree.bind(
            "<Double-1>", self.on_gofile_storage_open)
        self.gofile_tree.bind("<<TreeviewOpen>>",
                              self.on_gofile_storage_arrow)
        self.gofile_tree.bind(
            "<<TreeviewSelect>>",
            lambda _e: self._remember_selection("links"))
        self._gofile_click_timer: str = ""
        # bookkeeping for the browser: treeview iid -> content metadata
        self._gofile_nodes: dict[str, dict] = {}
        # R31: inline expansion — content ids of folders whose children are
        # on their way in (mapped to the row they slide under), and the
        # account-root id the table always sits on.
        self._gofile_pending: dict[str, str] = {}   # content id -> folder iid
        self._gofile_crumbs_base: str = ""
        self._gofile_loading = False
        # R27: the storage half remembers its last listing on disk, so a
        # launch or a folder visit costs no GoFile request at all — entries
        # stay until a real Refresh checks again. trail + per-folder data.
        self._gofile_cache_path = (Path(self.engine.store.path.parent)
                                   / "gofile_storage_cache.json")
        self._gofile_cache: dict = {}
        self._gofile_cached_view = False   # current table painted from cache?
        self._gofile_cache_load()
        # R31: the table always sits on the account root; the id is
        # remembered in the cache so a restart repaints it without asking.
        self._gofile_root_id: str = str(
            self._gofile_cache.get("root_id") or "")

        # Row 13: status line. Round R11: a small settings cog opens
        # the in-app settings popup. Round R13: the Presets dialog moved here
        # too as a folder-icon button next to the cog, and a Clear button at
        # the right end empties the log pane. R14: both are real drawn PNG
        # icons (the Unicode glyphs rendered badly on Windows: the cog looked
        # like a flower and the folder was a white crossed box), same size
        # and style so they sit aligned.
        status_frame = ttk.Frame(container)
        status_frame.grid(row=13, column=0, sticky="ew", padx=14, pady=(5, 12))
        self._cog_img = cog_photo(self)
        self._folder_img = folder_photo(self)
        cog = ttk.Button(status_frame, image=self._cog_img, width=3,
                         style="Icon.TButton", command=self.on_open_settings)
        cog.grid(row=0, column=0, sticky="w", padx=(0, 5))
        presets_btn = ttk.Button(status_frame, image=self._folder_img, width=3,
                                 style="Icon.TButton",
                                 command=self._open_presets_dialog)
        presets_btn.grid(row=0, column=1, sticky="w", padx=(0, 5))
        self.status = tk.Label(status_frame, text="", background=Theme.BG,
                               foreground=Theme.MUTED, anchor="w")
        self.status.grid(row=0, column=2, sticky="ew")
        status_frame.columnconfigure(2, weight=1)
        ttk.Button(status_frame, text="Clear log", width=9,
                   command=self.on_clear_log).grid(
            row=0, column=3, sticky="e")
        # R11b fix: the weight sits on the CONTENT column (0), so every row
        # stretches with the window. It used to sit on a second column that
        # only held the status label, which left the whole content block
        # narrow with dead space on the right.
        container.columnconfigure(0, weight=1)
        # R41: vertical fill. The canvas window item only ever grew to the
        # content's natural height, so a taller window left dead space under
        # the status line (part of the "why is it so broken" look). The
        # table sections share the extra height between them.
        for row, weight in ((4, 2), (9, 2), (11, 2), (12, 1)):
            container.rowconfigure(row, weight=weight)
        for frame in (results_frame, downloads_frame, gofile_frame):
            frame.rowconfigure(0, weight=1)

    # ---- shared UI behavior -------------------------------------------------

    def on_clear_log(self) -> None:
        """Round R13: empty the log pane. A confirmation line is written
        afterwards so the pane is never left blank-silent."""
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.log_line("log cleared")

    def log_line(self, text: str) -> None:
        """Timestamped event line, newest at bottom, auto-scroll, bounded size."""
        stamp = time.strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{stamp}] {text}\n")
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > LOG_MAX_LINES:
            self.log.delete("1.0", f"{lines - LOG_MAX_LINES}.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_status(self, ok: bool, text: str) -> None:
        """Status line reflects the real current state; green when ok, red when not."""
        self.status.configure(text=text, foreground=Theme.OK if ok else Theme.BAD)

    def post_event(self, kind: str, payload: object) -> None:
        """Thread-safe: worker threads call this; the drain loop applies it."""
        self._events.put((kind, payload))

    # ---- R22c: top activity bar (mini Steam download menu) -----------------

    def _tick_progress(self) -> None:
        """One-second UI-thread tick: measure the active jobs, update the bar.
        Re-scheduled first thing so a spike in the work below cannot stall it."""
        if self._closing:
            return
        try:
            self._update_top_progress()
        except Exception:
            pass  # the bar is cosmetic; never let it take the app down
        try:
            self._gofile_schedule_tick()
        except Exception:
            pass  # R26b: the retry queue must never stall the tick either
        self.after(1000, self._tick_progress)

    def _download_progress_snapshot(self) -> list[dict]:
        """Bytes done/total for every record currently downloading.

        Files marked done count their full size; in-flight pieces are the
        on-disk size of their `.part-<file_id>` file (the engine writes each
        download there before it is finished). Pure disk/store reads, so it
        is safe on the UI thread."""
        jobs: list[dict] = []
        try:
            # R36 optimization: the flat status check first — the old code
            # deep-copied the whole store every second just to conclude
            # "nothing downloading".
            if not self.engine.store.has_downloading():
                return jobs
            records = self.engine.store.all()
        except Exception:
            return jobs
        for infohash, record in (records or {}).items():
            if record.get("direct"):
                continue
            if str(record.get("status") or "") != "downloading":
                continue
            files = record.get("files") or []
            if not files:
                continue
            folder = str(record.get("folder") or "")
            now = all_ = 0
            for f in files:
                size = int(f.get("size") or 0)
                all_ += size
                if f.get("done"):
                    now += size
                elif folder:
                    part = Path(folder) / f".part-{int(f.get('file_id') or 0)}"
                    try:
                        now += max(part.stat().st_size, 0)
                    except OSError:
                        pass
            if all_ > 0:
                jobs.append({"key": f"dl:{infohash}",
                             "name": str(record.get("name") or infohash),
                             "kind": "down",
                             "now": now, "all": all_})
        return jobs

    def _update_top_progress(self) -> None:
        """Recompute the header bar: aggregate percent, per-direction speeds,
        and a one-line description of what is moving."""
        now_t = time.monotonic()
        jobs = self._download_progress_snapshot()
        with self._upload_jobs_lock:
            for job in self._upload_jobs.values():
                jobs.append({"key": job.key, "name": job.name, "kind": "up",
                             "now": job.bytes_now(), "all": max(job.bytes_all, 1)})
        down_now = sum(j["now"] for j in jobs if j["kind"] == "down")
        down_all = sum(j["all"] for j in jobs if j["kind"] == "down")
        up_now = sum(j["now"] for j in jobs if j["kind"] == "up")
        up_all = sum(j["all"] for j in jobs if j["kind"] == "up")

        prev = self._progress_last
        dt = now_t - prev["t"] if prev["t"] else 0.0
        if dt > 0.2:   # real second has passed: instant speeds, EMA-smoothed
            inst_down = max(down_now - prev["down"], 0) / dt
            inst_up = max(up_now - prev["up"], 0) / dt
            prev["down_speed"] = inst_down if prev["down_speed"] <= 0 else (
                0.6 * inst_down + 0.4 * prev["down_speed"])
            prev["up_speed"] = inst_up if prev["up_speed"] <= 0 else (
                0.6 * inst_up + 0.4 * prev["up_speed"])
            prev["t"], prev["down"], prev["up"] = now_t, down_now, up_now

        parts: list[str] = []
        downs = [j for j in jobs if j["kind"] == "down"]
        ups = [j for j in jobs if j["kind"] == "up"]
        if len(jobs) == 1:
            # R22d: the route is spelled out (Torbox -> PC / PC -> GoFile)
            # and an ETA is shown whenever the speed is high enough to mean
            # anything.
            j = jobs[0]
            pct = int(j["now"] * 100 / j["all"]) if j["all"] else 0
            speed = prev["down_speed"] if j["kind"] == "down" else prev["up_speed"]
            arrow = "\u2193" if j["kind"] == "down" else "\u2191"
            route = ("Torbox \u2192 PC" if j["kind"] == "down"
                     else "PC \u2192 GoFile")
            parts.append(f"{arrow} {route} '{j['name'][:40]}' {pct}% "
                         f"· {_fmt_speed(speed)} of {human_size(j['all'])}")
            eta = _fmt_eta(j["all"] - j["now"], speed)
            if eta:
                parts.append(eta)
        elif jobs:
            if downs:
                parts.append(f"\u2193 {len(downs)} Torbox\u2192PC download"
                             + ("s" if len(downs) > 1 else ""))
            if ups:
                parts.append(f"\u2191 {len(ups)} PC\u2192GoFile upload"
                             + ("s" if len(ups) > 1 else ""))
            parts.append(f"{_fmt_speed(prev['down_speed'])} down "
                         f"· {_fmt_speed(prev['up_speed'])} up")
            moved, whole = down_now + up_now, down_all + up_all
            if whole:
                parts.append(f"{int(moved * 100 / whole)}% overall")
            # Overall ETA: everything still to move, over both directions.
            eta = _fmt_eta((down_all - down_now) + (up_all - up_now),
                           prev["down_speed"] + prev["up_speed"])
            if eta:
                parts.append(eta)
        text = "  ·  ".join(parts) if jobs else "No active jobs"
        # R22d: the label tint follows the bar's stage color so the
        # direction is readable at a glance even without reading the text.
        if not jobs:
            bar_style, label_fg = "ProgDown.Horizontal.TProgressbar", Theme.TEXT
        elif downs and ups:
            bar_style, label_fg = "ProgMixed.Horizontal.TProgressbar", Theme.TEXT
        elif downs:
            bar_style, label_fg = ("ProgDown.Horizontal.TProgressbar",
                                   Theme.ACCENT_BRIGHT)
        else:
            bar_style, label_fg = "ProgUp.Horizontal.TProgressbar", Theme.OK
        self._progress_label.configure(text=text, foreground=label_fg)
        whole_all = down_all + up_all
        moved_all = down_now + up_now
        self._progress_bar.configure(
            value=int(moved_all * 100 / whole_all) if whole_all else 0,
            style=bar_style)

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "log":
                    self.log_line(str(payload))
                elif kind == "status":
                    ok, text = payload
                    self.set_status(ok, text)
                elif kind == "search_started":
                    # A new search clears the table first so stale rows from
                    # an earlier search never linger.
                    self.results_tree.delete(*self.results_tree.get_children())
                    self._results_iids.clear()
                elif kind == "search_rows":
                    # Streaming search: rows arrive in batches and are
                    # APPENDED, not replacing what is already shown.
                    self._append_results(payload)
                elif kind == "download_added":
                    self._on_download_added(payload)
                elif kind == "downloads_changed":
                    self._on_downloads_changed(payload)
                elif kind == "gofile_done":
                    self._on_gofile_done(payload)
                elif kind == "gofile_expired":
                    self._on_gofile_expired(payload)
                elif kind == "unpack_done":
                    self._on_unpack_done(payload)
                elif kind == "remove_done":
                    self._on_remove_done(payload)
                elif kind == "remove_link_done":
                    self._on_remove_link_done(payload)
                elif kind == "gofile_scheduled":
                    # R26b: a GoFile job was parked, fired, or given up;
                    # repaint so the queued/scheduled state is visible.
                    self._on_gofile_scheduled(payload)
                elif kind == "gofile_storage_data":
                    self._on_gofile_storage_data(payload)
                elif kind == "gofile_storage_failed":
                    self._on_gofile_storage_failed(str(payload))
                elif kind == "gofile_storage_delete_done":
                    self._on_gofile_storage_delete_done(payload)
                elif kind == "gofile_repair_done":
                    self._on_gofile_repair_done(payload)
                elif kind == "torbox_all":
                    self._on_torbox_all(payload)
                elif kind == "torbox_translated":
                    self._on_torbox_translated(payload)
                elif kind == "plugin_list":
                    self._on_plugin_list(payload)
                elif kind == "torbox_link_upload":
                    # R21: the click-to-GoFile worker finished preparing the
                    # torrent; run the ordinary upload path on the UI thread.
                    self._start_upload(payload)
                elif kind == "torbox_link_done":
                    self._on_torbox_link_done(payload)
                elif kind == "links_table_refresh":
                    # R22: a direct-drop GoFile upload finished; repaint the
                    # links table so the new link shows up at once.
                    self._refresh_links_table()
                elif kind == "handoff_items":
                    # R36: magnets/.torrent files handed over by a second
                    # app instance (or this launch's own command line).
                    self._on_handoff_items(payload)
        except queue.Empty:
            pass
        self.after(100, self._drain)

    # ---- Torbox account search (right log half, R15/R16) ----------------------

    def on_torbox_search(self) -> None:
        """'Find' in the TORBOX FILES half: fetch the account's live mylist
        once into a local cache, then filter it by the query box and the
        category dropdown (R16). Empty query lists everything."""
        self.set_status(True, "Searching your Torbox account…")
        threading.Thread(target=self._torbox_search_worker,
                         daemon=True, name="torbox-search").start()

    def _torbox_search_worker(self) -> None:
        """Daemon: fetch mylist once and hand the RAW rows to the UI thread;
        all filtering (query text + category) happens on the UI thread so
        changing the category or query re-filters instantly, with no new
        API call. Rows are sorted NEWEST FIRST (R16b, user ask): latest
        addition to the account at the top."""
        try:
            torrents = self.engine.client.mylist() or []
        except Exception as exc:
            self.post_event("log", f"Torbox account search failed: {exc}")
            self.post_event("status", (False, "Torbox search failed"))
            return
        rows = [(t.name or "", t.status or "", int(t.created_at or 0),
                 int(t.size or 0), human_size(t.size or 0),
                 int(t.id or 0), (t.hash or "").strip().lower())
                for t in torrents]
        rows.sort(key=lambda r: (r[2], r[0].lower()), reverse=True)
        self.post_event("torbox_all", rows)

    def _on_torbox_all(self, rows: list) -> None:
        # Newest-first at the cache entry point (R16b): the worker pre-sorts,
        # but sorting here too keeps the cache order guaranteed whatever the
        # source, so the tree always shows the latest account additions on top.
        self._torbox_all = sorted(
            rows, key=lambda r: (r[2], r[0].lower()), reverse=True)
        self._apply_torbox_filter()
        self.set_status(True, "Ready")
        # R18: translation is automated — every fresh list load quietly
        # translates any titles the disk cache has not seen yet, so searching
        # in English just works with no button to press.
        self._torbox_auto_translate()

    def on_sort_torbox(self, col: str) -> None:
        """R18: a TORBOX FILES heading was clicked — sort the cached list by
        that column, flipping direction on repeated clicks (first click on
        Added/Size shows the newest/biggest first)."""
        if self._torbox_sort_col == col:
            self._torbox_sort_desc = not self._torbox_sort_desc
        else:
            self._torbox_sort_col = col
            self._torbox_sort_desc = col in ("added", "size")
        self._apply_torbox_filter()

    def _torbox_sort_key(self, row: tuple, col: str):
        """Sort value for one cached row: Added/Size numeric (0/‑1 sort as
        unknown-first ascending), Name/Status case-insensitive text."""
        name, status, created, size_raw, size_text = row[:5]
        if col == "added":
            return created if isinstance(created, int) and created > 0 else -1
        if col == "size":
            return size_raw if isinstance(size_raw, (int, float)) else -1
        if col == "status":
            return (status or "").lower()
        return (name or "").lower()

    def _torbox_english(self, name: str) -> str:
        """R17: the cached English title for a row, '' when none yet."""
        try:
            return self._torbox_en.get(name) or ""
        except Exception:
            return ""

    def _torbox_cat_matches(self, name: str) -> bool:
        """R16 category filter over the cached account list. The account
        carries no real categories, so this matches the words release
        groups and indexers put in names; 'All categories' matches all.
        R17: the English title counts too, so a foreign-language release
        still lands in its category. R18e: keywords match on word
        boundaries (so 'The Imitation Game' no longer counts as a game),
        and anything carrying a movie or TV marker (1080p, x264, BluRay,
        S01E07, ...) never counts as a game."""
        category = self.torbox_cat.get()
        keywords = TORBOX_CAT_KEYWORDS.get(category)
        if not keywords:
            return True
        low = name.lower()
        norm = re.sub(r"[._\-]+", " ", low)
        english = self._torbox_english(name).lower()
        enorm = re.sub(r"[._\-]+", " ", english) if english else ""
        # R18d/R18e: TV packs ("S01 Complete Repack") and movies with
        # game-flavoured words ("The Imitation Game 1080p") never show
        # under Games. Checked on the English title too.
        if category == "Games" and (_looks_like_media(low)
                                    or _looks_like_media(english)):
            return False
        # R18e: episode/season markers land in TV shows even when the
        # keyword list alone would miss them (S01E07-style names).
        if category == "TV shows" and (_looks_like_tv(low)
                                       or _looks_like_tv(english)):
            return True
        if _kw_match(norm, keywords):
            return True
        return bool(enorm) and _kw_match(enorm, keywords)

    def _apply_torbox_filter(self) -> None:
        """UI thread: filter the cached account rows by query + category,
        sort them, repaint the tree + count label. Never touches the network.
        R18: the query also matches the cached English title, and clicking a
        heading re-sorts; with no sort active the newest-first account order
        stands. R40: the Name column shows the cached English title when it
        has one (the original release string stays behind the row for
        actions and sorting), so the translation is visible again."""
        rows = self._torbox_all
        q = self.torbox_query.get().strip().lower()
        shown = []
        for row in rows:
            name, status, created, size_raw, size_text = row[:5]
            english = self._torbox_english(name)
            if q and q not in name.lower() and q not in english.lower():
                continue
            if not self._torbox_cat_matches(name):
                continue
            shown.append(row)
        if self._torbox_sort_col is not None:
            col, desc = self._torbox_sort_col, self._torbox_sort_desc
            shown.sort(key=lambda r: self._torbox_sort_key(r, col), reverse=desc)
        # Heading indicators.
        for c, base in self._torbox_base.items():
            text = base
            if c == self._torbox_sort_col:
                text += " ▼" if self._torbox_sort_desc else " ▲"
            self.torbox_tree.heading(
                c, text=text, anchor=self.torbox_tree.column(c, "anchor"))
        self.torbox_tree.delete(*self.torbox_tree.get_children())
        self._torbox_row_meta = {}
        for name, status, created, size_raw, size_text, torrent_id, infohash in shown:
            added = ""
            if created:
                try:
                    added = time.strftime("%Y-%m-%d", time.gmtime(created))
                except (ValueError, OverflowError, OSError):
                    added = ""
            # R40: paint the English title when the cache has one; the
            # row's actions still use the original `name` in the meta below.
            display = self._torbox_english(name) or name
            iid = self.torbox_tree.insert(
                "", "end", values=(display, added, size_text, status))
            # R21: remember which account torrent each painted row belongs to,
            # so clicking a row can adopt it, fetch it and upload it to GoFile.
            self._torbox_row_meta[iid] = (infohash, torrent_id, name)
        total = len(rows)
        if q or self.torbox_cat.get() != "All categories":
            self.torbox_count.configure(
                text=f"{len(shown)} of {total} torrents match")
        else:
            self.torbox_count.configure(text=f"{total} torrents in your account")

    def on_torbox_filter_changed(self) -> None:
        """R16 category dropdown: re-filter the cached list instantly. If
        the list was never fetched yet, fetch it first."""
        if not self._torbox_all:
            self.on_torbox_search()
            return
        self._apply_torbox_filter()

    def on_torbox_clear(self) -> None:
        """R16 'x' next to the TORBOX FILES search box: clear the query and
        category back to 'All categories' and show every cached torrent,
        without a new API call."""
        self.torbox_query.delete(0, "end")
        self.torbox_cat.current(0)
        if not self._torbox_all:
            self.on_torbox_search()
            return
        self._apply_torbox_filter()

    # ---- select-then-press actions (R22) -------------------------------------------

    def _remember_selection(self, origin: str) -> None:
        """R22 select-then-press: clicking a row in any table only REMEMBERS
        it. The Make GoFile link and Download buttons then act on the last
        remembered row, whichever table it lives in."""
        self._action_origin = origin

    def _origin_selection(self) -> tuple:
        """Resolve the remembered selection at press time: ("results",
        SearchItem), ("torbox", (infohash, torrent_id, name)) or
        ("downloads", infohash). (None, None) when nothing usable is
        selected (the table was cleared or sorted under the row, or the
        user never clicked a row)."""
        origin = self._action_origin
        if origin == "results":
            sel = self.results_tree.selection()
            if sel:
                item = self._results_iids.get(sel[0])
                if item is not None:
                    return ("results", item)
        elif origin == "torbox":
            sel = self.torbox_tree.selection()
            if sel:
                meta = self._torbox_row_meta.get(sel[0])
                if meta and meta[0]:
                    return ("torbox", meta)
        elif origin == "downloads":
            sel = self.downloads_tree.selection()
            if sel:
                infohash = self._download_iids.get(sel[0])
                if infohash:
                    return ("downloads", infohash)
        elif origin == "links":
            sel = self.gofile_tree.selection()
            if sel:
                node = self._gofile_nodes.get(sel[0]) or {}
                if node.get("infohash"):
                    return ("links", (str(node["infohash"]),
                                      str(node.get("name") or ""),
                                      str(node.get("state") or "")))
        return (None, None)

    def _start_torbox_link(self, infohash: str, name: str) -> None:
        """R22 starter shared by the torbox and downloads origins of
        'Make GoFile link': adopt into the store when needed, fetch to the
        PC when needed, then upload through the ordinary path."""
        if infohash in self._torbox_link_running:
            self.log_line(f"A GoFile link for '{name}' is already being "
                          "made; one at a time.")
            return
        self._torbox_link_running.add(infohash)
        self.log_line(f"Making a GoFile link for '{name}' (fetch from Torbox "
                      "to this PC first if needed, then upload)…")
        self.set_status(True, f"Linking '{name}'…")
        threading.Thread(target=self._torbox_link_worker,
                         args=(infohash, name),
                         daemon=True, name="torbox-link").start()

    def _start_result_link(self, item) -> None:
        """R22 starter for the results origin of 'Make GoFile link': the
        magnet is added to Torbox (or its existing record is found), fetched
        to the PC when it is ready, then uploaded — the full chain, as the
        user confirmed."""
        name = item.name or "search result"
        magnet = item.file_url or ""
        if not magnet.startswith("magnet:"):
            self.log_line(f"'{name}' is not a magnet link, so it cannot be "
                          "sent to Torbox from the results table.")
            return
        infohash = _infohash(magnet)
        if not infohash:
            self.log_line(f"'{name}' has no infohash; it cannot be linked.")
            return
        if infohash in self._torbox_link_running:
            self.log_line(f"A GoFile link for '{name}' is already being "
                          "made; one at a time.")
            return
        self._torbox_link_running.add(infohash)
        self.log_line(f"Making a GoFile link for '{name}' (add to Torbox, "
                      "fetch to this PC when it is ready, then upload)…")
        self.set_status(True, f"Linking '{name}'…")
        threading.Thread(target=self._result_link_worker,
                         args=(magnet, infohash, name),
                         daemon=True, name="result-link").start()

    def _result_link_worker(self, magnet: str, infohash: str,
                            name: str) -> None:
        """Daemon for R22 results-table clicks: make sure the store tracks
        the torrent (adding it when it is new), then hand straight to the
        R21 pipeline, which clears the in-flight guard itself in its finally
        block on every path."""
        try:
            try:
                known = self.engine.store.get(infohash)
            except Exception:
                known = None
            if known is None:
                try:
                    self.engine.add(magnet, name)
                except Exception as exc:
                    detail = str(exc) or type(exc).__name__
                    self.post_event("log", f"Adding '{name}' to Torbox "
                                    f"failed: {detail}")
                    self.post_event("status",
                                    (False, f"Linking '{name}' failed"))
                    return
            self._torbox_link_worker(infohash, name)
        except Exception as exc:
            detail = str(exc) or type(exc).__name__
            self.post_event("log", f"Making the GoFile link for '{name}' "
                            f"failed: {detail}")
            self.post_event("status", (False, f"Linking '{name}' failed"))
            self.post_event("torbox_link_done", infohash)

    @staticmethod
    def _torbox_caching_line(torrent) -> str:
        """One progress line for a torrent Torbox is still caching there for
        the first time, built from what mylist carries (state, percent,
        bytes done, speed). '' when nothing useful is known. R24 (user):
        the first-time caching can be slow and the app has to say so."""
        state = str(getattr(torrent, "status", "") or "")
        progress = float(getattr(torrent, "progress", 0.0) or 0.0)
        if 0.0 < progress <= 1.0:
            progress *= 100.0  # a fraction-shaped value: normalise to percent
        progress = max(0.0, min(progress, 100.0))
        speed = float(getattr(torrent, "download_speed", 0.0) or 0.0)
        size = int(getattr(torrent, "size", 0) or 0)
        parts = []
        if state:
            parts.append(state)
        if progress > 0.0:
            parts.append(f"{progress:.1f}%")
            if size > 0:
                parts.append(f"{human_size(progress / 100.0 * size)} of "
                             f"{human_size(size)}")
        if speed > 0.0:
            parts.append(f"{human_size(speed)}/s")
        return ", ".join(parts)

    def _direct_gofile_transfer(self, infohash: str, name: str,
                                torbox_id: int,
                                cancel: threading.Event) -> None:
        """R24: the DIRECT Torbox->GoFile cloud transfer, the default behind
        Make GoFile link. Torbox uploads the whole torrent to GoFile itself
        as one zip — the app's own GOFILE_API_TOKEN is passed per request
        (never anything from the Torbox dashboard) — and nothing is fetched
        to this PC. The job is polled every 5 s and every stage is logged
        ("preparing", then "uploading" with percent every 10 points), so a
        slow transfer is never silent. Stop (or closing the app) cancels
        ONLY the transfer job the app itself queued, and says so in the
        log; no torrent and no GoFile content already uploaded is touched.
        GoFile content that landed before the stop is left for the user to
        remove (Remove link / gofile.io). Raises on failure so the caller
        falls back to the fetch-to-PC + upload chain."""
        job_id = self.engine.client.queue_gofile_job(
            torbox_id, self.gofile.token, zip_all=True)
        self.post_event("log", f"Torbox is transferring '{name}' to GoFile "
                        f"directly (cloud job {job_id}, one zip, nothing "
                        "downloaded to this PC)…")
        deadline = time.monotonic() + DOWNLOAD_UNPACK_DEADLINE
        last_stage = ""
        last_band = -1
        while True:
            if self._closing or cancel.is_set():
                try:
                    self.engine.client.cancel_integration_job(job_id)
                    self.post_event("log", f"The '{name}' cloud transfer job "
                                    "was cancelled on Torbox (only that "
                                    "job; nothing else there was touched).")
                except Exception:
                    self.post_event("log", f"Could not cancel cloud transfer "
                                    f"job {job_id}; remove it on the Torbox "
                                    "dashboard if it stays listed.")
                raise _UploadStopped()
            if time.monotonic() >= deadline:
                raise RuntimeError("the cloud transfer did not finish "
                                   "within 30 minutes")
            time.sleep(5.0)
            job = self.engine.client.get_integration_job(job_id)
            stage = str(job.get("status") or "").lower()
            try:
                pct = int(float(job.get("progress")) * 100)
            except (TypeError, ValueError):
                pct = -1
            if stage == "completed":
                link = str(job.get("download_url") or "").strip()
                if not link:
                    raise RuntimeError("the cloud transfer finished without "
                                       "a share link")
                folder_id = None
                try:
                    # R25: the signed free-tier read turns the /d/ code into
                    # the folder UUID, so the link is deletable from here and
                    # browsable in GOFILE STORAGE. Best-effort: on a rate
                    # limit the record keeps working with the code alone.
                    folder_id = self.gofile.resolve_content_id(link)
                except Exception as exc:
                    self.post_event("log", f"Could not index '{name}'s "
                                    f"GoFile folder for the storage browser "
                                    f"({str(exc) or type(exc).__name__}); the "
                                    "link itself is unaffected.")
                if folder_id:
                    # R28: Torbox created this folder itself and named it
                    # with its own short id; give it the release name so
                    # GOFILE STORAGE reads sensibly. Best-effort: a rename
                    # failure never fails the transfer.
                    nice = _gofile_folder_name(name)
                    try:
                        if self.gofile.update_name(folder_id, nice):
                            self.post_event(
                                "log", f"Named '{name}'s GoFile folder "
                                f"'{nice}'.")
                        else:
                            self.post_event(
                                "log", f"Could not rename '{name}'s GoFile "
                                "folder; it keeps the name Torbox gave it.")
                    except Exception as exc:
                        self.post_event(
                            "log", f"Could not rename '{name}'s GoFile "
                            f"folder ({str(exc) or type(exc).__name__}).")
                self.engine.store.update(
                    infohash, gofile_link=link,
                    gofile_folder_id=folder_id,
                    gofile_created=_utc_now_iso(),
                    uploaded_at=time.strftime("%Y-%m-%dT%H:%M:%S",
                                              time.localtime()),
                    archived=False, gofile_removed_at=None)
                self.post_event("log", f"'{name}' is on GoFile, transferred "
                                "by Torbox itself (nothing was downloaded "
                                "to this PC).")
                self.post_event("gofile_done", (infohash, link, name))
                return
            if stage == "failed":
                raise RuntimeError("Torbox reported the cloud transfer failed")
            if stage and stage != last_stage:
                last_stage = stage
                if stage != "uploading" or pct < 0:
                    self.post_event("log", f"Cloud transfer of '{name}': "
                                    f"{stage}…")
            # "uploading": report every 10-percent band instead of every 5 s.
            if stage == "uploading" and pct >= 0 and pct // 10 > last_band:
                last_band = pct // 10
                self.post_event("log", f"Cloud transfer of '{name}': "
                                f"{pct}% uploaded.")

    def _torbox_link_worker(self, infohash: str, name: str,
                            upload: bool = True) -> None:
        """Daemon for R21/R22 linking: adopt the account torrent into the
        store (idempotent), wait for it to complete on Torbox if it is still
        downloading, wait for Torbox to list its files, release it to the
        PC, wait for the local fetch, then hand over to the ordinary
        'Make GoFile link' upload path on the UI thread. With upload=False
        (R22: the Download button on torbox/downloads rows) it stops after
        the local fetch. Every wait loop honours the app's Stop button via
        the infohash's cancel event. No link, token or API key is ever
        logged here."""
        cancel = self._cancel_event(infohash)
        try:
            try:
                record = self.engine.store.get(infohash) or {}
            except Exception:
                record = {}
            if upload and record.get("gofile_link"):
                self.post_event("log", f"'{name}' already has a GoFile link: "
                                f"{record['gofile_link']}")
                return
            # (1) Make sure the store tracks this torrent (no-op when it
            # already does, e.g. it was added through the app earlier).
            if record.get("status") not in ("complete", "held", "downloading",
                                            "failed", "unpacking", "unpacked",
                                            "adding"):
                torrent = self.engine.client.find_by_hash(infohash)
                if torrent is None:
                    verb = "linked" if upload else "downloaded"
                    self.post_event("log",
                                    f"'{name}' is no longer on your Torbox "
                                    f"account; it cannot be {verb}.")
                    return
                self.engine.adopt(torrent)
                record = self.engine.store.get(infohash) or {}
            # (2) Wait for Torbox to finish if it is still downloading there.
            # "unpacking"/"unpacked" pass through too: they are local states
            # and their folder is already on the PC (R22, for downloads-table
            # clicks). R24 (user): when Torbox has not cached the torrent yet
            # it is downloading it into the account first — stay quiet for
            # about a minute, then check what Torbox is doing and report
            # caching progress so the wait is never silent.
            deadline_at = time.monotonic() + DOWNLOAD_UNPACK_DEADLINE
            caching_notice = False
            quiet_until = time.monotonic() + 60.0
            next_tb_check = 0.0
            last_tb_line = ""
            while record.get("status") not in ("complete", "held", "failed",
                                               "unpacking", "unpacked"):
                if self._closing or cancel.is_set():
                    self.post_event("log", f"'{name}' was stopped. The torrent "
                                    "stays on Torbox and keeps caching there.")
                    return
                if time.monotonic() >= deadline_at:
                    verb = ("the link was not made" if upload
                            else "the download was not started")
                    self.post_event("log", f"'{name}' did not finish on Torbox "
                                    f"within 30 minutes; {verb}.")
                    self.post_event("torbox_link_done", infohash)
                    return
                if not caching_notice:
                    caching_notice = True
                    self.post_event("log", f"Torbox does not have '{name}' "
                                    "cached yet; it is downloading it into "
                                    "your account first.")
                time.sleep(DOWNLOAD_POLL_INTERVAL)
                record = self.engine.store.get(infohash) or {}
                if record.get("status") in ("complete", "held", "failed",
                                            "unpacking", "unpacked"):
                    break
                now = time.monotonic()
                # After the quiet minute: every 10 s ask Torbox what it is
                # doing with this torrent and report real progress. Stop
                # never touches this — it is Torbox-side work.
                if now >= quiet_until and now >= next_tb_check:
                    next_tb_check = now + 10.0
                    try:
                        torrent = self.engine.client.find_by_hash(infohash)
                    except Exception:
                        torrent = None
                    if torrent is not None:
                        line = self._torbox_caching_line(torrent)
                        if line and line != last_tb_line:
                            last_tb_line = line
                            self.post_event("log", f"Torbox: {line}")
            if record.get("status") == "failed":
                verb = ("the link was not made" if upload
                        else "the download was not started")
                self.post_event("log", f"'{name}' failed on Torbox; {verb}.")
                self.post_event("torbox_link_done", infohash)
                return
            # (2a) R24: try the DIRECT Torbox->GoFile transfer first (the
            # user's default). Torbox uploads the torrent itself to GoFile
            # as one zip; nothing is ever fetched to this PC and no local
            # copy is created, so there is nothing to clean up afterwards.
            # The token is GOFILE_API_TOKEN from .env, passed per request —
            # never anything stored on the Torbox dashboard. Any failure
            # falls through to the old fetch-to-PC + upload chain below.
            # A record the engine marked "failed" (its PC fetch failed)
            # keeps the old error here; press Download to re-fetch it.
            if upload and int(record.get("torbox_id") or 0):
                try:
                    self._direct_gofile_transfer(infohash, name,
                                                 int(record["torbox_id"]),
                                                 cancel)
                    return
                except _UploadStopped:
                    self.post_event("log", f"'{name}' was stopped.")
                    return
                except Exception as exc:
                    detail = str(exc) or type(exc).__name__
                    self.post_event("log", f"Direct Torbox->GoFile transfer "
                                    f"for '{name}' failed ({detail}); falling "
                                    "back to fetch-to-PC + upload.")
            needs_fetch = record.get("status") == "held" \
                or not record.get("folder")
            # (2b) R22: Torbox can mark a torrent "cached" BEFORE it has
            # listed the torrent's files — engine.release() then refuses with
            # "has no file list yet", which is the error the user hit. Wait
            # here and re-read the account until the file list appears, then
            # store it, so release() always has what it needs.
            if needs_fetch and not record.get("files"):
                self.post_event("log", f"Waiting for Torbox to list the files "
                                f"of '{name}'…")
                while not record.get("files"):
                    if self._closing or cancel.is_set():
                        self.post_event("log", f"'{name}' was stopped.")
                        return
                    if time.monotonic() >= deadline_at:
                        verb = ("the link was not made" if upload
                                else "the download was not started")
                        self.post_event(
                            "log", f"Torbox never listed the files of "
                            f"'{name}' within 30 minutes; {verb}.")
                        self.post_event("torbox_link_done", infohash)
                        return
                    time.sleep(DOWNLOAD_POLL_INTERVAL)
                    try:
                        torrent = self.engine.client.find_by_hash(infohash)
                    except Exception:
                        torrent = None
                    # Id 0 is a real Torbox file id (cached single-file
                    # torrents get it — requestdl accepts file_id=0), so no
                    # filtering here: the filter was the "bar shows nothing,
                    # bottom says Linking" bug of October 2026.
                    file_list = [
                        {"file_id": int(getattr(f, "file_id", 0) or 0),
                         "name": str(f.name or ""),
                         "size": int(f.size or 0), "done": False}
                        for f in (torrent.files if torrent else [])]
                    if file_list:
                        self.engine.store.update(infohash, files=file_list)
                        record = self.engine.store.get(infohash) or {}
                        self.post_event("log", f"Torbox listed {len(file_list)} "
                                        f"file(s) for '{name}'.")
            # (3) Release to the PC when the files are not here yet.
            if record.get("status") == "held" or not record.get("folder"):
                if self._closing or cancel.is_set():
                    self.post_event("log", f"'{name}' was stopped.")
                    return
                # R24: this link job is pulling the files down itself, so the
                # local copy goes away again once the upload succeeds. A
                # torrent the user pre-downloaded (folder already here when
                # the link was pressed) never enters this branch and is kept.
                if upload:
                    self._link_delete_after[infohash] = True
                self.post_event("log", f"Downloading '{name}' to this PC…")
                self.engine.release(infohash)
            # (4) Wait for the local fetch to finish (refresh() flips it to
            # "complete"; retries happen inside the engine).
            while record.get("status") not in ("complete", "unpacked"):
                if self._closing or cancel.is_set():
                    self.post_event("log", f"'{name}' was stopped.")
                    return
                if time.monotonic() >= deadline_at:
                    verb = ("the link was not made" if upload
                            else "the download did not finish")
                    self.post_event("log", f"'{name}' did not finish downloading "
                                    f"to this PC within 30 minutes; {verb}.")
                    self.post_event("torbox_link_done", infohash)
                    return
                time.sleep(DOWNLOAD_POLL_INTERVAL)
                record = self.engine.store.get(infohash) or {}
                if record.get("status") == "failed":
                    self.post_event("log", f"Downloading '{name}' failed; the "
                                    "link was not made. Try again later.")
                    self.post_event("torbox_link_done", infohash)
                    return
            if not upload:
                # (5, fetch-only) The Download button just wanted the files here.
                self.post_event("log", f"'{name}' is on this PC.")
                self.post_event("status", (True, "Ready"))
                return
            # (5) Hand over to the ordinary upload path on the UI thread.
            self.post_event("log", f"'{name}' is ready; uploading to GoFile…")
            self.post_event("torbox_link_upload", infohash)
        except Exception as exc:
            detail = str(exc) or type(exc).__name__
            self.post_event("log", f"Making the GoFile link for '{name}' "
                            f"failed: {detail}")
            self.post_event("status", (False, f"Linking '{name}' failed"))
        finally:
            self._cancel_forget(infohash)
            self.post_event("torbox_link_done", infohash)

    def _on_torbox_link_done(self, infohash: str) -> None:
        self._torbox_link_running.discard(infohash)
        self._cancel_forget(infohash)
        self.set_status(True, "Ready")

    # ---- R23: Stop button plumbing -------------------------------------------------

    def _cancel_event(self, key: str) -> threading.Event:
        """Get-or-create the cancel event for one in-flight job, keyed by
        infohash (link jobs, uploads, downloads) or a drop-... key (direct
        drops). Every cancellable worker grabs its event at start; the Stop
        button only sets the ones that already exist, so a stale event can
        never stop a future job."""
        with self._cancel_lock:
            event = self._cancel_events.get(key)
            if event is None:
                event = threading.Event()
                self._cancel_events[key] = event
            return event

    def _cancel_forget(self, key: str) -> None:
        """Drop a finished job's cancel event (its worker's finally)."""
        with self._cancel_lock:
            self._cancel_events.pop(key, None)

    def on_stop_pressed(self) -> None:
        """R23/R24 Stop, on the activity bar where the jobs it stops are
        shown: LOCAL-ONLY. One press ends the in-flight link jobs, GoFile
        uploads, and downloads to this PC (engine.cancel's own registry).
        Nothing on Torbox is ever deleted or cancelled by this button: a
        torrent still caching there keeps caching, and the cloud-transfer
        job a link worker queued is cancelled by that worker itself when it
        sees the cancel event (reported in the log)."""
        with self._cancel_lock:
            events = list(self._cancel_events.values())
        for event in events:
            event.set()
        names: list[str] = []
        try:
            for ih, rec in (self.engine.store.all() or {}).items():
                if rec.get("status") == "downloading":
                    self.engine.cancel(ih)
                    names.append(str(rec.get("name") or ih))
        except Exception:
            pass
        if names:
            self.log_line("Stop pressed: stopping "
                          + ", ".join(names[:3])
                          + ("…" if len(names) > 3 else "")
                          + ". Nothing on Torbox is touched.")
        elif events:
            self.log_line("Stop pressed: in-flight job(s) stopping; nothing "
                          "on Torbox is touched.")
        else:
            self.log_line("Stop pressed: nothing running.")
        self.set_status(True, "Ready")

    # ---- Torbox title translation (R17/R18) -------------------------------------

    def _torbox_auto_translate(self) -> None:
        """R18: the automated pass. After a list load, translate only the
        titles the disk cache has never seen; a pass already running wins,
        and an all-cached list starts nothing. Quiet: no log line on
        success, the search just starts matching in English."""
        if self._torbox_translating:
            return
        names = [row[0] for row in self._torbox_all
                 if row and row[0] and self._torbox_en.get(row[0]) is None]
        if not names:
            return
        self._start_torbox_translate(names, force=False, quiet=True)

    def on_settings_update_plugins(self) -> None:
        """R19: the manual forced plugin-update pass, from the settings
        popup — the same worker as the automatic startup pass, but it logs
        the outcome even when nothing changed."""
        self.log_line("Checking search plugins for updates (qBittorrent's "
                      "own update pass)…")
        threading.Thread(target=self._plugin_update_worker, args=(True,),
                         daemon=True, name="plugin-update-manual").start()

    def on_register_associations(self) -> None:
        """R36, from the settings popup: register the OS file associations
        so double-clicking a .torrent (or opening a magnet: link) hands it
        to the running app. Windows registry / Linux .desktop + xdg-mime;
        the worker thread keeps the UI free while the OS calls run."""
        self.set_status(True, "Registering file associations…")
        threading.Thread(target=self._register_associations_worker,
                         daemon=True, name="register-assoc").start()

    def _register_associations_worker(self) -> None:
        try:
            detail = handoff.register_associations()
        except Exception as exc:
            detail = f"failed: {str(exc) or type(exc).__name__}"
        self.post_event("log", f"File associations: {detail}")
        self.post_event("status", (True, "Ready"))

    def on_settings_translate(self) -> None:
        """R18: the manual forced pass, from the settings popup. Rebuilds
        the cache from scratch for every title in the loaded list, ignoring
        what it already knows — the 'just in case' path when the automated
        pass looks stuck or the cache looks wrong."""
        if not self._torbox_all:
            self.log_line("No Torbox list loaded yet: open TORBOX FILES "
                          "once, then run the forced translation.")
            return
        names = [row[0] for row in self._torbox_all if row and row[0]]
        self._start_torbox_translate(names, force=True, quiet=False)

    def _start_torbox_translate(self, names: list, force: bool,
                                quiet: bool) -> None:
        """Shared start for both passes: guard flag, status line, daemon."""
        if self._torbox_translating:
            if not quiet:
                self.log_line("A translation pass is already running; "
                              "wait for it to finish.")
            return
        self._torbox_translating = True
        self._torbox_translate_stop.clear()
        self.set_status(True, "Updating English search names…")
        threading.Thread(target=self._torbox_translate_worker,
                         args=(names, force, quiet), daemon=True,
                         name="torbox-translate").start()

    def _torbox_translate_worker(self, names: list, force: bool,
                                 quiet: bool) -> None:
        """Daemon: translate titles via warm_up; progress and the end signal
        go through the event queue so the UI thread repaints."""
        def progress(done: int, total: int) -> None:
            self.post_event("status",
                            (True, f"Updating English search names… {done}/{total}"))
        def done(failed: bool) -> None:
            self.post_event("torbox_translated", (failed, quiet))
        try:
            warm_up(names, self._torbox_en, progress=progress, done=done,
                    stop=self._torbox_translate_stop, force=force)
        except Exception as exc:
            self.post_event("log", f"Translation failed: {exc}")
            self.post_event("torbox_translated", (True, quiet))

    def _on_torbox_translated(self, payload: tuple) -> None:
        """UI thread, end of a translation pass: flush the cache to disk,
        repaint (filter/sort picks up new English matches), report. The
        automated pass stays quiet on success; a failure is always logged."""
        failed, quiet = payload
        self._torbox_translating = False
        self._torbox_en.save()
        self._apply_torbox_filter()
        self.set_status(True, "Ready")
        if failed:
            self.log_line("Translation stopped early: the translator kept "
                          "failing (it may be throttled). Titles already "
                          "done are saved; try Settings → Translate titles "
                          "now later for the rest.")
        elif not quiet:
            self.log_line("English search names rebuilt and cached on disk.")

    def _match_log_height(self) -> None:
        """R16: size the LOG pane's text to the same height as the TORBOX
        FILES pane (query row + tree + count label), so the two halves line
        up. One-shot after the window lays out."""
        try:
            self.update_idletasks()
            target_px = (self.torbox_tree.winfo_reqheight()
                         + self.torbox_query.winfo_reqheight() + 3
                         + self.torbox_count.winfo_reqheight() + 2)
            font = tkfont.Font(font=self.log.cget("font"))
            line_px = max(1, int(font.metrics("linespace")))
            self.log.configure(height=max(6, round(target_px / line_px)))
        except Exception:
            pass

    def _center_on_screen(self) -> None:
        """R18: move the window to the center of the screen (a third up from
        true center). Purely cosmetic; a failure never blocks anything."""
        try:
            self.update_idletasks()
            width = self.winfo_reqwidth()
            height = self.winfo_reqheight()
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            x = max(0, (screen_w - width) // 2)
            y = max(0, (screen_h - height) // 3)
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    # ---- drag-and-drop add (R15) ------------------------------------------------

    def _on_drop_files(self, event) -> None:
        """Drop onto the downloads section: add every .torrent found.

        event.data is a Tcl list of dropped paths; self.tk.splitlist() parses
        it safely (Windows paths contain spaces and braces). A dropped folder
        is scanned for *.torrent files. Each file is uploaded from a daemon
        worker via engine.add_torrent_file, mirroring the magnet add flow."""
        if not DND_AVAILABLE:
            self.log_line("Drag-and-drop unavailable: tkinterdnd2 is not installed.")
            return
        try:
            paths = list(self.tk.splitlist(event.data))
        except Exception as exc:
            self.log_line(f"Could not read the dropped items: {exc}")
            return
        torrent_paths: list = []
        gofile_paths: list = []
        folder_had_files = False
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                # A dropped folder contributes its .torrent files to Torbox;
                # other files inside folders are skipped (a folder can hold
                # thousands of files — dumping them all on GoFile unasked
                # would be a surprise).
                found = sorted(p for p in path.rglob("*.torrent") if p.is_file())
                torrent_paths.extend(found)
                folder_had_files = folder_had_files or any(path.iterdir())
            elif path.is_file() and path.suffix.lower() == ".torrent":
                torrent_paths.append(path)
            elif path.is_file():
                # R16, per the user's question: Torbox only accepts
                # torrents, so an .exe, .mp4 or any other file dropped here
                # is shared through GoFile instead — the app's other leg.
                gofile_paths.append(path)
        if folder_had_files and not torrent_paths:
            self.log_line("Folder drop: no .torrent files inside; other file "
                          "types are only shared when dropped directly.")
        if not torrent_paths and not gofile_paths:
            self.log_line("Drop ignored: nothing to add among the dropped items.")
            return
        self.set_status(True, f"Adding {len(torrent_paths) + len(gofile_paths)} "
                              "dropped item(s)…")
        for torrent_path in torrent_paths:
            self.log_line(f"Adding '{torrent_path.name}' to Torbox…")
            threading.Thread(target=self._drop_add_worker, args=(str(torrent_path),),
                             daemon=True, name=f"drop-add-{torrent_path.stem}").start()
        for file_path in gofile_paths:
            self.log_line(f"Uploading '{file_path.name}' to GoFile (Torbox "
                          "only accepts torrents)…")
            threading.Thread(target=self._gofile_drop_worker, args=(str(file_path),),
                             daemon=True, name=f"drop-gofile-{file_path.stem}").start()

    def _gofile_drop_worker(self, path: str) -> None:
        """Daemon: share one dropped non-torrent file through GoFile.

        Uploads into a GoFile folder named after the file (the same shape
        the download flow uses, so the share looks consistent) and logs the
        resulting gofile.io link. R22: the link is also recorded in the
        store under a "gofile-…" key, so direct drops show up in the GOFILE
        LINKS table like every other link (the 30-day TTL scheduler treats
        them like any other GoFile content). The link is safe to log: it
        carries no API key."""
        try:
            file_path = Path(path)
            folder = self.gofile.create_folder("root", file_path.stem)
            # R22c: the top activity bar tracks this upload too.
            # R23: the drop's cancel event uses the same drop-... key the
            # job accumulator uses, so the Stop button can end it.
            drop_key = "drop-" + uuid.uuid4().hex[:8]
            cancel = self._cancel_event(drop_key)
            job = _UploadJob(drop_key, file_path.name,
                             bytes_all=file_path.stat().st_size)

            def _drop_progress(sent: int, total: int) -> None:
                if cancel.is_set():
                    raise _UploadStopped()
                job.callback(str(file_path), sent, total)

            with self._upload_jobs_lock:
                self._upload_jobs[drop_key] = job
            try:
                result = self.gofile.upload_file(folder, str(file_path),
                                                 on_progress=_drop_progress)
                if cancel.is_set():
                    raise _UploadStopped()
            finally:
                with self._upload_jobs_lock:
                    self._upload_jobs.pop(drop_key, None)
                self._cancel_forget(drop_key)
            link = str((result or {}).get("downloadPage")
                       or (result or {}).get("link") or "").strip()
            if not link:
                raise GofileError("GoFile did not return a share link")
        except _UploadStopped:
            # R23 Stop: a deliberate stop is not an error.
            self.post_event("log", f"'{Path(path).name}' was stopped.")
            self.post_event("status", (True, "Ready"))
            return
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            self.post_event("log", f"GoFile upload of '{Path(path).name}' failed: {message}")
            self.post_event("status", (False, f"GoFile upload of {Path(path).name} failed"))
            return
        now = _utc_now_iso()
        # R22: record the direct drop in the store so the links table shows
        # it. "direct": True keeps it out of the DOWNLOADS table (there is
        # no torrent behind it); gofile_folder_id + gofile_created put it
        # under the same 30-day TTL cycle as the other links.
        self.engine.store.upsert({
            "infohash": "gofile-" + uuid.uuid4().hex[:12],
            "name": file_path.name,
            "magnet": "",
            "torbox_id": 0,
            "status": "complete",
            "folder": str(file_path),   # R22b: the original file, so an
                                        # archived drop can be re-linked
            "files": [],
            "created_at": now,
            "gofile_link": link,
            "gofile_folder_id": str(folder) if folder else None,
            "gofile_created": now,
            "unpack_dest": "",
            "unpacked": False,
            "uploaded_at": now,
            "archived": False,
            "archived_at": None,
            "direct": True,
        })
        self.post_event("links_table_refresh", None)
        self.post_event("log", f"GoFile link for '{Path(path).name}': {link}")
        self.post_event("status", (True, "GoFile link ready"))

    def _drop_add_worker(self, path: str) -> None:
        """Daemon: upload one dropped .torrent file to the Torbox account."""
        try:
            infohash = self.engine.add_torrent_file(path)
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            self.post_event("log", f"Could not add '{Path(path).name}': {message}")
            self.post_event("status", (False, f"Adding {Path(path).name} failed"))
            return
        self.post_event("download_added", (infohash, Path(path).stem))

    # ---- add link row (R16) ------------------------------------------------------

    def on_add_link(self) -> None:
        """'Add' in the ADD LINK row (R16). Scope decided by the user's
        'your call':
        - magnet: URI      -> straight to Torbox, like a search download.
        - URL ending .torrent -> fetched to disk, then the .torrent file
          upload path (engine.add_torrent_file) runs.
        - any other http(s) URL -> downloaded to downloads/_links/ and
          shared through GoFile (same leg as a dropped .exe/.mp4).
        Everything runs from daemon workers; the UI never blocks."""
        link = self.link_entry.get().strip()
        if not link:
            self.log_line("Link box is empty; nothing to add.")
            return
        low = link.lower()
        if low.startswith("magnet:"):
            name = _magnet_display_name(link)
            self.log_line(f"Adding magnet '{name}' to Torbox…")
            self.set_status(True, "Adding magnet to Torbox…")
            threading.Thread(target=self._add_worker, args=(link, name),
                             daemon=True, name="link-magnet").start()
        elif low.startswith(("http://", "https://")) \
                and low.split("?", 1)[0].endswith(".torrent"):
            name = _url_filename(link)
            self.log_line(f"Fetching '{name}' and adding it to Torbox…")
            self.set_status(True, "Fetching .torrent from link…")
            threading.Thread(target=self._link_torrent_worker, args=(link, name),
                             daemon=True, name="link-torrent").start()
        elif low.startswith(("http://", "https://")):
            name = _url_filename(link)
            self.log_line(f"Downloading '{name}' from the link, then sharing "
                          "it on GoFile (Torbox only accepts torrents)…")
            self.set_status(True, f"Downloading {name}…")
            threading.Thread(target=self._link_gofile_worker, args=(link,),
                             daemon=True, name="link-gofile").start()
        else:
            self.log_line("Not a magnet or http(s) link; nothing to add.")
            return
        self.link_entry.delete(0, "end")

    # ---- browse add (R18) --------------------------------------------------------

    def on_gofile_add_file(self) -> None:
        """'Add file' in the GOFILE title row (R34). Pick one or more files
        from disk with the OS dialog; each one is shared through GoFile via
        the same worker a dropped file takes, so it lands in its own folder
        named after it, records a link row, and shows live upload progress.
        Runs from daemon workers; the UI thread never blocks."""
        paths = filedialog.askopenfilenames(
            parent=self, title="Add files to GoFile")
        if not paths:
            return
        self.set_status(True, f"Adding {len(paths)} file(s) to GoFile…")
        for raw in paths:
            path = Path(raw)
            self.log_line(f"Uploading '{path.name}' to GoFile…")
            threading.Thread(target=self._gofile_drop_worker, args=(str(path),),
                             daemon=True, name=f"pick-gofile-{path.stem}").start()

    def on_browse_files(self) -> None:
        """'File' button next to Add: pick one or more files with the OS
        dialog. Routing mirrors the drop rules exactly: a .torrent goes to
        Torbox, any other file is shared through GoFile."""
        paths = filedialog.askopenfilenames(
            parent=self, title="Add files",
            filetypes=[("Torrent files", "*.torrent"), ("All files", "*")])
        if not paths:
            return
        self._add_picked_paths(paths)

    def on_browse_folder(self) -> None:
        """'Folder' button next to Add: pick a folder; every .torrent inside
        it (recursively) is added to Torbox, like a dropped folder."""
        folder = filedialog.askdirectory(parent=self, title="Add a folder")
        if not folder:
            return
        self._add_picked_paths([folder])

    def _add_picked_paths(self, paths) -> None:
        """Shared routing for the File/Folder buttons, line for line the
        same rules as _on_drop_files, minus the drop-event parsing."""
        torrent_paths: list = []
        gofile_paths: list = []
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                torrent_paths.extend(
                    sorted(p for p in path.rglob("*.torrent") if p.is_file()))
            elif path.suffix.lower() == ".torrent":
                torrent_paths.append(path)
            else:
                gofile_paths.append(path)
        if not torrent_paths and not gofile_paths:
            self.log_line("Nothing to add (folders are scanned for .torrent "
                          "files; other file types go to GoFile).")
            return
        self.set_status(True, f"Adding {len(torrent_paths) + len(gofile_paths)} "
                              "picked item(s)…")
        for torrent_path in torrent_paths:
            self.log_line(f"Adding '{torrent_path.name}' to Torbox…")
            threading.Thread(target=self._drop_add_worker,
                             args=(str(torrent_path),), daemon=True,
                             name=f"pick-add-{torrent_path.stem}").start()
        for file_path in gofile_paths:
            self.log_line(f"Uploading '{file_path.name}' to GoFile (Torbox "
                          "only accepts torrents)…")
            threading.Thread(target=self._gofile_drop_worker,
                             args=(str(file_path),), daemon=True,
                             name=f"pick-gofile-{file_path.stem}").start()

    def _link_torrent_worker(self, link: str, name: str) -> None:
        """Daemon: fetch a .torrent URL, run the same file-upload path a
        dropped .torrent uses, then delete the fetched file."""
        tmp = ROOT / "downloads" / "_links" / (name if name.endswith(".torrent")
                                               else name + ".torrent")
        try:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            _fetch_url_to(link, tmp)
            infohash = self.engine.add_torrent_file(str(tmp), name=name)
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            self.post_event("log", f"Could not add the .torrent link: {message}")
            self.post_event("status", (False, "Adding the .torrent link failed"))
            return
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
        self.post_event("download_added", (infohash, name))

    def _link_gofile_worker(self, link: str) -> None:
        """Daemon: download the pasted URL's file to downloads/_links/ and
        hand it to the GoFile drop worker (folder + upload + link log)."""
        name = _url_filename(link)
        dest = ROOT / "downloads" / "_links" / name
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            _fetch_url_to(link, dest)
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            self.post_event("log", f"Could not download the link: {message}")
            self.post_event("status", (False, "Downloading the link failed"))
            return
        self.post_event("log", f"Downloaded '{name}'; uploading to GoFile…")
        self._gofile_drop_worker(str(dest))

    # ---- selection helpers ---------------------------------------------------

    def _selected_record(self) -> dict | None:
        """The store record of the selected downloads row, or None."""
        sel = self.downloads_tree.selection()
        if not sel:
            return None
        infohash = self._download_iids.get(sel[0])
        if not infohash:
            return None
        return self.engine.store.get(infohash)

    def _selected_infohash(self) -> str:
        sel = self.downloads_tree.selection()
        return self._download_iids.get(sel[0], "") if sel else ""

    # R24: _update_link_label is gone with the stray link label it fed.

    # ---- downloads table -------------------------------------------------------

    @staticmethod
    def _status_display(status: str) -> str:
        """How a record's status reads in the table (held explains itself)."""
        if status == "held":
            return "held (on Torbox)"
        return status

    def _refresh_downloads_table(self) -> None:
        """Rebuild the downloads table from the store (small; bounded).

        R22b: the table lists every non-direct record, archived ones
        included; an archived row's status cell reads "archived <YYYY-MM-DD>"
        (from gofile_removed_at) or plain "archived", and its Link cell is
        empty (the link was cleared when the content expired). Reinstating
        expired links happens in the GOFILE table, not here."""
        records = self.engine.store.all()
        previous = self._selected_infohash()
        self.downloads_tree.delete(*self.downloads_tree.get_children())
        self._download_iids.clear()
        for infohash, record in records.items():
            # R22: direct drops (files sent straight to GoFile, never a
            # torrent) live only in the links table, not in DOWNLOADS.
            if record.get("direct"):
                continue
            folder = str(record.get("folder") or "")
            try:
                has_local = bool(folder) and Path(folder).is_dir()
            except OSError:
                has_local = False
            # R28 (user: "just move this to the link table"): a record whose
            # only remaining piece is its GoFile link shows in GOFILE
            # alone, not here. Active work, queued retries and anything with
            # local files still show; Torbox-only records keep showing too.
            if (record.get("gofile_link") and not has_local
                    and infohash not in self._gofile_scheduled
                    and (record.get("status") or "")
                    not in ("adding", "downloading")):
                continue
            if record.get("archived") and not has_local:
                # archived with no files left on disk: DOWNLOADS has nothing
                # left to do with it, and it already shows in GOFILE.
                continue
            is_archived = bool(record.get("archived"))
            files = record.get("files") or []
            done = sum(1 for f in files if f.get("done"))
            if is_archived:
                status = self._archived_status_text(record)
                where = ""
            else:
                # R26b: a job parked on the GoFile retry queue wears its
                # queued state, whatever the underlying record status is.
                sched = self._gofile_scheduled.get(infohash)
                if sched is not None:
                    retry_at = time.strftime(
                        "%H:%M", time.localtime(float(sched.get("due") or 0)))
                    status = (f"queued for GoFile "
                              f"(retry {retry_at})")
                else:
                    status = self._status_display(record.get("status") or "adding")
                # R24 (user: "This doesn't tell me if its on my computer or
                # not"): the Where column answers exactly that. Links are
                # shown only in the GOFILE table at the bottom.
                if has_local:
                    where = "On PC"
                elif record.get("gofile_link"):
                    where = "GoFile only"
                else:
                    where = "Torbox only"
            iid = self.downloads_tree.insert("", "end", values=(
                record.get("name") or infohash or "download",
                status,
                f"{done}/{len(files)}",
                where,
            ))
            self._download_iids[iid] = infohash
        if previous:
            for iid, infohash in self._download_iids.items():
                if infohash == previous:
                    self.downloads_tree.selection_set(iid)
                    self.downloads_tree.see(iid)
                    break
        # R22: keep the GOFILE section in step with the store.
        self._refresh_links_table()

    def _record_state(self, infohash: str, record: dict) -> str:
        """The State cell for a record with a link (R26b aware): the queued
        retry time when a check is scheduled, 'live' otherwise."""
        sched = self._gofile_scheduled.get(infohash)
        if sched is not None:
            retry_at = time.strftime(
                "%H:%M", time.localtime(float(sched.get("due") or 0)))
            return f"queued for GoFile (retry {retry_at})"
        return "live" if record.get("gofile_link") else ""

    def _paint_gofile_merged(self, children: dict, cached: bool = False,
                             fetched: str = "") -> None:
        """R32: the ONE painter of the merged GOFILE section. Storage
        children get the tree treatment (R31: folders go in closed, their
        children load lazily under their own row) plus the old links
        table's cells: Link (the folder's public page), State and Added
        from its store record, 'live' when the account has a folder the
        store never knew about. Records whose folder is NOT in this
        listing — rate-limited checks, archived rows — are appended as
        link-only rows so nothing vanishes before a real check (the R26/R27
        persistence rule, now merged). Never raises into the caller."""
        self.gofile_tree.delete(*self.gofile_tree.get_children())
        self._gofile_nodes = {}
        self._gofile_pending = {}
        try:
            records = self.engine.store.all()
        except Exception:
            records = {}
        by_id: dict = {}
        by_code: dict = {}
        for infohash, record in records.items():
            fid = str(record.get("gofile_folder_id") or "")
            if fid:
                by_id[fid] = (infohash, record)
            link = str(record.get("gofile_link") or "")
            if "/d/" in link:
                by_code.setdefault(link.rsplit("/d/", 1)[1].strip("/"),
                                   (infohash, record))
        seen_ids: set = set()
        seen_codes: set = set()
        entries = list((children or {}).values())
        entries.sort(key=lambda c: (c.get("type") != "folder",
                                    str(c.get("name") or "").lower()))
        for child in entries:
            cid = str(child.get("id") or "")
            code = str(child.get("code") or "").strip()
            seen_ids.add(cid)
            if code:
                seen_codes.add(code)
            match = by_id.get(cid) or by_code.get(code) or ("", None)
            infohash, record = match
            link = f"https://gofile.io/d/{code}" if code else ""
            state = ""
            added = ""
            if record is not None:
                link = str(record.get("gofile_link") or link)
                if link or record.get("archived"):
                    state = self._record_state(infohash, record)
                when = str(record.get("uploaded_at")
                           or record.get("gofile_created") or "")
                added = when.replace("T", " ")[:10]
            elif child.get("type") == "folder":
                state = "live"
            if not added:
                created = child.get("created")
                if isinstance(created, (int, float)) and created > 0:
                    added = time.strftime(
                        "%Y-%m-%d", time.localtime(float(created)))
            name = str(child.get("name") or cid or "")
            iid = self.gofile_tree.insert(
                "", "end", text=name, open=False,
                values=(link, state, added))
            node = dict(child)
            node["name"] = name
            node["infohash"] = infohash
            node["state"] = state
            node["link"] = link
            self._gofile_nodes[iid] = node
        for infohash, record in records.items():
            fid = str(record.get("gofile_folder_id") or "")
            link = str(record.get("gofile_link") or "")
            code = (link.rsplit("/d/", 1)[1].strip("/")
                    if "/d/" in link else "")
            if (fid and fid in seen_ids) or (code and code in seen_codes):
                continue
            if not link and not record.get("archived"):
                continue
            name = str(record.get("name") or infohash or "")
            state = (self._record_state(infohash, record) if link
                     else self._archived_status_text(record))
            when = str(record.get("uploaded_at")
                       or record.get("gofile_created") or "")
            iid = self.gofile_tree.insert(
                "", "end", text=name, open=False,
                values=(link, state, when.replace("T", " ")[:10]))
            self._gofile_nodes[iid] = {
                "id": fid, "type": "link", "name": name, "link": link,
                "code": code, "infohash": infohash, "state": state}
        crumbs = "My storage"
        if cached:
            when_txt = (fetched or "").replace("T", " ")[:16] or "earlier"
            crumbs += f"   (cached {when_txt} — press Refresh to check)"
        self._gofile_crumbs_base = crumbs
        self.gofile_crumbs.configure(text=crumbs)

    def _refresh_links_table(self) -> None:
        """R32: the merged GOFILE section's Link/State cells come from the
        store, so every place that used to repaint the links table now
        repaints the merged tree from the last known root listing (the
        cache — zero GoFile requests) with those cells re-applied. Rows
        persist until a real check says otherwise, as before. Skipped
        while a live refresh is in flight so the loading hint stays up."""
        if self._gofile_loading:
            return
        root_id = str(self._gofile_root_id
                      or self._gofile_cache.get("root_id") or "")
        cached = (self._gofile_cache.get("listings") or {}).get(root_id)
        children: dict = {}
        fetched = ""
        if isinstance(cached, dict) and isinstance(cached.get("data"), dict):
            raw = cached["data"].get("children")
            if isinstance(raw, dict):
                children = raw
            fetched = str(cached.get("fetched") or "")
        self._paint_gofile_merged(children, cached=True, fetched=fetched)

    @staticmethod
    def _archived_status_text(record: dict) -> str:
        """Status cell for an archived row: 'archived <YYYY-MM-DD>' when the
        removal date is known (first 10 chars of the ISO timestamp), plain
        'archived' otherwise (old records predate gofile_removed_at)."""
        removed = str(record.get("gofile_removed_at") or "").strip()
        if removed:
            return f"archived {removed[:10]}"
        return "archived"

    @staticmethod
    def _open_local_folder(path: str) -> None:
        """Open a local folder in the OS file manager (Explorer on Windows).
        Never raises into the caller; a failure is reported by the caller."""
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - Windows shell open, path from the store
        else:
            subprocess.Popen(["xdg-open", path])

    # ---- GoFile storage browser (R25, right half of the bottom split) ----
    # ---- R27: on-disk persistence for its listings ----------------------

    def _gofile_cache_load(self) -> None:
        """Read gofile_storage_cache.json into memory. Missing or corrupt
        cache = empty; the app then behaves like the first-ever load."""
        try:
            raw = json.loads(self._gofile_cache_path.read_text(
                encoding="utf-8"))
            if isinstance(raw, dict):
                self._gofile_cache = raw
        except (OSError, ValueError):
            self._gofile_cache = {}

    def _gofile_cache_save(self) -> None:
        """Atomically write the cache next to the download store. A failure
        is logged and otherwise ignored — the cache must never take the
        app down or slow a paint."""
        try:
            self._gofile_cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._gofile_cache_path.with_name(
                self._gofile_cache_path.name + ".tmp")
            tmp.write_text(json.dumps(self._gofile_cache), encoding="utf-8")
            os.replace(tmp, self._gofile_cache_path)
        except Exception as exc:
            self.post_event("log", f"GoFile storage cache write failed: "
                            f"{exc or type(exc).__name__}")

    def _gofile_cache_put(self, data: dict) -> None:
        """Remember one successful GET /contents reply (per folder id),
        newest last; keep at most the 40 most recently visited folders."""
        cid = str(data.get("id") or "")
        if not cid:
            return
        listings = self._gofile_cache.setdefault("listings", {})
        listings.pop(cid, None)
        listings[cid] = {"data": data,
                         "fetched": _utc_now_iso()}
        while len(listings) > 40:
            oldest = next(iter(listings))
            listings.pop(oldest, None)
        self._gofile_cache_save()

    def _gofile_cache_drop(self, ids: list[str]) -> None:
        """Forget cached listings for deleted content ids (a delete that
        succeeded server-side should not keep coming back from disk)."""
        listings = self._gofile_cache.get("listings") or {}
        for i in ids:
            listings.pop(str(i), None)
        self._gofile_cache_save()

    def _gofile_startup_restore(self) -> None:
        """Startup: paint the account root from the cache — zero GoFile
        requests. Nothing cached: fall back to the old one-time live load
        (which also bootstraps the cache). R31: with inline expansion there
        is no visited-folder trail; the table always starts at the root and
        folders open under themselves when expanded."""
        listings = self._gofile_cache.get("listings") or {}
        cached = listings.get(str(self._gofile_root_id or ""))
        if not cached:
            self.on_gofile_storage_refresh(show_errors=False)
        else:
            self._paint_gofile_storage(cached["data"], cached=True,
                                       fetched=str(cached.get("fetched") or ""))
        # R29: one-shot repair of folders that got Torbox's short ids from
        # direct transfers made before the transfer-time rename existed.
        threading.Thread(target=self._gofile_rename_backlog_worker,
                         daemon=True, name="gofile-rename-backlog").start()

    def _gofile_rename_backlog_worker(self) -> None:
        """Daemon, once per startup, two passes.
        Pass 1: every store record that remembers its GoFile folder id gets
        one best-effort PUT rename to the release name. A folder already
        named right costs one harmless call; a gone folder just fails and is
        skipped, and the next startup tries again.
        Pass 2 (R30): folders the store never knew about — the reason R29's
        repair missed this machine's three (the store here is empty). A
        folder GoFile created without a name wears its own short code as its
        name, so name == code is the never-named signature; each one is read
        once and, when it holds a single file, renamed after that file
        (extension and any .partN tail stripped, then sanitized). Folders
        with several children are left alone. The R26 limiter throttles
        every call like the rest of the app."""
        renamed, tried = [], 0
        try:
            records = self.engine.store.all() or {}
        except Exception:
            records = {}
        for _ih, record in records.items():
            folder_id = str(record.get("gofile_folder_id") or "")
            name = str(record.get("name") or "").strip()
            if not folder_id or not name:
                continue
            tried += 1
            try:
                if self.gofile.update_name(folder_id, name):
                    renamed.append(folder_id)
            except Exception:
                pass
        # Pass 2: never-named folders, read from the account root itself.
        try:
            root_id = str(self.gofile.get_root_folder() or "")
        except Exception:
            root_id = ""
        if root_id:
            root = None
            cached = (self._gofile_cache.get("listings") or {}).get(root_id)
            if isinstance(cached, dict) and isinstance(cached.get("data"),
                                                       dict):
                root = cached["data"]
            else:
                try:
                    root = self.gofile.get_content(root_id)
                except Exception:
                    root = None
            children = (root or {}).get("children")
            if isinstance(children, dict):
                for child in children.values():
                    if (child.get("type") != "folder"
                            or str(child.get("name") or "")
                            != str(child.get("code") or "")):
                        continue
                    fid = str(child.get("id") or "")
                    tried += 1
                    try:
                        data = self.gofile.get_content(fid)
                    except Exception:
                        continue
                    if not isinstance(data, dict):
                        continue
                    kids = data.get("children")
                    if not isinstance(kids, dict) or not kids:
                        continue   # nothing inside to name it after
                    # R31: one file keeps the old rule (name after the
                    # file, extension and .partN tail off); several
                    # files share their common prefix (multi-part
                    # archives collapse first, then movie+info and
                    # image+update pairs reduce to the shared title) —
                    # the user's "pinpoint the game or movie" ask.
                    file_names = [str(k.get("name") or "")
                                  for k in kids.values()
                                  if k.get("type") == "file"]
                    if len(file_names) == 1:
                        nice = _gofile_folder_name(
                            _name_from_file(file_names[0]))
                    else:
                        nice = _gofile_folder_name(
                            _common_name_from_files(file_names))
                    # "upload" would be a downgrade from the code: a
                    # folder whose name we could not work out stays put.
                    if not nice or nice == "upload":
                        continue
                    try:
                        if self.gofile.update_name(fid, nice):
                            renamed.append(fid)
                    except Exception:
                        pass
        if renamed:
            self._gofile_cache_drop(renamed)
            self.post_event("gofile_repair_done", (len(renamed), tried))

    def _on_gofile_repair_done(self, payload: tuple) -> None:
        renamed, tried = payload
        self.log_line(f"Renamed {renamed} of {tried} unnamed GoFile folders; "
                      "GOFILE is refreshing.")
        self.on_gofile_storage_refresh(show_errors=False)

    def _insert_gofile_children(self, parent_iid: str, children) -> None:
        """Insert one folder's children (folders first, then files, each
        alphabetically) under parent_iid — top level for the root, INLINE
        under the folder's own row when it expands (R31). Folder rows go in
        closed; the arrow or one click loads or reveals their children."""
        entries = list((children or {}).values())
        entries.sort(key=lambda c: (c.get("type") != "folder",
                                    str(c.get("name") or "").lower()))
        for child in entries:
            iid = self.gofile_tree.insert(
                parent_iid, "end",
                text=str(child.get("name") or child.get("id") or ""),
                open=False)
            self._gofile_nodes[iid] = child

    def _paint_gofile_storage(self, data: dict, cached: bool = False,
                              fetched: str = "") -> None:
        """UI thread: paint the ROOT of the storage tree from one
        GET /contents reply (live or cached). Folders go in closed; their
        children load lazily under their own row on expansion (R31), so the
        table never navigates away. The crumbs line says which, so a stale
        view is always identifiable at a glance."""
        self._gofile_loading = False
        self._gofile_cached_view = cached
        node_id = str(data.get("id") or "")
        if node_id:
            self._gofile_root_id = node_id
            self._gofile_cache["root_id"] = node_id
        children = data.get("children")
        if not isinstance(children, dict):
            children = {}
        self.gofile_tree.delete(*self.gofile_tree.get_children())
        self._gofile_nodes = {}
        self._gofile_pending = {}
        self._insert_gofile_children("", children)
        crumbs = "My storage"
        if cached:
            when = (fetched or "").replace("T", " ")[:16] or "earlier"
            crumbs += f"   (cached {when} — press Refresh to check)"
        self._gofile_crumbs_base = crumbs
        self.gofile_crumbs.configure(text=crumbs)

    def on_gofile_storage_refresh(self, show_errors: bool = True) -> None:
        """Refresh: reload the account ROOT (R31: the table always shows
        the root; folders expand inline under their own rows). Runs on a
        daemon thread; the result comes back through the event queue."""
        if self._gofile_loading:
            return
        content_id = str(self._gofile_root_id or "")
        if not content_id:
            # First load (or the root id was never resolved): resolve the
            # account root from the configured token.
            try:
                content_id = self.gofile.get_root_folder()
            except Exception as exc:
                self.gofile_crumbs.configure(text="(not loaded — press Refresh)")
                self.log_line(f"GoFile storage: could not reach the account "
                              f"root ({exc or type(exc).__name__}).")
                if show_errors:
                    self.set_status(False, "GoFile storage not loaded")
                return
            self._gofile_root_id = content_id
            self._gofile_cache["root_id"] = content_id
        self._gofile_loading = True
        self.gofile_crumbs.configure(text="loading My storage…")
        threading.Thread(target=self._gofile_storage_worker,
                         args=(content_id,), daemon=True,
                         name="gofile-storage").start()

    AUTO_REFRESH_INTERVAL_MS = 30 * 60 * 1000

    def _auto_refresh_tables(self) -> None:
        """R43 (user ask): refresh TORBOX FILES and GOFILE automatically —
        once shortly after startup, then every half hour while the window
        is open. The gofile pass runs quiet (show_errors=False) so a
        background miss or rate limit never nags the user; a manual press
        still reports normally. Reschedules itself until the app closes."""
        if self._closing:
            return
        try:
            if self.config.has("TORBOX_API_KEY"):
                self.on_torbox_search()
            if self.config.has("GOFILE_API_TOKEN"):
                self.on_gofile_storage_refresh(show_errors=False)
        except Exception:
            pass
        self.after(self.AUTO_REFRESH_INTERVAL_MS, self._auto_refresh_tables)

    def _gofile_storage_worker(self, content_id: str) -> None:
        """Daemon: one signed free-tier read of a folder's contents."""
        try:
            data = self.gofile.get_content(content_id)
            self.post_event("gofile_storage_data", data)
        except Exception as exc:
            self.post_event("gofile_storage_failed",
                            str(exc) or type(exc).__name__)

    def _on_gofile_storage_data(self, data: dict) -> None:
        """UI thread: a live GET /contents reply arrived — cache it, then
        route it (R31). When it answers a pending inline expansion the
        children slide under that folder's own row; anything else is a root
        paint (which is what makes checked-away entries disappear)."""
        self._gofile_cache_put(data)
        cid = str((data or {}).get("id") or "")
        iid = self._gofile_pending.pop(cid, None)
        if iid is not None:
            kids = (data or {}).get("children")
            self._insert_gofile_children(
                iid, kids if isinstance(kids, dict) else {})
            try:
                self.gofile_tree.item(iid, open=True)
            except Exception:
                pass
            if not self._gofile_pending:
                self.gofile_crumbs.configure(text=self._gofile_crumbs_base)
            return
        self._paint_gofile_storage(data, cached=False)

    def _on_gofile_storage_failed(self, message: str) -> None:
        self._gofile_loading = False
        self._gofile_pending = {}
        # R27 (user: entries "only disappear after being checked again"):
        # a failed check never wipes the table — whatever was on screen
        # simply stays, with the crumbs saying the check failed (R31: an
        # interrupted expansion restores the line it had before it too).
        if self._gofile_crumbs_base and self.gofile_tree.get_children():
            self.gofile_crumbs.configure(
                text=f"{self._gofile_crumbs_base} "
                     "(check failed — press Refresh)")
        else:
            self.gofile_crumbs.configure(text="(load failed — press Refresh)")
        self.log_line(f"GoFile storage: {message}. GoFile may be rate "
                      "limiting — try again in a minute.")
        self.set_status(False, "GoFile storage failed")

    def on_gofile_storage_click(self, event) -> None:
        """R31 (user: "just a drop down with an arrow"): a plain left click
        on a folder toggles it inline — open shows its children beneath the
        row, closed hides them. The toggle is scheduled 300 ms out so a
        double click inside that window can still overtake it and open the
        folder's public page instead. Ctrl/shift clicks are multi-select
        for Delete and never toggle; files and link-only rows just select.
        R32 retract fix: the row's open state is read NOW, at click time,
        and the scheduled toggle drives to that target. The tree's own
        class binding runs after this handler and flips the arrow itself,
        so a toggle that re-read the state 300 ms later would undo the
        user's click — an open folder could never be closed by clicking
        it (the tree closed it, then the toggle saw "closed" and reopened
        it)."""
        if self._gofile_click_timer:
            try:
                self.after_cancel(self._gofile_click_timer)
            except Exception:
                pass
            self._gofile_click_timer = ""
        if self._gofile_loading:
            return
        if event.state & 0x0005:   # shift or ctrl held: selection click only
            return
        iid = self.gofile_tree.identify_row(event.y)
        child = self._gofile_nodes.get(iid)
        if not child or child.get("type") != "folder":
            return
        was_open = bool(self.gofile_tree.item(iid, "open"))
        self._gofile_click_timer = self.after(
            300, lambda: self._gofile_toggle(iid, child, was_open))

    def _gofile_toggle(self, iid: str, child: dict,
                       was_open: bool = False) -> None:
        """The click-scheduled half of inline expansion (R31). R32 retract
        fix: the target state was decided at click time (was_open) — an
        open folder ALWAYS closes (the way back) and a closed one ALWAYS
        opens, whatever the tree's own class binding did to the arrow in
        between; re-reading the state at toggle time was the reason an
        expanded folder could not be retracted."""
        self._gofile_click_timer = ""
        try:
            if was_open:
                self.gofile_tree.item(iid, open=False)
                return
            if self.gofile_tree.get_children(iid):
                self.gofile_tree.item(iid, open=True)
                return
            self._gofile_expand(iid, child)
        except Exception:
            return

    def _gofile_expand(self, iid: str, child: dict) -> None:
        """Load one folder's children and open its row (R31): a folder read
        before paints from the cache with no GoFile request, a never-seen
        one fetches live and the children slide in under the row when the
        reply lands."""
        fid = str(child.get("id") or "")
        if not fid or fid in self._gofile_pending:
            return
        self._gofile_pending[fid] = iid
        self.gofile_crumbs.configure(
            text=f"loading {child.get('name') or 'folder'}…")
        cached = (self._gofile_cache.get("listings") or {}).get(fid)
        if cached:
            self._gofile_pending.pop(fid, None)
            kids = cached["data"].get("children")
            self._insert_gofile_children(
                iid, kids if isinstance(kids, dict) else {})
            self.gofile_tree.item(iid, open=True)
            if not self._gofile_pending:
                self.gofile_crumbs.configure(text=self._gofile_crumbs_base)
            return
        threading.Thread(target=self._gofile_storage_worker,
                         args=(fid,), daemon=True,
                         name="gofile-storage").start()

    def on_gofile_storage_arrow(self, _event=None) -> None:
        """The +/- arrow was used (R31): the item has just been opened, so
        make sure it holds children — known ones are already in place;
        unknown ones fetch and slide in when the reply arrives."""
        iid = self.gofile_tree.focus()
        child = self._gofile_nodes.get(iid)
        if not child or child.get("type") != "folder":
            return
        if self.gofile_tree.get_children(iid):
            return
        self._gofile_expand(iid, child)

    def on_gofile_storage_open(self, event) -> None:
        """Double-click in GOFILE (R30, user: "two clicks it opens the
        folder in the dashboard"; merged R32): a folder opens its public
        page, gofile.io/d/<code>, in the browser; a link-only row opens
        its link; a file opens its parent folder's page. Returning "break"
        keeps the Treeview's own class double-click from toggling the
        folder open as a side effect — the browser page is the whole
        action."""
        if self._gofile_click_timer:
            try:
                self.after_cancel(self._gofile_click_timer)
            except Exception:
                pass
            self._gofile_click_timer = ""
        iid = self.gofile_tree.identify_row(event.y)
        child = self._gofile_nodes.get(iid)
        if not child:
            return "break"
        if child.get("type") == "folder":
            code = str(child.get("code") or "").strip()
            if code:
                webbrowser.open(f"https://gofile.io/d/{code}")
            else:
                self.log_line("GoFile did not give that folder a public "
                              "code — refresh and try again.")
        elif child.get("type") == "link":
            link = str(child.get("link") or "")
            if link:
                webbrowser.open(link)
            else:
                self.log_line(f"'{child.get('name')}' is archived; select "
                              "it and press Make GoFile link for a fresh "
                              "link.")
        else:
            # R31 (user: double click must never START A DOWNLOAD): a
            # file's "link" is its direct store URL, which the browser
            # downloads. The link the user wants is the FOLDER's public
            # page, so the file's parent row is opened instead; a file
            # sitting at the root has no page of its own, so nothing opens.
            try:
                parent_iid = self.gofile_tree.parent(iid)
            except Exception:
                parent_iid = ""
            parent = self._gofile_nodes.get(parent_iid or "")
            pcode = str((parent or {}).get("code") or "").strip()
            if pcode:
                webbrowser.open(f"https://gofile.io/d/{pcode}")
            else:
                self.log_line("That file sits at the root of My storage — "
                              "open it from gofile.io, or use its row in "
                              "GOFILE.")
        return "break"

    def on_gofile_storage_delete(self) -> None:
        """Delete: every selected row (files and folders both — folder
        deletes are recursive) is confirmed once, then removed from the
        GoFile account server-side. The account token is the GOFILE_API_TOKEN
        from .env; nothing on Torbox is ever touched here."""
        selected = self.gofile_tree.selection()
        if not selected:
            self.set_status(False, "Select rows in GoFile storage first")
            return
        names = [str(self._gofile_nodes.get(iid, {}).get("name") or "?")
                 for iid in selected]
        shown = ", ".join(names[:3]) + (f" … and {len(names) - 3} more"
                                        if len(names) > 3 else "")
        if not messagebox.askyesno(
                "Delete from GoFile",
                f"Delete {len(names)} item(s) from your GoFile account?\n\n"
                f"{shown}\n\nFolder deletes remove everything inside them. "
                "This cannot be undone.", parent=self):
            return
        ids = [str(self._gofile_nodes.get(iid, {}).get("id") or "")
               for iid in selected]
        ids = [i for i in ids if i]

        def worker() -> None:
            try:
                ok = self.gofile.delete_contents(ids)
                detail = "deleted from GoFile" if ok else "GoFile refused the delete"
                self.post_event("gofile_storage_delete_done", (ok, detail, ids))
            except Exception as exc:
                self.post_event("gofile_storage_delete_done",
                                (False, str(exc) or type(exc).__name__, ids))

        threading.Thread(target=worker, daemon=True,
                         name="gofile-storage-delete").start()

    def _on_gofile_storage_delete_done(self, payload: tuple) -> None:
        ok, detail = payload[0], payload[1]
        ids = list(payload[2]) if len(payload) > 2 else []   # R27
        if ok:
            self._gofile_cache_drop(ids)   # gone on the server, gone on disk
            self.log_line(f"GoFile storage: {detail}.")
            self.set_status(True, "Deleted from GoFile")
            self._refresh_links_table()   # a deleted link row should say so
        else:
            self.log_line(f"GoFile storage delete failed: {detail}.")
            self.set_status(False, "GoFile delete failed")
        self.on_gofile_storage_refresh(show_errors=False)

    # ---- Where-column hyperlink (R25b) ---------------------------------

    def _on_downloads_where_click(self, event) -> None:
        """R26b (user): every Where value is a hyperlink to where the
        download actually is. 'On PC' opens the folder in the file manager
        (R25b). 'Torbox only' opens the Torbox dashboard — NOT the raw CDN
        link, which carries the API key in its URL and expires after ~3 h;
        the dashboard is where that download lives safely. 'GoFile only'
        opens the GoFile share link. Any other click stays an ordinary
        row selection."""
        if self.downloads_tree.identify_column(event.x) != "#4":
            return
        iid = self.downloads_tree.identify_row(event.y)
        infohash = self._download_iids.get(iid)
        if not infohash:
            return
        record = self.engine.store.get(infohash) or {}
        folder = str(record.get("folder") or "")
        try:
            has_local = bool(folder) and Path(folder).is_dir()
        except OSError:
            has_local = False
        if has_local:
            self.set_status(True, f"Opening {Path(folder).name}…")
            try:
                self._open_local_folder(folder)
            except Exception as exc:
                self.log_line(f"Could not open the folder: {exc}")
                self.set_status(False, "Could not open the folder")
            return
        if not record.get("gofile_link"):
            # Torbox only: the download lives on the Torbox account.
            self.set_status(True, "Opening the Torbox dashboard…")
            try:
                webbrowser.open("https://torbox.app/dashboard")
            except Exception as exc:
                self.log_line(f"Could not open the browser: {exc}")
                self.set_status(False, "Could not open the browser")
            return
        # GoFile only: open the share link itself.
        link = str(record.get("gofile_link") or "")
        self.set_status(True, "Opening the GoFile link…")
        try:
            webbrowser.open(link)
        except Exception as exc:
            self.log_line(f"Could not open the browser: {exc}")
            self.set_status(False, "Could not open the browser")


    def _on_downloads_changed(self, changed: dict) -> None:
        """Engine poll results: update rows, detect the complete transition,
        and (R36) catch handed-off torrents reaching the cached state."""
        nudged = False   # R46: a download finished on Torbox -> refresh its table
        for infohash, record in changed.items():
            if not isinstance(record, dict):
                continue
            old = self._known_status.get(infohash)
            new = record.get("status") or ""
            self._known_status[infohash] = new
            # R46: a real transition into "held" (cached on Torbox) or
            # "complete" (fetched to this PC's store) means the TORBOX
            # FILES table's row for it is stale — nudge a quiet refresh
            # instead of waiting for the half-hour auto-refresh timer.
            if old is not None and old != new and new in ("held", "complete"):
                nudged = True
            # R36: a handed-off torrent is now cached on Torbox ("held") —
            # or went straight to complete. Notify and act on the default.
            if infohash in self._handoff_pending and new in ("held", "complete"):
                name = self._handoff_pending.pop(infohash)
                self._handoff_ready(infohash,
                                    str(record.get("name") or name))
            if (old is not None and old != "complete" and new == "complete"):
                # R36: "also make a GoFile link" from the handoff popup —
                # upload the local files the moment the PC download is done.
                if infohash in self._handoff_gofile_on_complete:
                    self._handoff_gofile_on_complete.discard(infohash)
                    self._asked_complete.add(infohash)   # answered already
                    self._start_upload(infohash)
                elif (not record.get("gofile_link")
                        and infohash not in self._asked_complete):
                    self._asked_complete.add(infohash)   # ask once per download
                    self._ask_upload_popup(infohash,
                                           record.get("name") or infohash)
        if nudged:
            self._nudge_torbox_table()
        self._refresh_downloads_table()

    def _nudge_torbox_table(self) -> None:
        """R46: refresh the TORBOX FILES table right after a download
        transitioned to cached/complete, so its status column updates
        automatically (user ask). Coalesced: at most one fetch per
        TORBOX_NUDGE_WINDOW seconds, however many torrents finished in
        the same burst; the half-hour timer still covers everything else.
        Runs on the UI thread (the caller already is) but only starts the
        usual daemon worker, so the network never blocks the interface."""
        now = time.monotonic()
        if now - self._torbox_nudge_last < TORBOX_NUDGE_WINDOW:
            return  # one already ran (or is due) inside the window
        self._torbox_nudge_last = now
        self.on_torbox_search()

    def _on_download_added(self, payload: tuple) -> None:
        infohash, name = payload
        self._known_status[infohash] = "adding"
        self.log_line(f"'{name}' added to Torbox (infohash {infohash}).")
        self._refresh_downloads_table()
        self.set_status(True, "Ready")

    # ---- file-association handoff (R36) ---------------------------------------------

    def on_handoff_items(self, items: list) -> None:
        """Called by the single-instance listener (its own thread) when a
        second app instance handed magnets or .torrent files over. The
        queue hop makes the UI thread the only consumer."""
        if items:
            self.post_event("handoff_items", list(items))

    def _on_handoff_items(self, payload: list) -> None:
        self._consume_handoff_items(payload)

    def _consume_handoff_items(self, items: list) -> None:
        """Add every handed-off item to Torbox and mark it pending, so the
        cached-on-Torbox moment knows to notify and ask. Torbox accepts
        magnets and .torrent files; anything else is said so and ignored."""
        accepted = 0
        for item in items:
            text = str(item)
            if text.startswith("magnet:"):
                name = _magnet_display_name(text)
                infohash = _infohash(text)
                if infohash:
                    self._handoff_pending[infohash] = name or infohash
                self.log_line(f"Handoff: adding magnet '{name}' to Torbox…")
                self.set_status(True, "Adding magnet to Torbox…")
                threading.Thread(target=self._add_worker, args=(text, name),
                                 daemon=True, name="handoff-magnet").start()
                accepted += 1
                continue
            path = Path(text)
            if path.suffix.lower() == ".torrent" and path.is_file():
                self.log_line(f"Handoff: adding '{path.name}' to Torbox…")
                self.set_status(True, f"Adding {path.name} to Torbox…")
                threading.Thread(target=self._handoff_torrent_file_worker,
                                 args=(str(path),), daemon=True,
                                 name="handoff-torrent").start()
                accepted += 1
                continue
            self.log_line(f"Handoff: '{path.name}' is not something Torbox "
                          "accepts (magnets and .torrent files); ignored.")
        if accepted:
            self.log_line(f"Handoff: {accepted} item(s) queued on Torbox; "
                          "you will be asked what to do once cached.")

    def _handoff_torrent_file_worker(self, path: str) -> None:
        """Daemon: put one handed-off .torrent file on Torbox and mark it
        pending (same shape as _drop_add_worker, plus the pending mark)."""
        try:
            infohash = self.engine.add_torrent_file(path)
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            self.post_event("log",
                            f"Could not add '{Path(path).name}': {message}")
            self.post_event("status", (False,
                                       f"Adding {Path(path).name} failed"))
            return
        if not infohash:
            self.post_event("log", f"Could not read '{Path(path).name}' "
                            "(no usable info dict); not added.")
            return
        self._handoff_pending[infohash] = Path(path).stem
        self.post_event("download_added", (infohash, Path(path).stem))

    def _handoff_default_mode(self) -> str:
        """The remembered handoff default, applied in memory when the user
        checked 'remember as default' (no restart needed), or the .env
        value. Deliberately never 'gofile': a GoFile link can never be the
        default (user rule) — the popup's 'also make a GoFile link' box is
        the only way to add one."""
        if self._handoff_default_setting:
            return self._handoff_default_setting
        return self.config.handoff_default

    def _save_handoff_default(self, value: str) -> None:
        """Persist HANDOFF_DEFAULT to .env (comments preserved) and apply
        it in memory right away. Values written here are only ever 'pc' or
        'torbox' — never 'gofile'."""
        self._handoff_default_setting = value
        if not wizard.merge_env(self.config.env_path,
                                {"HANDOFF_DEFAULT": value}):
            self.log_line("Could not write HANDOFF_DEFAULT to .env; it "
                          "applies to this session only.")

    def _handoff_ready(self, infohash: str, name: str) -> None:
        """A handed-off torrent is now cached on Torbox. Tell the user
        (desktop notification), then act on the default: ask in a popup,
        download to the PC, or leave it on the account."""
        try:
            handoff.notify("Torbox Downloader", f"'{name}' is cached on Torbox.")
        except Exception:
            pass   # a missed toast must never break the flow
        mode = self._handoff_default_mode()
        if mode == "pc":
            self.log_line(f"Handoff: '{name}' is cached; downloading to "
                          "this PC (default).")
            self._handoff_start_pc_download(infohash, name)
            return
        if mode == "torbox":
            self.log_line(f"Handoff: '{name}' is cached on Torbox and stays "
                          "there (default).")
            self.set_status(True, "Ready")
            return
        self._ask_handoff_popup(infohash, name)

    def _handoff_start_pc_download(self, infohash: str, name: str) -> None:
        """Fetch the cached torrent to this PC (same worker the Download
        button uses; one job per infohash, like everywhere else)."""
        if infohash in self._torbox_link_running:
            self.log_line(f"'{name}' already has a job running; one at a time.")
            return
        self._torbox_link_running.add(infohash)
        threading.Thread(target=self._torbox_link_worker,
                         args=(infohash, name, False),
                         daemon=True, name="handoff-pc").start()

    def _ask_handoff_popup(self, infohash: str, name: str) -> None:
        """Centered popup: the handed-off torrent is cached on Torbox —
        download it to this PC? Two checkboxes: 'Also make a GoFile link'
        and 'Remember this answer as the default'. RULE: the remember box
        only ever remembers the PC/Torbox answer — a GoFile link can never
        become the default."""
        win = tk.Toplevel(self)
        win.title("Torrent cached on Torbox")
        win.configure(background=Theme.BG)
        win.resizable(False, False)
        win.transient(self)
        ttk.Label(win, text=(
            f"'{name}' is cached on Torbox.\n\n"
            "Download it to this PC now?"), justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(14, 6))
        go_var = tk.BooleanVar(value=False)
        remember_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(win, text="Also make a GoFile link",
                        variable=go_var).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=14, pady=2)
        ttk.Checkbutton(win, text="Remember this answer as the default",
                        variable=remember_var).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=14, pady=(2, 6))

        def yes() -> None:
            win.destroy()
            if remember_var.get():
                self._save_handoff_default("pc")
            self._handoff_start_pc_download(infohash, name)
            if go_var.get():
                # PC download first; the GoFile upload runs once the local
                # files are complete (the torbox-to-PC-to-GoFile chain).
                self._handoff_gofile_on_complete.add(infohash)
                self.log_line(f"Handoff: '{name}' will also get a GoFile "
                              "link once it finishes downloading here.")

        def no() -> None:
            win.destroy()
            if remember_var.get():
                self._save_handoff_default("torbox")
            if go_var.get():
                # Nothing local: the direct Torbox -> GoFile transfer.
                self.log_line(f"Handoff: starting the direct Torbox -> "
                              f"GoFile transfer for '{name}'.")
                self._start_torbox_link(infohash, name)
            else:
                self.log_line(f"Handoff: '{name}' stays on Torbox.")
            self.set_status(True, "Ready")

        ttk.Button(win, text="Yes", command=yes).grid(
            row=3, column=0, sticky="ew", padx=(14, 4), pady=(5, 12))
        ttk.Button(win, text="No", command=no).grid(
            row=3, column=1, sticky="ew", padx=(4, 14), pady=(5, 12))
        win.columnconfigure(0, weight=1)
        win.columnconfigure(1, weight=1)
        self._center_popup(win)
        win.grab_set()

    # ---- completion popup --------------------------------------------------------

    def _center_popup(self, win: tk.Toplevel) -> None:
        """R34: place a popup over the middle of the main window. Toplevels
        default to the window manager's own spot (top-right of the screen
        here), which the user asked to change."""
        try:
            win.update_idletasks()
            w = win.winfo_reqwidth()
            h = win.winfo_reqheight()
            x = self.winfo_rootx() + max((self.winfo_width() - w) // 2, 0)
            y = self.winfo_rooty() + max((self.winfo_height() - h) // 2, 0)
            win.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

    def _ask_upload_popup(self, infohash: str, name: str) -> None:
        """'<name> finished downloading. Send to GoFile?' — Yes runs the same
        upload flow as Make GoFile link; No leaves the download as it is."""
        win = tk.Toplevel(self)
        win.title("Download complete")
        win.configure(background=Theme.BG)
        win.resizable(False, False)
        win.transient(self)
        ttk.Label(win, text=f"{name} finished downloading.\nSend to GoFile?",
                  justify="left").grid(row=0, column=0, columnspan=2,
                                       sticky="w", padx=14, pady=(12, 5))

        def yes() -> None:
            win.destroy()
            self._start_upload(infohash)

        ttk.Button(win, text="Yes", command=yes).grid(row=1, column=0,
                                                      sticky="ew", padx=(14, 4), pady=(5, 12))
        ttk.Button(win, text="No", command=win.destroy).grid(row=1, column=1,
                                                             sticky="ew", padx=(4, 14), pady=(5, 12))
        win.columnconfigure(0, weight=1)
        win.columnconfigure(1, weight=1)
        self._center_popup(win)
        win.grab_set()

    # ---- search -----------------------------------------------------------------

    def on_category_changed(self, _event=None) -> None:
        """Round R11c: the category dropdown takes effect immediately.
        With a query in the box, changing it re-runs the search under the
        new category; the cancel-and-replace path in on_search handles a
        still-running search. An empty search box does nothing."""
        if self.search_entry.get().strip():
            self.on_search()

    def on_search(self, deadline: float | None = None) -> None:
        """Run a search. R20a: `deadline` overrides the 30-second search
        deadline; when it is not given, the all-time wildcard pattern '*'
        gets TRENDING_SEARCH_DEADLINE (2 minutes) because it gathers far
        more than a normal query — the user saw the 30s deadline end a
        trending search while engines were still working. The button and
        the Return key call this with no arguments, so they pick up the
        pattern-aware default."""
        pattern = self.search_entry.get().strip()
        if not pattern:
            self.set_status(False, "Type something to search for first.")
            self.log_line("Search box is empty; nothing to search.")
            return
        category = CATEGORY_API.get(self.category_combo.get(), "all")
        self._results_cat = category   # R17: games -> version number, else date
        if deadline is None:
            deadline = (TRENDING_SEARCH_DEADLINE if pattern == "*"
                        else SEARCH_DEADLINE)
        # R19/R20: which plugins the search runs through. The dropdown only
        # lists enabled plugins (R20), so the value is always usable; the
        # fallback guards a blank combo on a fresh window.
        plugins = self._plugin_filter_value() or "all"
        if self._searching and self._search_cancel is not None:
            # Round R10: a new search replaces the running one instead of
            # being refused. Cancel the old worker, then let a tiny daemon
            # thread stop+delete the old job best-effort (never the UI
            # thread — those are network calls). The old job id is captured
            # NOW so a late-arriving id can never confuse the cleanup.
            old_cancel = self._search_cancel
            old_job = self._search_job_id
            old_cancel.set()

            def _kill_old_job() -> None:
                if old_job is None:
                    return
                for call in (self.qbit.stop, self.qbit.delete):
                    try:
                        call(old_job)
                    except Exception:
                        pass  # best-effort cleanup only

            threading.Thread(target=_kill_old_job, daemon=True,
                             name="search-replace").start()
            self.log_line("Starting a new search; the running one is replaced…")
        self._searching = True
        cancel = threading.Event()
        self._search_cancel = cancel
        self._search_job_id = None
        self.set_status(True, f"Searching '{pattern}'…")
        threading.Thread(target=self._search_worker,
                         args=(pattern, category, cancel, plugins, deadline),
                         daemon=True, name="search").start()

    def on_clear_search(self) -> None:
        """Clear button (round R11): cancel a running search the same way
        the cancel-and-replace path does (set the worker's cancel event,
        then stop+delete its qBit job best-effort from a daemon thread —
        those are network calls, never the UI thread), wipe the results
        table, and empty the query box. The R10 worker checks its cancel
        event on every poll iteration and exits without posting rows, so a
        cleared table cannot be repopulated by the cancelled worker."""
        if self._searching and self._search_cancel is not None:
            old_cancel = self._search_cancel
            old_job = self._search_job_id
            old_cancel.set()
            threading.Thread(target=self._abandon_job, args=(old_job,),
                             daemon=True, name="search-cancel").start()
        self.results_tree.delete(*self.results_tree.get_children())
        self._results_iids.clear()
        self.search_entry.delete(0, "end")
        self._searching = False
        self.log_line("Search cleared.")
        self.set_status(True, "Ready")

    # ---- R19: plugin filter, trending, plugin updates -----------------------

    def _plugin_filter_value(self) -> str:
        """The "Search in:" dropdown's current choice, as the WebUI API's
        plugins value: "all" or one specific enabled plugin's name. (R20:
        disabled plugins are hidden from the dropdown, so the old
        "enabled"/"disabled" resolutions are gone.)"""
        sel = self.plugin_combo.get()
        if not sel or sel == "All plugins":
            return "all"
        return sel  # one specific (enabled) plugin name

    def _on_plugin_list(self, plist) -> None:
        """Refresh the "Search in:" dropdown with the installed plugin
        names (UI thread; the worker posts the list). R20: only ENABLED
        plugins are listed, disabled ones are hidden. The current
        selection is kept when still valid."""
        self._qbit_plugins = [p for p in (plist or [])
                              if isinstance(p, dict) and p.get("name")]
        names = sorted({p["name"] for p in self._qbit_plugins if p.get("enabled")})
        values = list(PLUGIN_FILTER_LABELS) + names
        current = self.plugin_combo.get()
        self.plugin_combo.configure(values=values)
        if current not in values:
            self.plugin_combo.current(0)

    def on_trending(self) -> None:
        """R20 'Trending' button: the search box gets a wildcard pattern
        that the engines treat as "everything" (verified live against the
        WebUI API: '*' returns ~100 real results with seed counts, an
        empty pattern returns nothing but plugin error rows, and a year
        only surfaces one year). The table then sorts by Seeds for the
        most-seeded or by Date/Version for the newest — all of time,
        not just the current year."""
        self.search_entry.delete(0, "end")
        self.search_entry.insert(0, "*")
        self.log_line("Trending: searching all of time in the current "
                      "category and plugin filter. Click Seeds for the "
                      "most-seeded, Date or Version for the newest.")
        self.on_search()

    def _plugin_update_worker(self, forced: bool) -> None:
        """Daemon: fetch the plugin list, run qBittorrent's own update pass
        (each plugin re-fetched from its source, replaced only when newer),
        refetch the list and diff the versions. Started automatically once
        at startup (forced=False, only logs when something changed) and on
        demand from Settings (forced=True, always logs the outcome)."""
        try:
            before = {str(p.get("name")): str(p.get("version"))
                      for p in (self.qbit.plugins() or []) if p.get("name")}
        except Exception as exc:
            hint = _qbit_hint(exc)
            self.post_event(
                "log",
                f"Search plugin list unavailable: {exc}. Search needs "
                "qBittorrent running with its WebUI enabled." + hint)
            return
        try:
            self.qbit.update_plugins()
        except Exception as exc:
            self.post_event("log", f"Search plugin update failed: {exc}")
            return
        try:
            plist = self.qbit.plugins() or []
        except Exception as exc:
            self.post_event("log",
                            "Search plugin update ran, but the list "
                            f"refresh failed: {exc}")
            return
        self.post_event("plugin_list", plist)
        changes = []
        for p in plist:
            name, ver = str(p.get("name")), str(p.get("version"))
            old = before.get(name)
            if old is None:
                changes.append(f"{name} (new)")
            elif old != ver:
                changes.append(f"{name} {old} -> {ver}")
        if changes:
            self.post_event("log", "Search plugins updated: "
                            + ", ".join(changes) + ".")
        elif forced:
            self.post_event("log", f"Search plugins checked: {len(plist)} "
                            "installed, all current.")
        # startup pass with nothing to change stays silent

    @staticmethod
    def _is_plugin_error(item: SearchItem) -> bool:
        """qBittorrent plugins inject their failures as fake results; those
        rows must never reach the table. Two known shapes: a negative size
        ("Jackett: api key error!" rows) and a "[something][Error]: ..."
        name (rutor-style rows that carry a fake 1 TiB size)."""
        size = item.size_bytes
        if isinstance(size, (int, float)) and size < 0:
            return True
        name = item.name or ""
        return name.startswith("Jackett:") or "][Error]:" in name

    def _abandon_job(self, job_id: int | None) -> None:
        """Best-effort stop+delete of one replaced search job (worker thread
        only — these are network calls). Harmless if the replace thread
        already cleaned the same job up."""
        if job_id is None:
            return
        for call in (self.qbit.stop, self.qbit.delete):
            try:
                call(job_id)
            except Exception:
                pass

    def _search_worker(self, pattern: str, category: str,
                       cancel: threading.Event, plugins: str = "all",
                       deadline: float = SEARCH_DEADLINE) -> None:
        """qBittorrent search in a worker thread, streaming like qBittorrent's
        own UI: probe, start a job, then poll status AND results about once a
        second, posting only the NEW rows after each poll (deduped by name +
        url + size; plugin-error rows are hidden and counted). The loop ends
        when the job is 'stopped' AND a final page fetch came up short, or at
        the deadline; R20a: on_search passes the deadline (30s normally, 2
        minutes for the all-time trending '*' query); the job is deleted
        best-effort afterwards.

        Round R10: `cancel` is this worker's own event. When a new search
        replaces this one, the event is set (and a daemon thread stops+deletes
        this job); the worker checks the event between polls, posts nothing
        except "Search replaced by a new one." and exits silently. `job_id`
        stays a local captured at start, so the finally block can never touch
        a NEWER search's job. Every call here is non-blocking and this thread
        is a daemon; the UI only ever sees posted events."""
        job_id: int | None = None
        posted = 0
        dropped = 0
        drop_engines: set[str] = set()
        drop_line_posted = False

        def post_drop_line() -> None:
            nonlocal drop_line_posted
            if dropped and not drop_line_posted:
                drop_line_posted = True
                engines = ", ".join(sorted({e.lower() for e in drop_engines if e}))
                self.post_event("log", "Hid " + f"{dropped} plugin error row(s)"
                                + (f" ({engines})" if engines else ""))

        try:
            self.post_event("search_started", None)
            self.post_event("log", f"Searching '{pattern}'…")
            self.qbit.version()  # connectivity probe; raises QBitError if unreachable
            job_id = self.qbit.search(pattern, category=category, plugins=plugins)
            # Register the job id for the replace path only while this is
            # still the current search (a newer search has already swapped
            # self._search_cancel for its own event).
            if self._search_cancel is cancel:
                self._search_job_id = job_id
            if cancel.is_set():
                self.post_event("log", "Search replaced by a new one.")
                self._abandon_job(job_id)
                return
            seen: set[tuple] = set()
            offset = 0
            stopped = False
            replaced = False
            deadline_at = time.monotonic() + deadline
            failures = 0
            while True:
                if cancel.is_set():
                    replaced = True
                    break
                page: list[SearchItem] = []
                try:
                    page = self.qbit.results(job_id,
                                             limit=RESULTS_PAGE_SIZE,
                                             offset=offset)
                    offset += len(page)
                    status = self.qbit.poll_status(job_id).get("status")
                    failures = 0
                except QBitError:
                    # A transient WebUI hiccup must not kill a running
                    # search; give up only after several in a row.
                    failures += 1
                    if failures > 5:
                        raise
                    status = None
                if cancel.is_set():
                    # The replacement cleared the table already; these rows
                    # must never land in the new search's results.
                    replaced = True
                    break
                fresh = []
                for item in page:
                    if self._is_plugin_error(item):
                        dropped += 1
                        if item.engine:
                            drop_engines.add(item.engine)
                        continue
                    key = (item.name, item.file_url, item.size_bytes, item.engine)
                    if key not in seen:
                        seen.add(key)
                        fresh.append(item)
                if fresh:
                    posted += len(fresh)
                    self.post_event("search_rows", fresh)
                    self.post_event("log",
                                    f"Search progress: {posted} results so far")
                if status == "stopped":
                    stopped = True
                    if len(page) < RESULTS_PAGE_SIZE:
                        break  # stopped AND the final (short) page is in
                if time.monotonic() >= deadline_at:
                    break
                if cancel.wait(SEARCH_POLL_INTERVAL):
                    replaced = True
                    break
            if replaced:
                self.post_event("log", "Search replaced by a new one.")
                self._abandon_job(job_id)
                return
            post_drop_line()
            if not posted and not stopped:
                raise QBitError(
                    f"search for '{pattern}' did not finish within "
                    f"{int(deadline)}s and no results arrived yet")
            self.post_event("log", f"Search finished: {posted} results shown")
            self.post_event("status", (True, "Ready"))
        except Exception as exc:
            if cancel.is_set():
                # The replacement already owns the UI; stay silent about this
                # worker's failure and just clean its job up.
                self.post_event("log", "Search replaced by a new one.")
                self._abandon_job(job_id)
                return
            post_drop_line()
            # Friendly message only; qbit/gofile/torbox errors never carry secrets.
            exc_text = str(exc) or type(exc).__name__
            self.post_event("log", (exc_text + (" " + _qbit_hint(exc)
                                                if _qbit_hint(exc) else "")))
            self.post_event("status", (False, exc_text or "Search failed"))
        finally:
            # Only the still-current worker cleans up: a replaced worker's job
            # is handled by the replace thread (and, if the job id only arrived
            # after the replacement, by the check right above). job_id is a
            # local from this worker's own start, so a NEW search's job is
            # never deleted here.
            if self._search_cancel is cancel:
                if job_id is not None:
                    try:
                        self.qbit.delete(job_id)
                    except Exception:
                        pass  # cleanup is best-effort; never mask the real result
                self._searching = False
                self._search_cancel = None
                self._search_job_id = None

    # ---- results table: append and sort -------------------------------------

    def _row_version_cell(self, item: SearchItem) -> str:
        """The Version cell, per the user's R17/R18 definition. For a game,
        the best information the name itself carries, in order of
        preference: the version/update number ("v1.0.1", "Update 4"); when
        the name carries no number, the release tags (region/rev/language,
        e.g. "USA · Multi 5"); when neither, the upload date. For non-games,
        the upload date. Games are known by the search category when one was
        chosen, else by the name's own keywords. A name that carries no
        version information at all cannot be mined further from the name
        alone (checksum DAT matching would need the actual files)."""
        name = item.name or ""
        cat = getattr(self, "_results_cat", "all")
        if cat == "games" or (cat == "all" and _looks_like_game(name)):
            number = game_version(name)
            if number:
                return number
            tags = version_tags(name)
            if tags:
                return tags
        return _upload_date_text(item)

    def _append_row(self, item: SearchItem) -> None:
        """Insert one SearchItem at the bottom of the results table. The
        Version cell (R17) shows the game's version/update number for games
        and the upload date for other media."""
        values = (item.name or "(untitled)",
                  self._row_version_cell(item),
                  human_size(item.size_bytes),
                  str(item.seeds), item.engine)
        iid = self.results_tree.insert("", "end", values=values)
        self._results_iids[iid] = item

    def _append_results(self, items: list[SearchItem]) -> None:
        """Append one streamed batch of rows to the results table (the table
        itself is cleared by the search_started event, never here). When the
        user has chosen a sort, the whole table is re-sorted after the batch
        lands so the visible order stays the one they asked for."""
        for item in items:
            self._append_row(item)
        if self._sort_col is not None:
            self._resort_results()

    def on_sort_results(self, col: str) -> None:
        """A results heading was clicked: sort by that column, flipping the
        direction on repeated clicks (first click on Size/Seeds shows the
        biggest first, like qBittorrent)."""
        if self._sort_col == col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col = col
            # R18b: Version joins Size/Seeds in showing "biggest/best"
            # first on the initial click.
            self._sort_desc = col in ("size", "seeds", "version")
        self._resort_results()

    def _version_rank(self, item: SearchItem) -> tuple:
        """Comparable rank for the Version column so 'best first' means:
        highest version number (v1.0.1 style), then Update/Build numbers,
        then newest upload date; anything without a number (release tags)
        falls in the last group. Ties are broken by seeds (see
        _sort_value), which gives the user's 'latest version with the most
        seeds' ordering."""
        cell = self._row_version_cell(item).strip()
        lower = cell.lower()
        digits = [int(x) for x in re.findall(r"\d+", cell)]
        if lower.startswith(("update", "build")) and digits:
            return (1, digits[0])
        if lower.startswith("v") and digits:
            return (2,) + tuple(digits)
        if re.match(r"^\d{4}-\d{2}-\d{2}$", cell):
            return (0,) + tuple(digits)
        return (0, 0)

    def _sort_value(self, item: SearchItem, col: str):
        """Numeric sort values with None (or anything non-numeric) treated as
        the smallest possible; Name sorts case-insensitively."""
        if col == "name":
            return (item.name or "").lower()
        if col == "version":
            # R18b/R18c: rank by version quality (best number first), ties
            # broken by seed count — the "latest version with the most
            # seeds" order the user asked for.
            seeds = item.seeds if isinstance(item.seeds, int) else -1
            return (self._version_rank(item), seeds)
        if col == "seeds":
            # R18c: two-stage in this direction too — most seeds first, and
            # among equal seed counts the latest version wins the tie.
            seeds = item.seeds if isinstance(item.seeds, int) else -1
            return (seeds, self._version_rank(item))
        value = item.size_bytes if col == "size" else item.seeds
        return value if isinstance(value, (int, float)) else -1

    def _resort_results(self) -> None:
        """Rebuild the results table in the active sort order (or, with no
        sort active, in arrival order) and refresh the heading indicators."""
        for c, base in self._results_base.items():
            text = base
            if c == self._sort_col:
                text += " ▼" if self._sort_desc else " ▲"
            self.results_tree.heading(
                c, text=text, anchor=self.results_tree.column(c, "anchor"))
        items = list(self._results_iids.values())
        if self._sort_col is not None:
            col, desc = self._sort_col, self._sort_desc
            items.sort(key=lambda item: self._sort_value(item, col), reverse=desc)
        self.results_tree.delete(*self.results_tree.get_children())
        self._results_iids.clear()
        for item in items:
            self._append_row(item)

    # ---- download (add to Torbox) -------------------------------------------------

    def on_download(self) -> None:
        """R22 select-then-press: acts on the row last clicked in ANY table.
        A search result is added to Torbox (hold-by-default: nothing is
        fetched yet); a torbox or downloads row is fetched to this PC
        without uploading (adopting it into the store first when it was
        never tracked)."""
        origin, payload = self._origin_selection()
        if payload is None:
            self.log_line("Click a row in one of the tables first, then "
                          "press Download.")
            return
        if origin == "results":
            item = payload
            name = item.name or "result"
            if not item.file_url.startswith("magnet:"):
                self.log_line(f"'{name}' is not a magnet link; only magnet "
                              "results can be sent to Torbox.")
                return
            self.set_status(True, f"Adding {name} to Torbox…")
            self.log_line(f"Adding '{name}' to Torbox…")
            threading.Thread(target=self._add_worker,
                             args=(item.file_url, name),
                             daemon=True, name="add").start()
            return
        if origin == "torbox":
            infohash, _torrent_id, name = payload
        elif origin == "links":
            # R28: link-only records now live in the links table, so a
            # Download press there fetches the record back to this PC (its
            # torrent is still in the Torbox account; nothing is re-added).
            # Direct drops have no torrent behind them and stay refused.
            infohash, name, state = payload
            record = self.engine.store.get(infohash) or {}
            if record.get("direct"):
                self.log_line(f"'{name}' is a direct GoFile drop; there is no "
                              "torrent behind it to download to this PC.")
                return
            if "archived" in str(state):
                self.log_line(f"'{name}' has no live GoFile link; select it "
                              "and press Make GoFile link to reinstate it.")
                return
        else:  # downloads
            infohash = payload
            try:
                record = self.engine.store.get(infohash) or {}
            except Exception:
                record = {}
            name = record.get("name") or infohash
        if infohash in self._torbox_link_running:
            self.log_line(f"'{name}' already has a job running; one at a "
                          "time.")
            return
        self._torbox_link_running.add(infohash)
        self.log_line(f"Downloading '{name}' to this PC…")
        self.set_status(True, f"Downloading '{name}'…")
        threading.Thread(target=self._torbox_link_worker,
                         args=(infohash, name, False),
                         daemon=True, name="fetch-only").start()

    def _add_worker(self, magnet: str, name: str) -> None:
        try:
            infohash = self.engine.add(magnet, name)
            self.post_event("download_added", (infohash, name))
        except Exception as exc:
            self.post_event("log", str(exc) or type(exc).__name__)
            self.post_event("status", (False, f"Adding '{name}' failed: {exc}"))

    # ---- download & unpack (one button, round R10) --------------------------

    def on_download_unpack(self) -> None:
        """'Download & Unpack': for a held or failed record, release it to
        the PC, wait for completion, then unpack to the default preset. For
        an already-complete record, run just the unpack part. Other statuses
        log why nothing happens."""
        record = self._selected_record()
        if record is None:
            self.log_line("No download selected; nothing to do.")
            return
        infohash = record["infohash"]
        name = record.get("name") or infohash
        status = record.get("status") or ""
        if status in ("held", "failed"):
            self.set_status(True, f"Fetching {name} from Torbox to this PC…")
            self.log_line(f"Fetching '{name}' from Torbox to this PC…")
            threading.Thread(target=self._download_unpack_worker,
                             args=(infohash, name, True),
                             daemon=True, name="download-unpack").start()
        elif status == "downloading":
            self.log_line(f"'{name}' is already downloading; when it completes "
                          "this button will unpack it.")
        elif status == "complete":
            self.set_status(True, f"Unpacking {name}")
            self.log_line(f"Unpacking '{name}' to the default preset…")
            threading.Thread(target=self._download_unpack_worker,
                             args=(infohash, name, False),
                             daemon=True, name="download-unpack").start()
        elif status == "unpacked":
            dest = record.get("unpack_dest") or "a preset folder"
            self.log_line(f"'{name}' was already unpacked to {dest}.")
        else:  # adding / unpacking: transitional states
            self.log_line(f"'{name}' is still {status} on Torbox; try again in a moment.")

    def _download_unpack_worker(self, infohash: str, name: str,
                                do_release: bool) -> None:
        """Daemon: release the record to the PC (when asked), poll the store
        until it is "complete" or "failed" (up to 30 min), then unpack to the
        default preset. The completion popup still fires from the engine
        poller's own downloads_changed event, untouched by this worker."""
        try:
            if do_release:
                # R23: an explicit Download press after a Stop clears the
                # engine's cancel flag first (release() refuses while it
                # is still set, so a stop is never silently undone by a
                # background job — only by a deliberate press here).
                self.engine.resume(infohash)
                self.engine.release(infohash)
                self.post_event("log",
                                f"'{name}' released: files are being fetched to this PC.")
            deadline = time.monotonic() + DOWNLOAD_UNPACK_DEADLINE
            while True:
                record = self.engine.store.get(infohash) or {}
                status = record.get("status") or ""
                if status == "complete":
                    break
                if status == "failed":
                    self.post_event("log",
                                    f"'{name}' failed to download; nothing to unpack.")
                    self.post_event("status", (False, f"Download of '{name}' failed"))
                    return
                if time.monotonic() >= deadline:
                    self.post_event("log",
                                    f"'{name}' is still not complete after 30 minutes; "
                                    "unpack skipped (it can be unpacked later with "
                                    "Download & Unpack).")
                    self.post_event("status", (False, f"'{name}' still not complete"))
                    return
                if self._stop_poll.wait(DOWNLOAD_POLL_INTERVAL):
                    return  # app is closing
            dest = self.presets.default
            if not dest:
                self.post_event("log", "Downloaded, but no default unpack preset is "
                                       "set (Presets…).")
                self.post_event("status", (True, "Ready"))
                return
            # engine.unpack() itself sets unpacked=True, unpack_dest=dest and
            # keeps status "complete" — the UI must not double-update.
            extracted = self.engine.unpack(infohash, dest)
            self.post_event("unpack_done", (infohash, name, dest, len(extracted)))
        except Exception as exc:
            if do_release and isinstance(exc, ValueError) and "not held" in str(exc):
                # A record that changed status between the button press and
                # the release: report it plainly instead of a scary error.
                self.post_event("log", str(exc))
                self.post_event("status", (False, str(exc)))
                return
            self.post_event("log", str(exc) or type(exc).__name__)
            self.post_event("status",
                            (False, f"Download & Unpack of '{name}' failed: {exc}"))

    # ---- engine poller ------------------------------------------------------------

    def _poll_loop(self) -> None:
        """Daemon: engine.refresh() every 3s; changed records go through the
        event queue so the UI thread does all widget work."""
        last_fail_post = 0.0
        while not self._closing:
            try:
                changed = self.engine.refresh()
            except Exception as exc:
                now = time.monotonic()
                if now - last_fail_post > POLL_FAILURE_ECHO:
                    last_fail_post = now
                    self.post_event("log", str(exc) or type(exc).__name__)
                    self.post_event("status", (False, str(exc) or "Torbox poll failed"))
                changed = {}
            if changed:
                self.post_event("downloads_changed",
                                {k: dict(v) for k, v in changed.items()})
            if self._stop_poll.wait(POLL_INTERVAL):
                break

    # ---- GoFile 30-day reminder (R24) ---------------------------------------------------

    def _ttl_loop(self) -> None:
        """Daemon: one reminder pass right after startup, then one every
        GOFILE_TTL_INTERVAL (6 hours). The lock guard means a slow pass can
        never overlap the next one (a later tick just skips while one runs).
        Exits with the app via _stop_poll / _closing."""
        while not self._closing:
            self._run_ttl_pass()
            if self._stop_poll.wait(GOFILE_TTL_INTERVAL):
                break

    def _run_ttl_pass(self) -> None:
        """One reminder pass in this worker thread (R24, per the user: the
        app NEVER deletes GoFile or Torbox content on its own any more).

        Every record with a live link older than gofile_ttl_days (30 by
        default) is collected; the UI thread gets a reminder naming them so
        the user can remove them with the Delete button in the GOFILE
        LINKS table or on gofile.io. Nothing is deleted or archived here.
        """
        if not self._ttl_lock.acquire(blocking=False):
            return  # a pass is already running; skip this tick
        try:
            ttl_days = self.config.gofile_ttl_days
            cutoff = time.time() - ttl_days * 86400
            try:
                records = self.engine.store.all()
            except Exception as exc:
                self.post_event("log",
                                f"GoFile reminder pass failed: {exc}" or type(exc).__name__)
                return
            aged = []
            for infohash, record in records.items():
                if not record.get("gofile_link") or record.get("archived"):
                    continue
                created = _parse_utc_iso(record.get("gofile_created"))
                if created is not None and created.timestamp() <= cutoff:
                    aged.append(record.get("name") or infohash)
            if aged:
                self.post_event("gofile_expired", (sorted(aged), ttl_days))
        finally:
            self._ttl_lock.release()

    def _on_gofile_expired(self, payload: tuple) -> None:
        names, ttl_days = payload
        self.log_line(
            f"GoFile reminder: {len(names)} link(s) older than {ttl_days} days "
            "need removal: " + ", ".join(names) + ". "
            "Use Delete in GOFILE (or gofile.io) to delete them — "
            "the app never removes them on its own.")

    # ---- GoFile upload ---------------------------------------------------------------

    def on_make_gofile_link(self) -> None:
        """R22 select-then-press: acts on the row last clicked in ANY table.
        A search result runs the full chain (add to Torbox, wait, fetch to
        the PC, upload); a torbox row is adopted/fetched/uploaded; a
        downloads row uploads what is already here."""
        origin, payload = self._origin_selection()
        if payload is None:
            self.log_line("Click a row in one of the tables first, then "
                          "press Make GoFile link.")
            return
        if origin == "results":
            self._start_result_link(payload)
        elif origin == "torbox":
            infohash, _torrent_id, name = payload
            self._start_torbox_link(infohash, name)
        elif origin == "links":
            # R22b: the selected row is a GoFile link (or an archived one).
            # A live link is already made — say so; an archived row gets a
            # fresh link made from the files still on disk.
            infohash, name, state = payload
            self._relink_from_links(infohash, name)
        else:  # downloads
            infohash = payload
            try:
                record = self.engine.store.get(infohash) or {}
            except Exception:
                record = {}
            self._start_torbox_link(infohash, record.get("name") or infohash)

    def _relink_from_links(self, infohash: str, name: str) -> None:
        """R22b: Make GoFile link was pressed with a GOFILE row selected. A row that still has its link just gets the usual
        already-has-a-link message. An ARCHIVED row is reinstated: its
        local folder (torrent records) or original file (direct drops) is
        uploaded to GoFile again and the record goes back to live."""
        try:
            record = self.engine.store.get(infohash) or {}
        except Exception:
            record = {}
        if record.get("gofile_link"):
            self.log_line(f"'{name}' already has a GoFile link: "
                          f"{record['gofile_link']}")
            self.set_status(True, "Ready")
            return
        if record.get("direct"):
            source = str(record.get("folder") or "")
            if not source or not Path(source).is_file():
                self.log_line(
                    f"'{name}' is archived and its original file is no "
                    "longer on disk, so a new link cannot be made from it.")
                return
            if infohash in self._torbox_link_running:
                self.log_line(f"'{name}' already has a job running; one at a time.")
                return
            self._torbox_link_running.add(infohash)
            self.log_line(f"Remaking the GoFile link for '{name}'…")
            self.set_status(True, f"Remaking GoFile link for {name}…")
            threading.Thread(target=self._direct_relink_worker,
                             args=(infohash, source, name),
                             daemon=True, name="gofile-relink").start()
            return
        # A torrent record: the ordinary upload worker already handles
        # archived records (folder still on disk -> fresh link -> the
        # archived flags clear).
        self._start_upload(infohash)

    def _direct_relink_worker(self, infohash: str, source: str, name: str) -> None:
        """Daemon: re-upload one direct-drop file to GoFile and put the SAME
        record back to live (fresh link + folder id + timestamps, archived
        flags cleared). Same upload shape as _gofile_drop_worker."""
        try:
            file_path = Path(source)
            folder = self.gofile.create_folder("root", file_path.stem)
            # R22c: the top activity bar tracks this upload too.
            # R23: cancel-aware like every other upload.
            cancel = self._cancel_event(infohash)
            job = _UploadJob(infohash, name,
                             bytes_all=file_path.stat().st_size)

            def _relink_progress(sent: int, total: int) -> None:
                if cancel.is_set():
                    raise _UploadStopped()
                job.callback(str(file_path), sent, total)

            with self._upload_jobs_lock:
                self._upload_jobs[infohash] = job
            try:
                result = self.gofile.upload_file(folder, str(file_path),
                                                 on_progress=_relink_progress)
                if cancel.is_set():
                    raise _UploadStopped()
            finally:
                with self._upload_jobs_lock:
                    self._upload_jobs.pop(infohash, None)
            link = str((result or {}).get("downloadPage")
                       or (result or {}).get("link") or "").strip()
            if not link:
                raise GofileError("GoFile did not return a share link")
            now = _utc_now_iso()
            self.engine.store.update(
                infohash, gofile_link=link,
                gofile_folder_id=str(folder) if folder else None,
                gofile_created=now, uploaded_at=now,
                archived=False, archived_at=None, gofile_removed_at=None)
            self.post_event("links_table_refresh", None)
            self.post_event("log", f"GoFile link for '{name}': {link}")
            self.post_event("status", (True, "GoFile link ready"))
        except _UploadStopped:
            # R23 Stop: a deliberate stop is not an error.
            self.post_event("log", f"'{name}' was stopped.")
            self.post_event("status", (True, "Ready"))
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            self.post_event("log", f"GoFile relink of '{name}' failed: {message}")
            self.post_event("status", (False, f"Relinking '{name}' failed: {message}"))
        finally:
            self.post_event("torbox_link_done", infohash)

    def _start_upload(self, infohash: str) -> None:
        """Shared by the button and the completion popup's Yes."""
        record = self.engine.store.get(infohash)
        if record is None:
            self.log_line("That download record no longer exists; nothing to upload.")
            return
        name = record.get("name") or infohash
        if record.get("gofile_link"):
            self.log_line(f"'{name}' already has a GoFile link: {record['gofile_link']}")
            self.set_status(True, "Ready")
            return
        # Task 7 re-upload path: an archived record has no link anymore, and
        # its local folder still exists (expiry never touches local files),
        # so it may go back up to GoFile even when its status is "unpacked"
        # rather than "complete".
        if record.get("status") != "complete" and not record.get("archived"):
            self.log_line(f"'{name}' is not complete yet (status: {record.get('status')}); "
                          "nothing to upload.")
            return
        folder = record.get("folder") or ""
        if not folder or not Path(folder).is_dir():
            self.log_line(f"'{name}' has no download folder on disk; nothing to upload.")
            return
        self.set_status(True, f"Uploading {name} to GoFile…")
        self.log_line(f"Uploading '{name}' to GoFile…")
        threading.Thread(target=self._upload_worker, args=(infohash, name, folder),
                         daemon=True, name="gofile-upload").start()

    def _upload_worker(self, infohash: str, name: str, folder: str) -> None:
        # R22c: register a progress accumulator so the top activity bar
        # tracks this upload (total = the folder's bytes, known up front).
        # R23: the Stop button ends this upload mid-file — the cancel-aware
        # wrapper raises _UploadStopped from on_progress, which aborts
        # gofile's streamed body cleanly.
        cancel = self._cancel_event(infohash)
        try:
            bytes_all = sum(
                p.stat().st_size for p in Path(folder).iterdir() if p.is_file())
        except Exception:
            bytes_all = 0
        job = _UploadJob(infohash, name, bytes_all)

        def _progress(path: str, sent: int, total: int) -> None:
            if cancel.is_set():
                raise _UploadStopped()
            job.callback(path, sent, total)

        with self._upload_jobs_lock:
            self._upload_jobs[infohash] = job
        try:
            folder_id, link = self.gofile.upload_folder(folder, name=name,
                                                        on_progress=_progress)
            if cancel.is_set():
                raise _UploadStopped()
            if link:
                # Task 7: keep the folder id and the creation time so the TTL
                # scheduler can expire this content later. This same path also
                # serves the archived re-upload: clearing archived and
                # gofile_removed_at moves the record back into the live table.
                self.engine.store.update(
                    infohash, gofile_link=link,
                    gofile_folder_id=folder_id or None,
                    gofile_created=_utc_now_iso(),
                    uploaded_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                    archived=False, gofile_removed_at=None)
                # R24: when the Make-GoFile-link job pulled the files down to
                # this PC itself, the local copy goes away again now that the
                # upload succeeded. A pre-downloaded torrent (no flag) is kept.
                if self._link_delete_after.pop(infohash, False):
                    detail = self._delete_local_folder_guarded(folder)
                    if detail.startswith("folder deleted"):
                        # The record keeps its link; held means the Download
                        # button can fetch it again from Torbox later.
                        self.engine.store.update(infohash, folder="",
                                                 status="held", unpacked=False)
                        self.post_event("log", f"Local copy of '{name}' "
                                        "deleted again after the upload "
                                        f"({detail}); the GoFile link stays "
                                        "and the record can be re-fetched "
                                        "from Torbox.")
                    else:
                        self.post_event("log", f"Local copy of '{name}' kept "
                                        f"({detail}).")
            self.post_event("gofile_done", (infohash, link, name))
        except _UploadStopped:
            # R23 Stop: a deliberate stop is not an error.
            self._link_delete_after.pop(infohash, None)
            self.post_event("log", f"'{name}' was stopped.")
            self.post_event("status", (True, "Ready"))
        except GofileError as exc:
            self._link_delete_after.pop(infohash, None)
            self.post_event("log", str(exc))
            self.post_event("status", (False, f"GoFile upload of '{name}' failed: {exc}"))
            # R26b: a rate limit that survived the quick retries is not a
            # dead end — park the job for a scheduled retry (30 min later).
            if self._gofile_rate_limited(exc):
                self._schedule_gofile_retry(infohash, name, "upload", str(exc))
        except Exception as exc:
            self._link_delete_after.pop(infohash, None)
            self.post_event("log", f"GoFile upload failed: {exc}")
            self.post_event("status", (False, f"GoFile upload of '{name}' failed: {exc}"))
        finally:
            with self._upload_jobs_lock:
                self._upload_jobs.pop(infohash, None)
            self._cancel_forget(infohash)

    # ---- R26b: scheduled GoFile retry queue ----------------------------------

    def _schedule_gofile_retry(self, infohash: str, name: str, kind: str,
                               reason: str) -> None:
        """A GoFile job was still rate-limited after its quick retries: park
        it for a retry GOFILE_RETRY_AFTER from now instead of failing it for
        good. Repeated rate limits re-park the same job (the attempts count
        rides along), and after GOFILE_RETRY_MAX parked retries the job is
        given up with a clear log line. The wait shows up as a scheduled
        state in the downloads table (and the links table for remove jobs),
        which is the user's 'make the status show that it is queued' rule."""
        give_up = False
        when = time.time() + GOFILE_RETRY_AFTER
        with self._gofile_sched_lock:
            entry = self._gofile_scheduled.get(infohash) or {}
            attempts = int(entry.get("attempts") or 0) + 1
            if attempts > GOFILE_RETRY_MAX:
                del self._gofile_scheduled[infohash]
                give_up = True
            else:
                self._gofile_scheduled[infohash] = {
                    "name": name, "kind": kind, "due": when,
                    "attempts": attempts, "reason": reason}
        retry_at = time.strftime("%H:%M", time.localtime(when))
        if give_up:
            self.post_event(
                "log", f"'{name}' was still rate-limited by GoFile after "
                f"{GOFILE_RETRY_MAX} scheduled retries ({reason}); it is not "
                "queued anymore - press Make GoFile link again later.")
            self.post_event("status",
                            (False, f"'{name}' gave up after {GOFILE_RETRY_MAX} "
                             "scheduled GoFile retries"))
        else:
            self.post_event(
                "log", f"'{name}' is queued: still rate-limited by GoFile "
                f"({reason}); scheduled retry {attempts}/{GOFILE_RETRY_MAX} "
                f"at {retry_at}.")
            self.post_event("status",
                            (True, f"'{name}' queued for GoFile: retry at "
                             f"{retry_at}"))
        self.post_event("gofile_scheduled", infohash)

    def _gofile_schedule_tick(self) -> None:
        """One-second tick (runs on the UI thread from _tick_progress): fire
        every scheduled GoFile retry whose time has come. Pure dict reads
        otherwise, so an empty queue costs nothing."""
        now = time.time()
        due: list[tuple[str, dict]] = []
        with self._gofile_sched_lock:
            for infohash, entry in list(self._gofile_scheduled.items()):
                if now >= float(entry.get("due") or 0.0):
                    due.append((infohash, entry))
                    del self._gofile_scheduled[infohash]
        for infohash, entry in due:
            self._gofile_restart_job(infohash, entry)

    def _gofile_restart_job(self, infohash: str, entry: dict) -> None:
        """Re-run a parked job when its retry time arrives. Kind 'upload'
        goes through the ordinary _start_upload path (it re-checks every
        guard); kind 'remove' re-runs the delete worker."""
        name = str(entry.get("name") or infohash)
        kind = str(entry.get("kind") or "upload")
        if kind == "remove":
            record = self.engine.store.get(infohash) or {}
            folder_id = str(record.get("gofile_folder_id") or "")
            if not folder_id and not record.get("gofile_link"):
                return   # the link was removed some other way meanwhile
            threading.Thread(target=self._remove_link_worker,
                             args=(infohash, name, folder_id),
                             daemon=True, name="remove-link-retry").start()
        else:
            self._start_upload(infohash)

    def _gofile_rate_limited(self, message: str) -> bool:
        """True when a GoFile failure is a rate limit (the only failure the
        retry queue handles; other errors fail immediately as before).
        Matches every spelling GoFile uses: "rate limit", "error-rateLimit",
        "rate_limit" — compared with all separators stripped."""
        compressed = "".join(str(message).lower().split())
        return "ratelimit" in compressed

    def _on_gofile_scheduled(self, _payload: object) -> None:
        """Repaint after a job was parked, fired, or given up so the queued/
        scheduled state is visible immediately."""
        self._refresh_downloads_table()
        self._refresh_links_table()

    def _on_gofile_done(self, payload: tuple) -> None:
        infohash, link, name = payload
        with self._gofile_sched_lock:   # R26b: no longer queued if it was
            self._gofile_scheduled.pop(infohash, None)
        self._refresh_downloads_table()
        if link:
            self.log_line("GoFile link ready.")
            self.log_line(link)
            self.set_status(True, "Ready")
        else:
            self.log_line(f"GoFile upload of '{name}' finished but returned no share "
                          "link; try again later.")
            self.set_status(False, "GoFile upload returned no link")

    # ---- unpack --------------------------------------------------------------------------

    def _on_unpack_done(self, payload: tuple) -> None:
        _infohash, name, dest, count = payload
        self._refresh_downloads_table()
        self.log_line(f"Unpacked {count} file(s) to {dest} ('{name}').")
        self.set_status(True, "Ready")

    # ---- presets manager -------------------------------------------------------------------

    def _open_presets_dialog(self) -> None:
        win = tk.Toplevel(self)
        win.title("Presets")
        win.configure(background=Theme.BG)
        win.resizable(False, False)
        win.transient(self)

        list_frame = ttk.Frame(win)
        list_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=14, pady=(12, 5))
        listbox = tk.Listbox(list_frame, height=6, width=56, background=Theme.PANEL,
                             foreground=Theme.TEXT, relief="flat", borderwidth=0,
                             selectbackground=Theme.PANEL2, selectforeground=Theme.TEXT,
                             activestyle="none")
        list_scroll = ttk.Scrollbar(list_frame, command=listbox.yview)
        listbox.configure(yscrollcommand=list_scroll.set)
        listbox.grid(row=0, column=0, sticky="ew")
        list_scroll.grid(row=0, column=1, sticky="ns")
        list_frame.columnconfigure(0, weight=1)

        def reload_list() -> None:
            listbox.delete(0, "end")
            for path in self.presets.list():
                suffix = "  (default)" if path == self.presets.default else ""
                listbox.insert("end", f"{path}{suffix}")

        def selected_path() -> str:
            index = listbox.curselection()
            if not index:
                return ""
            raw = listbox.get(index[0])
            return raw.replace("  (default)", "")

        def add_preset() -> None:
            text = entry.get().strip()
            if not text:
                self.log_line("Preset path is empty; nothing added.")
                return
            if self.presets.add(text):
                self.log_line(f"Preset added: {self.presets.list()[-1]}")
            else:
                self.log_line("That preset already exists.")
            entry.delete(0, "end")
            reload_list()

        def set_default() -> None:
            path = selected_path()
            if not path:
                self.log_line("No preset selected; no default set.")
                return
            self.presets.default = path
            self.log_line(f"Default unpack destination set: {path}")
            reload_list()

        def remove_preset() -> None:
            path = selected_path()
            if not path:
                self.log_line("No preset selected; nothing removed.")
                return
            self.presets.remove(path)
            self.log_line(f"Preset removed: {path}")
            reload_list()

        ttk.Label(win, text="New folder:").grid(row=1, column=0, sticky="w", padx=14, pady=5)
        entry = ttk.Entry(win, width=44)
        entry.grid(row=1, column=1, sticky="ew", padx=(0, 14), pady=5)
        ttk.Button(win, text="Add", command=add_preset).grid(
            row=2, column=0, sticky="ew", padx=14, pady=5)
        ttk.Button(win, text="Set as default", command=set_default).grid(
            row=2, column=1, sticky="ew", padx=(0, 14), pady=5)
        ttk.Button(win, text="Remove", command=remove_preset).grid(
            row=3, column=0, sticky="ew", padx=14, pady=5)
        ttk.Button(win, text="Close", command=win.destroy).grid(
            row=3, column=1, sticky="ew", padx=(0, 14), pady=5)
        win.columnconfigure(1, weight=1)
        reload_list()
        self._center_popup(win)
        win.grab_set()

    # ---- open link ----------------------------------------------------------------------------
    # R24: on_open_link is gone with the stray link label; links open by
    # double-clicking their row in GOFILE (merged, R32).

    # ---- settings popup -------------------------------------------------------------------------

    # Popup fields: (env var name, human label, is_secret). Secrets are shown
    # masked in the entries; their values live only in memory and in .env,
    # and are never printed or logged anywhere.
    SETTINGS_FIELDS = (
        ("TORBOX_API_KEY", "Torbox API key", True),
        ("GOFILE_API_TOKEN", "GoFile API token", True),
        ("QBIT_URL", "qBittorrent WebUI URL", False),
        ("QBIT_PORT", "qBittorrent WebUI port", False),
        ("QBIT_USERNAME", "qBittorrent username", False),
        ("QBIT_PASSWORD", "qBittorrent password", True),
    )

    def _read_env_values(self) -> dict[str, str]:
        """Parse .env into a dict, same rules as Config. In-memory only."""
        values: dict[str, str] = {}
        path = ROOT / ".env"
        if path.exists():
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    values[key.strip()] = val.strip()
            except OSError:
                pass
        return values

    def on_open_settings(self) -> None:
        """Settings cog (round R11, amended R11b): a popup inside the app
        for editing the .env values. The .env file itself is never opened in
        an editor, and no value is ever logged. Saving rewrites .env with the
        known keys filled in, preserving comments and any unknown keys; the
        app picks the new values up on its next start."""
        win = tk.Toplevel(self)
        win.title("Settings")
        win.configure(background=Theme.BG)
        win.resizable(False, False)
        win.transient(self)
        current = self._read_env_values()
        # R45: blank entries must not round-trip as empty .env lines — a
        # saved QBIT_URL= built the URL ":8080/api/…" and broke search
        # ("unknown url type"). Prefill the qBittorrent fields with the
        # same defaults Config applies, so Save writes working values.
        for _name, _default in (("QBIT_URL", "http://127.0.0.1"),
                                ("QBIT_PORT", "8080")):
            if not current.get(_name):
                current[_name] = _default

        ttk.Label(win, text="Edit settings (saved to .env; values are never "
                            "logged).\nRestart the app after saving to apply.",
                  justify="left").grid(row=0, column=0, columnspan=2,
                                       sticky="w", padx=14, pady=(12, 5))
        entries: dict[str, ttk.Entry] = {}
        for row, (name, label, secret) in enumerate(self.SETTINGS_FIELDS, start=1):
            ttk.Label(win, text=f"{label}:").grid(row=row, column=0, sticky="e",
                                                  padx=(14, 6), pady=3)
            entry = ttk.Entry(win, width=44, show="•" if secret else "")
            entry.insert(0, current.get(name, ""))
            entry.grid(row=row, column=1, sticky="ew", padx=(0, 14), pady=3)
            entries[name] = (entry, secret)

        show_var = tk.BooleanVar(value=False)

        def toggle_show() -> None:
            for entry, secret in entries.values():
                if secret:
                    entry.configure(show="" if show_var.get() else "•")

        ttk.Checkbutton(win, text="Show secret values", variable=show_var,
                        command=toggle_show).grid(
            row=len(self.SETTINGS_FIELDS) + 1, column=0, columnspan=2,
            sticky="w", padx=14, pady=(4, 2))

        # R18: the manual forced translation pass, kept "just in case" per
        # the user. Re-runs every cached Torbox title through the translator
        # (network permitting) instead of trusting the disk cache.
        ttk.Button(win, text="Translate titles now", width=20,
                   command=self.on_settings_translate).grid(
            row=len(self.SETTINGS_FIELDS) + 2, column=0, columnspan=2,
            sticky="w", padx=14, pady=(4, 2))

        # R19: the manual forced plugin-update pass, alongside the one that
        # runs automatically at startup. Uses qBittorrent's own update
        # mechanism (each plugin is re-fetched from its source and replaced
        # only when a newer version exists).
        ttk.Button(win, text="Update search plugins now", width=24,
                   command=self.on_settings_update_plugins).grid(
            row=len(self.SETTINGS_FIELDS) + 3, column=0, columnspan=2,
            sticky="w", padx=14, pady=(4, 2))

        # R36: what a handed-off torrent (a .torrent opened from the file
        # manager or a magnet: link) does once it is cached on Torbox. No
        # GoFile option here — a GoFile link can never be the default (user
        # rule); the handoff popup's checkbox is the only way to add one.
        handoff_labels = {"ask": "Ask every time", "pc": "Download to PC",
                          "torbox": "Keep on Torbox"}
        label_to_value = {v: k for k, v in handoff_labels.items()}
        handoff_row = len(self.SETTINGS_FIELDS) + 4
        ttk.Label(win, text="Handoff default:").grid(
            row=handoff_row, column=0, sticky="e", padx=(14, 6), pady=(8, 3))
        handoff_var = tk.StringVar(
            value=handoff_labels.get(self._handoff_default_mode(),
                                     "Ask every time"))
        ttk.Combobox(win, state="readonly", textvariable=handoff_var, width=24,
                     values=("Ask every time", "Download to PC",
                             "Keep on Torbox")).grid(
            row=handoff_row, column=1, sticky="w", padx=(0, 14), pady=(8, 3))

        ttk.Button(win, text="Register file associations", width=24,
                   command=self.on_register_associations).grid(
            row=handoff_row + 1, column=0, columnspan=2,
            sticky="w", padx=14, pady=(4, 2))

        def save() -> None:
            # Read the values FIRST — after destroy() the entries are gone.
            values = {name: entry.get().strip()
                      for name, (entry, _secret) in entries.items()}
            values["HANDOFF_DEFAULT"] = label_to_value.get(
                handoff_var.get(), "ask")
            # The default applies right away; no restart needed for it.
            self._handoff_default_setting = values["HANDOFF_DEFAULT"]
            win.destroy()
            threading.Thread(target=self._settings_save_worker, args=(values,),
                             daemon=True, name="settings-save").start()

        button_row = len(self.SETTINGS_FIELDS) + 6
        ttk.Button(win, text="Save", command=save).grid(
            row=button_row, column=0, sticky="ew", padx=(14, 4), pady=(6, 12))
        ttk.Button(win, text="Cancel", command=win.destroy).grid(
            row=button_row, column=1, sticky="ew", padx=(4, 14), pady=(6, 12))
        win.columnconfigure(1, weight=1)
        self._center_popup(win)
        win.grab_set()

    def _settings_save_worker(self, values: dict[str, str]) -> None:
        """Daemon: rewrite .env with the six known keys, preserving comment
        lines, blank lines and any unknown keys. Atomic replace; file mode
        tightened where the OS honors it. No value is ever logged."""
        try:
            path = ROOT / ".env"
            known = [name for name, _label, _secret in self.SETTINGS_FIELDS]
            old_lines: list[str] = []
            if path.exists():
                try:
                    old_lines = path.read_text(encoding="utf-8").splitlines()
                except OSError:
                    old_lines = []
            out: list[str] = []
            seen: set[str] = set()
            for line in old_lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in values:
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append(f"{key}={values[key]}")
                        continue
                out.append(line)
            for name in known:
                if name not in seen:
                    out.append(f"{name}={values[name]}")
            # R36: HANDOFF_DEFAULT (and any other provided key outside the
            # known six) is written too when the file does not have it yet.
            for name in sorted(values):
                if name not in seen and name not in known:
                    out.append(f"{name}={values[name]}")
            tmp = path.with_suffix(".env.tmp")
            tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, path)
            self.post_event("log", "Settings saved to .env (values never "
                                   "logged). Restart the app to apply them; "
                                   "the handoff default applies right away.")
            self.post_event("status", (True, "Settings saved — restart to apply."))
        except Exception as exc:
            self.post_event("log", f"Could not save settings: {exc}")
            self.post_event("status", (False, f"Saving settings failed: {exc}"))

    # ---- remove from PC ----------------------------------------------------------------------------

    def on_remove_pc(self) -> None:
        """'Remove from PC': confirm, then delete the selected download's
        local files. R24: when the record still has a live GoFile link the
        list entry and the link STAY (only the local copy goes); without a
        link the list entry is removed too. The Torbox account is NOT
        touched either way."""
        record = self._selected_record()
        if record is None:
            self.log_line("No download selected; nothing to remove.")
            return
        name = record.get("name") or record["infohash"]
        has_link = bool(record.get("gofile_link"))
        if has_link:
            text = (f"Delete {name}'s files from this PC?\nThe list entry "
                    "and its GoFile link stay; the Torbox account is not "
                    "touched.")
        else:
            text = (f"Delete {name}'s files from this PC and remove it "
                    "from the list?\nThe Torbox account is not touched.")
        win = tk.Toplevel(self)
        win.title("Remove from PC")
        win.configure(background=Theme.BG)
        win.resizable(False, False)
        win.transient(self)
        ttk.Label(win, text=text, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 5))

        def yes() -> None:
            win.destroy()
            self.set_status(True, f"Removing {name} from this PC…")
            self.log_line(f"Removing '{name}' from this PC…")
            threading.Thread(target=self._remove_worker, args=(record["infohash"], name),
                             daemon=True, name="remove-pc").start()

        ttk.Button(win, text="Yes", command=yes).grid(row=1, column=0,
                                                      sticky="ew", padx=(14, 4), pady=(5, 12))
        ttk.Button(win, text="No", command=win.destroy).grid(row=1, column=1,
                                                             sticky="ew", padx=(4, 14), pady=(5, 12))
        win.columnconfigure(0, weight=1)
        win.columnconfigure(1, weight=1)
        self._center_popup(win)
        win.grab_set()

    def _delete_local_folder_guarded(self, folder: str) -> str:
        """Delete a local folder ONLY when it sits inside the engine's
        download root; anything outside the root is refused, never deleted.
        Returns a short detail string for the log."""
        if not folder:
            return "no local folder recorded"
        root = self.engine.download_root.resolve()
        try:
            target = Path(folder).resolve()
        except OSError:
            return f"folder refused (unreadable path, not deleted): {folder}"
        if not (target != root and root in target.parents):
            return (f"folder refused (outside the download root, "
                    f"not deleted): {folder}")
        try:
            shutil.rmtree(target)
            return f"folder deleted: {folder}"
        except OSError as exc:
            return f"folder could not be deleted: {exc}"

    def _remove_worker(self, infohash: str, name: str) -> None:
        """Daemon: delete the record's local folder — but ONLY when the
        folder sits inside the engine's download root; anything outside the
        root is refused, never deleted. R24: with a live GoFile link the
        record and the link STAY (held, re-fetchable); without a link the
        list entry is dropped too. The Torbox account is never contacted."""
        try:
            record = self.engine.store.get(infohash)
            if record is None:
                self.post_event("log",
                                f"'{name}' is not in the list anymore; nothing to remove.")
                return
            has_link = bool(record.get("gofile_link"))
            detail = self._delete_local_folder_guarded(
                str(record.get("folder") or ""))
            if has_link:
                self.engine.store.update(infohash, folder="", status="held",
                                         unpacked=False)
                detail += "; the GoFile link and the list entry stay"
            else:
                self.engine.store.delete(infohash)  # the list entry goes too
            self.post_event("remove_done", (infohash, name, detail))
        except Exception as exc:
            self.post_event("log", str(exc) or type(exc).__name__)
            self.post_event("status", (False, f"Removing '{name}' failed: {exc}"))

    def _on_remove_done(self, payload: tuple) -> None:
        _infohash, name, detail = payload
        self._known_status.pop(_infohash, None)
        self._asked_complete.discard(_infohash)
        self._refresh_downloads_table()
        self.log_line(f"Removed '{name}' from this PC. {detail}")
        self.set_status(True, "Ready")

    # ---- Remove link (R24) -------------------------------------------------------------------------

    def on_remove_link(self) -> None:
        """R24 'Remove link' (R25 updated, R32 re-homed): delete the
        selected row's GoFile content server-side, then clear the link.
        R33: the button is gone (user request) — GoFile-side deletion now
        runs through Delete in GOFILE, and this dialog method is kept only
        for reference; the scheduled-retry "remove" path calls
        _remove_link_worker directly. Links made through this PC carry a
        folder UUID and delete directly; a direct Torbox->GoFile link is a
        bare /d/ code that the signed free-tier read resolves to its folder
        first (proven live). If the resolution is refused (rate limit, gate
        change) the row is kept and the log says what to do. The Torbox
        account is never touched. R32: the selection comes from the merged
        GOFILE tree now."""
        sel = self.gofile_tree.selection()
        node = self._gofile_nodes.get(sel[0]) if sel else None
        if node is None:
            self.log_line("Click a row in GOFILE first, then press "
                          "Remove link.")
            return
        infohash = str(node.get("infohash") or "")
        name = str(node.get("name") or "")
        if not infohash:
            self.log_line(f"'{name}' has no local record (it lives only in "
                          "your GoFile account) — press Delete to remove it "
                          "from GoFile instead.")
            return
        record = self.engine.store.get(infohash) or {}
        if not record.get("gofile_link"):
            self.log_line(f"'{name}' has no live GoFile link; nothing to "
                          "remove.")
            return
        folder_id = str(record.get("gofile_folder_id") or "")
        if folder_id:
            text = (f"Delete {name}'s files from GoFile and remove the "
                    "link?\nThe Torbox account is not touched. Local files "
                    "on this PC are not touched either.")
        else:
            text = (f"Delete {name}'s files from GoFile and remove the "
                    "link?\nThis link was made by Torbox itself, so its "
                    "folder is looked up from the share code first — if "
                    "GoFile refuses, the row stays and you can retry later.")
        win = tk.Toplevel(self)
        win.title("Remove link")
        win.configure(background=Theme.BG)
        win.resizable(False, False)
        win.transient(self)
        ttk.Label(win, text=text, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 5))

        def yes() -> None:
            win.destroy()
            self.set_status(True, f"Removing {name}'s GoFile link…")
            self.log_line(f"Removing '{name}'s GoFile link…")
            threading.Thread(target=self._remove_link_worker,
                             args=(infohash, name, folder_id),
                             daemon=True, name="remove-link").start()

        ttk.Button(win, text="Yes", command=yes).grid(row=1, column=0,
                                                      sticky="ew", padx=(14, 4), pady=(5, 12))
        ttk.Button(win, text="No", command=win.destroy).grid(row=1, column=1,
                                                             sticky="ew", padx=(4, 14), pady=(5, 12))
        win.columnconfigure(0, weight=1)
        win.columnconfigure(1, weight=1)
        self._center_popup(win)
        win.grab_set()

    def _remove_link_worker(self, infohash: str, name: str,
                            folder_id: str) -> None:
        """Daemon: delete the GoFile content, then clear the link fields.
        R25: a bare /d/ short code (direct Torbox->GoFile drops) is resolved
        to its folder UUID first through the signed free-tier read, so every
        link is deletable from here now. A record with local files on disk
        stays live (it shows 'On PC' again); one without goes to archived,
        like the old expiry pass did."""
        try:
            record = self.engine.store.get(infohash) or {}
            link = str(record.get("gofile_link") or "")
            detail = "nothing to delete"
            ok = False
            if folder_id or link:
                try:
                    ok, detail = self.gofile.delete_link(folder_id, link)
                except Exception as exc:
                    ok = False
                    detail = (f"GoFile refused ({str(exc) or type(exc).__name__}) "
                              "— try again, or delete the files at gofile.io")
                if not ok:
                    self.post_event("log", f"Could not delete '{name}' from "
                                    f"GoFile: {detail}. The link row was "
                                    "kept — try again or delete the files "
                                    "at gofile.io.")
                    self.post_event("status",
                                    (False, f"Removing '{name}' failed"))
                    # R26b: a rate limit goes to the scheduled retry queue
                    # instead of waiting for a manual retry.
                    if self._gofile_rate_limited(detail):
                        self._schedule_gofile_retry(infohash, name, "remove",
                                                    detail)
                    return
            try:
                has_local = (bool(record.get("folder"))
                             and Path(str(record["folder"])).is_dir())
            except OSError:
                has_local = False
            self.engine.store.update(
                infohash, gofile_link=None, gofile_folder_id=None,
                gofile_created=None, archived=not has_local,
                gofile_removed_at=_utc_now_iso())
            self.post_event("remove_link_done", (infohash, name, detail))
        except Exception as exc:
            self.post_event("log", str(exc) or type(exc).__name__)
            self.post_event("status", (False, f"Removing '{name}' failed: {exc}"))

    def _on_remove_link_done(self, payload: tuple) -> None:
        infohash, name, detail = payload
        with self._gofile_sched_lock:   # R26b: no longer queued if it was
            self._gofile_scheduled.pop(infohash, None)
        self._known_status.pop(infohash, None)
        self._refresh_downloads_table()
        self._refresh_links_table()
        self.log_line(f"Removed '{name}'s GoFile link. {detail}.")
        self.set_status(True, "Ready")

    # ---- shutdown -----------------------------------------------------------------------------------

    def on_close(self) -> None:
        self._closing = True
        self._stop_poll.set()
        # R23: end every in-flight job the Stop button could have stopped,
        # so the workers exit instead of streaming on behind the window.
        with self._cancel_lock:
            events = list(self._cancel_events.values())
        for event in events:
            event.set()
        # R17: end any in-flight Translate pass cleanly; the disk cache was
        # already saved incrementally (every 25 titles) and once more here.
        self._torbox_translate_stop.set()
        try:
            self._torbox_en.save()
        except Exception:
            pass
        try:
            self.engine.shutdown(wait=False)
        except Exception:
            pass
        self.destroy()


# Taskbar identity on Windows. Both halves must match for Windows to show
# the app icon on the taskbar button: the window/process declares this
# AppUserModelID, and a Start Menu shortcut (tools/register-shortcut.ps1)
# carries the same System.AppUserModel.ID property plus the app icon.
# With the AUMID but no shortcut, Windows cannot resolve the identity and
# falls back to pythonw.exe's Python logo (verified live, R11); with the
# shortcut registered, the taskbar button takes the shortcut's icon and name.
TASKBAR_AUMID = "Thaura.TorboxDownloader"


def _ensure_windows_taskbar_identity() -> None:
    """Declare the app AUMID and quietly register its Start Menu shortcut.

    The shortcut is what Windows resolves the taskbar button from. If it is
    missing (fresh machine, or deleted) this re-registers it once; re-running
    tools/register-shortcut.ps1 is needed only after a Python upgrade moves
    the interpreter path. Cosmetic only, never blocks startup.
    """
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(TASKBAR_AUMID)
    except Exception:
        pass
    try:
        if getattr(sys, "frozen", False):
            # R38: a packed exe carries its own icon; the shortcut
            # registration below targets a Python interpreter script and
            # does not apply to a frozen build.
            return
        script = Path(__file__).resolve()
        app_dir = script.parent
        programs = (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows"
                    / "Start Menu" / "Programs")
        lnk = programs / "Torbox Downloader.lnk"
        reg = Path(__file__).resolve().parent.parent / "tools" / "register-shortcut.ps1"
        if reg.exists() and not lnk.exists():
            subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(reg),
                 "-Target", sys.executable,
                 "-Arguments", '"' + str(script) + '"',
                 "-WorkDir", str(app_dir),
                 "-Icon", str(app_dir / "icon.ico")],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def main() -> None:
    if sys.platform == "win32":
        _ensure_windows_taskbar_identity()
    # R36: single-instance handoff. A second launch (a double-clicked
    # .torrent or an opened magnet: link) forwards its arguments to the
    # running app over a localhost socket and exits; the first instance
    # stays the only app. With nothing running, this instance claims the
    # port and becomes the app, keeping its own command-line items (the
    # app-closed-then-double-click case) for its UI to consume.
    peer = handoff.SingleInstance(on_items=None)
    peer.startup_items = handoff.parse_cli_args(sys.argv[1:])
    if not peer.claim():
        if peer.startup_items:
            handoff.send_items(peer.startup_items)
        return
    # R36: first-run wizard — "everything is done at startup, so that the
    # user doesn't have to do anything manually." Skippable: closing it
    # starts the app degraded, and Settings can fill the keys in later.
    config = Config()
    if not config.has("TORBOX_API_KEY"):
        wizard.run_startup_wizard(config.env_path)
        config = Config()
    app = App(config, handoff_instance=peer)
    app.mainloop()


if __name__ == "__main__":
    main()
