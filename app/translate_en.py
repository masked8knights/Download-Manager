"""English titles for non-English torrent names (R17).

The user's Torbox account holds releases named in other languages; an
English query ("the lion king") finds nothing in "Le.Roi.Lion.1994.FRENCH".
This module translates release titles to English and caches every result
on disk, so each title is translated once for the life of the project.
The TORBOX FILES pane shows the English title in its own column and the
search matches both the original and the English text.

Translator: Google's public keyless translate endpoint
(translate.googleapis.com, client=gtx) over plain urllib. It is
unofficial and can throttle or vanish; every failure is non-fatal here —
the row just keeps showing its original name, and the warm-up loop stops
after repeated failures rather than hammering.

PRIVACY NOTE (stated to the user when built): translating a title sends
that title text to Google's translator. Only release names go; nothing
else about the account, and no secret ever passes through this module.
The cache file lives next to the app's own data and holds only
original → English title pairs.

No secrets are ever printed or logged by this module.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

__all__ = ["TranslateError", "translate_text", "TitleTranslations"]

TRANSLATE_URL = ("https://translate.googleapis.com/translate_a/single"
                 "?client=gtx&sl=auto&tl=en&dt=t&q=")
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "TorboxDownloader/1.0")


class TranslateError(Exception):
    """Raised when the translator is unreachable or answers oddly."""


def translate_text(text: str, timeout: float = 10.0) -> str:
    """Translate one title to English (auto-detect source language)."""
    clean = str(text).strip()
    if not clean:
        return ""
    url = TRANSLATE_URL + urllib.parse.quote(clean)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    # Response shape: [[["translated","source",...],["more","source",...]],
    #                  ...] — join the translated segments of segment 0.
    if (not isinstance(data, list) or not data
            or not isinstance(data[0], list)):
        raise TranslateError("translator response shape unexpected")
    parts = [seg[0] for seg in data[0]
             if isinstance(seg, list) and seg and isinstance(seg[0], str)]
    english = "".join(parts).strip()
    if not english:
        raise TranslateError("translator returned an empty translation")
    return english


class TitleTranslations:
    """original title → English title, cached atomically on disk.

    get() is safe from any thread; put() records and periodically saves.
    save() writes to <path>.tmp then os.replace, so a crash mid-write
    never corrupts the cache."""

    def __init__(self, path, save_every: int = 25):
        self._path = Path(path)
        self._save_every = max(1, int(save_every))
        self._lock = threading.Lock()
        self._map: dict = {}
        self._dirty = 0
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._map = {str(k): str(v) for k, v in data.items()}
        except Exception:
            self._map = {}

    def get(self, original: str):
        with self._lock:
            return self._map.get(str(original))

    def put(self, original: str, english: str) -> None:
        with self._lock:
            key = str(original)
            if not key or self._map.get(key) == str(english):
                return
            self._map[key] = str(english)
            self._dirty += 1
            if self._dirty >= self._save_every:
                self._save_locked()

    def save(self) -> None:
        with self._lock:
            self._save_locked()

    def _save_locked(self) -> None:
        self._dirty = 0
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._map, ensure_ascii=False,
                                      indent=0), encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception:
            # A cache that cannot be written is not fatal: translations
            # still work for this session and are retried next run.
            pass

    def __len__(self) -> int:
        with self._lock:
            return len(self._map)


def warm_up(titles: list, cache: TitleTranslations, translate=None,
            delay: float = 0.35, progress=None, done=None,
            stop=None, force: bool = False) -> None:
    """Translate uncached titles one by one, calling progress(done, total)
    roughly every ten items and done(failed: bool) at the end. Designed to
    run inside a daemon thread. Stops after two consecutive failures.
    force=True re-translates every title even when the cache has it (the
    settings popup's manual pass)."""
    worker = translate or translate_text
    total = 0
    for title in titles:
        if stop is not None and stop.is_set():
            return
        if not force and cache.get(title) is not None:
            continue
        total += 1
    if total == 0:
        if done is not None:
            done(False)
        return
    failures = 0
    completed = 0
    for index, title in enumerate(titles):
        if stop is not None and stop.is_set():
            return
        if not force and cache.get(title) is not None:
            continue
        try:
            cache.put(title, worker(title))
            failures = 0
        except Exception:
            failures += 1
            if failures >= 2:
                if done is not None:
                    done(True)
                return
            time.sleep(delay * 4)
        completed += 1
        time.sleep(delay)
        if progress is not None and (completed % 10 == 0 or completed == total):
            progress(completed, total)
    cache.save()
    if done is not None:
        done(False)
