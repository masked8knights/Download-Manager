"""Game/version tag extraction from release names (R16, todo item 7).

The user asked for the emulator-style "which version is this" display for
legal-commons games (the No-Intro / Redump convention). Torrent result
names carry that information as parenthesized tags, e.g.

    Super Game (Europe) (Rev 1) (En,Fr,De)
    Some Game v1.2 (USA) (Update)
    Loader (World) (Unl)

version_tags() parses those tags out of a name and returns one short
display string ("Europe · Rev 1 · En,Fr"), or "" when the name carries
none. It is pure text parsing: no network, no checksum DAT files. The
name itself is always shown in full elsewhere, so a tag that is missed
only means the version column stays empty for that row.

Parsing rules, matching the No-Intro/Redump naming standard:
- region/country tags: (USA), (Europe), (Japan), (World), (Spain)... plus
  multi-country "(USA, Europe)".
- revision/version: (Rev 1), (Rev A), (R1), (v1.02), (Beta), (Proto),
  (Sample), (Demo), (Trade Demo), (Update), (Patch), (Superset).
- language: (En,Fr,De), (En,Ja) — 2/3-letter codes, comma separated.
- special markers: (Unl), (Pirate), (Aftermarket), (DLC), (Homebrew).
- anything else in parentheses (scene group names, codec tags, years) is
  left alone: it is not version information.

No secrets are ever handled or printed by this module.
"""

from __future__ import annotations

import re

__all__ = ["version_tags", "game_version"]

_REGIONS = {
    "usa", "europe", "japan", "world", "asia", "australia", "brazil",
    "canada", "china", "france", "germany", "greece", "hong kong",
    "italy", "korea", "netherlands", "poland", "russia", "scandinavia",
    "spain", "sweden", "taiwan", "uk", "united kingdom", "nsw",
}
_SPECIAL = {
    "unl", "unlicensed", "pirate", "aftermarket", "dlc", "homebrew",
    "beta", "proto", "prototype", "sample", "demo", "trade demo",
    "update", "patch", "superset", "rev 0", "rev a", "rev b", "rev c",
}
_LANG = re.compile(r"^[A-Z][a-z]{1,3}$")   # En, Fr, De, Ja, Zh, Pt...
_REV = re.compile(r"^(?:rev(?:ision)?\s*[0-9a-z]|r[0-9])$", re.IGNORECASE)
_VER = re.compile(r"^v[0-9]", re.IGNORECASE)
_YEAR = re.compile(r"^(19|20)[0-9]{2}$")
_LANG_LIST = re.compile(r"^[A-Z][a-z]{1,2}(?:,[A-Z][a-z]{1,2}){1,6}$")
_MULTI = re.compile(r"^MULTI?([0-9]+)?$", re.IGNORECASE)   # (MULTi5), MULTI7
_PAREN = re.compile(r"\(([^()]*)\)")

# R16b second pass: scene-style names ("Game.Name.USA.MULTI5.PS3-CLANDESTiNE")
# carry the same facts without parentheses. Tokens scanned in the bare name
# when the parenthesized pass finds nothing.
_REGION_CODES = {
    "usa", "us", "eur", "europe", "euro", "jpn", "jap", "japan", "pal",
    "ntsc", "ntsc-u", "ntsc-j", "asia", "kor", "ger", "fra", "ita", "esp",
    "swe", "aus", "can", "world",
}
_BARE_REGION = re.compile(r"\b(ntsc-[uj])\b|\b([a-z]{2,6})\b", re.IGNORECASE)
_BARE_VER = re.compile(r"\bv(?:er(?:sion)?)?\.?\s?(\d+(?:\.\d+)*)\b",
                       re.IGNORECASE)
_BARE_REV = re.compile(r"\brev(?:ision)?\.?\s?(\d|[a-e])\b", re.IGNORECASE)
_BARE_MULTI = re.compile(r"\bMULTI?([0-9]+)?\b", re.IGNORECASE)

_ORDER = ("region", "rev", "ver", "lang", "special")


def _tag_kind(tag: str) -> str:
    """Classify one parenthesized tag, or "" when it is not version info."""
    t = tag.strip()
    if not t:
        return ""
    low = t.lower()
    if low in _REGIONS:
        return "region"
    if low in _SPECIAL or _REV.match(t):
        return "rev"
    if _VER.match(t):
        return "ver"
    if _LANG_LIST.match(t) or _LANG.match(t):
        return "lang"
    if _MULTI.match(t):
        return "lang"
    if _YEAR.match(t):
        return ""
    # Multi-country region lists like "(USA, Europe)".
    parts = [p.strip().lower() for p in t.split(",")]
    if len(parts) > 1 and all(p in _REGIONS for p in parts):
        return "region"
    return ""


def _scan_bare(name: str) -> dict:
    """Second pass over a scene-style name with no useful parenthesized
    tags: find region codes (USA / EUR / PAL / NTSC-U...), a bare version
    (v1.02, version 2), a bare revision (Rev 2) and a language count
    (MULTI5). Deliberately conservative — each kind reported at most once,
    and only the first hit per kind wins."""
    found: dict = {}
    for token in re.split(r"[^A-Za-z0-9\-]+", name):
        if token and token.lower() in _REGION_CODES:
            found["region"] = token.upper().replace("USA", "USA")
            break
    match = _BARE_REV.search(name)
    if match:
        found["rev"] = "Rev " + match.group(1).upper()
    match = _BARE_VER.search(name)
    if match:
        found["ver"] = "v" + match.group(1)
    match = _BARE_MULTI.search(name)
    if match:
        count = match.group(1)
        found["lang"] = f"Multi {count}" if count else "Multi"
    return found


def version_tags(name: str) -> str:
    """Pull the emulator-style version tags out of a release name.

    Returns one display string in the order region · rev/version ·
    language · special, with " · " separators, or "" when nothing in the
    name is version information.

    Two passes: parenthesized No-Intro/Redump tags first; when the name
    carries none, a scene-style scan of the bare name (region codes, bare
    versions, MULTI language counts). A name that carries NO version
    information in any form still returns "" — that fact is not knowable
    from the name alone (see the checksum/DAT note in todo.md)."""
    if not name:
        return ""
    found: dict = {}
    for match in _PAREN.finditer(str(name)):
        kind = _tag_kind(match.group(1))
        if kind:
            found.setdefault(kind, match.group(1).strip())
    if not found:
        found = _scan_bare(str(name))
    return " · ".join(found[k] for k in _ORDER if k in found)


# R17: the Version column shows the game's own version/update NUMBER
# ("v1.0.1"), not the region/language tags. Scene-style names carry the
# same numbers without parentheses; both forms are scanned here.
_GAME_VER = re.compile(
    r"\bv(?:er(?:sion)?)?\.?\s?(\d+(?:\.\d+){1,3})\b", re.IGNORECASE)
_GAME_UPDATE = re.compile(
    r"\b(?:update|upd)[.\s]?v?(\d+(?:\.\d+){0,3})\b", re.IGNORECASE)
_GAME_BUILD = re.compile(
    r"\bbuild[.\s]?(\d+(?:\.\d+){0,3})\b", re.IGNORECASE)
# A bare dotted number is only trusted with two dots or more (1.0.1),
# so years and resolutions never read as versions.
_GAME_BARE = re.compile(r"\b(\d+\.\d+\.\d+(?:\.\d+)?)\b")


def game_version(name: str) -> str:
    """The game's version/update number from a release name, or ''.

    Reads the number forms players mean by "which version is this":
    v1.0.1 / ver 2.1 / version 1.2.3, Update 4, Build 12345, and bare
    dotted numbers like 1.0.5. Works on both parenthesized
    ("Some Game (v1.0.1)") and scene-style ("Game.Name.v1.0.1-GOG")
    names. Returns the display string ("v1.0.1", "Update 4",
    "Build 12345"), or "" when the name carries no version number."""
    if not name:
        return ""
    text = str(name)
    match = _GAME_VER.search(text)
    if match:
        return "v" + match.group(1)
    match = _GAME_UPDATE.search(text)
    if match:
        return "Update " + match.group(1)
    match = _GAME_BUILD.search(text)
    if match:
        return "Build " + match.group(1)
    match = _GAME_BARE.search(text)
    if match:
        return "v" + match.group(1)
    return ""
