"""Preset unpack destinations (task 6, app/presets.py).

A tiny Presets class backed by one JSON file at the project root
(presets.json). It holds folder paths only — no secrets ever go in this
file. Exactly one preset is the default, or none is.

Schema: {"presets": ["C:\\Users\\<you>\\Downloads", ...], "default": "..."}

- load() tolerates a missing or broken file (starts empty, never crashes).
- save() is atomic: writes presets.json.tmp, then os.replace()s it over
  the real file, so a crash mid-save leaves the previous file intact.
- On first load with no presets, one default is seeded: the app's
  downloads folder (project_root / "downloads"), created if missing. Its
  absolute path is stored as both a preset and the default. On Windows
  the app runs from a folder of its own on the PC, so this resolves
  to that folder's downloads\\ subfolder there.

This module is standalone on purpose: it imports nothing from sibling app
modules, so test scripts can import it directly via sys.path.

No secrets are ever printed or logged by this module.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from apppaths import ROOT  # R38: frozen-aware writable root

PRESETS_PATH = ROOT / "presets.json"


class Presets:
    """Folder presets for the unpack destination, persisted atomically."""

    def __init__(self, path: str | os.PathLike | None = None,
                 seed_dir: str | os.PathLike | None = None) -> None:
        self.path = Path(path) if path is not None else Path(PRESETS_PATH)
        self._items: list[str] = []
        self._default: str = ""
        self.load()
        if not self._items:
            seed = Path(seed_dir) if seed_dir is not None else ROOT / "downloads"
            seed = Path(seed).expanduser()
            seed.mkdir(parents=True, exist_ok=True)
            self._items = [str(seed)]
            self._default = str(seed)
            self.save()

    # ------------------------------------------------------------ persistence

    def load(self) -> None:
        """Read presets.json; a missing or broken file starts empty."""
        self._items, self._default = [], ""
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            return  # broken file: start empty, never crash
        if not isinstance(data, dict):
            return
        items = data.get("presets")
        if isinstance(items, list):
            self._items = [str(p) for p in items if str(p).strip()]
        default = data.get("default")
        if isinstance(default, str) and default in self._items:
            self._default = default

    def save(self) -> None:
        """Write presets.json atomically (tmp file, then os.replace)."""
        payload = {"presets": self._items, "default": self._default}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, self.path)

    # ---------------------------------------------------------------- mutators

    def list(self) -> list[str]:
        """A copy of the preset folder paths."""
        return list(self._items)

    def add(self, path: str) -> bool:
        """Add a folder path (no duplicates). First preset becomes the default."""
        text = str(Path(str(path).strip()).expanduser()) if str(path).strip() else ""
        if not text or text in self._items:
            return False
        self._items.append(text)
        if not self._default:
            self._default = text
        self.save()
        return True

    def remove(self, path: str) -> bool:
        """Remove a preset; a removed default leaves no default."""
        text = str(path)
        if text not in self._items:
            return False
        self._items.remove(text)
        if self._default == text:
            self._default = ""
        self.save()
        return True

    @property
    def default(self) -> str:
        """The default preset path, or '' when none is set."""
        return self._default

    @default.setter
    def default(self, path: str) -> None:
        """Set the default; the path is added as a preset when new."""
        text = str(Path(str(path).strip()).expanduser()) if str(path).strip() else ""
        if text and text not in self._items:
            self._items.append(text)
        self._default = text
        self.save()
