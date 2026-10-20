"""Loads .env from the project root. Values are never printed or logged; only their presence.

.env variable names read here (names only, values live in .env itself):
TORBOX_API_KEY, GOFILE_API_TOKEN, QBIT_URL, QBIT_PORT, QBIT_USERNAME,
QBIT_PASSWORD, GOFILE_TTL_DAYS."""

from pathlib import Path

from apppaths import USER_ROOT

# R38: writable root. From source this is the project root; in a frozen
# build it is the folder holding the executable, so .env persists there.
ROOT = USER_ROOT
ENV_PATH = ROOT / ".env"


class Config:
    def __init__(self, env_path: Path = ENV_PATH):
        self.env_path = env_path
        self._values: dict[str, str] = {}
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                self._values[key.strip()] = val.strip()

    def has(self, name: str) -> bool:
        return bool(self._values.get(name, "").strip())

    # Secrets
    @property
    def torbox_api_key(self) -> str:
        return self._values.get("TORBOX_API_KEY", "")

    @property
    def gofile_api_token(self) -> str:
        return self._values.get("GOFILE_API_TOKEN", "")

    # Not secrets
    @property
    def qbit_url(self) -> str:
        # R45: an EMPTY QBIT_URL= line (the Settings popup writes every
        # known key, blank ones included) must fall back to the default
        # just like a missing one — a bare "" built the URL ":8080/api/…"
        # and broke search with "unknown url type".
        value = str(self._values.get("QBIT_URL", "") or "").strip().rstrip("/")
        return value or "http://127.0.0.1"

    @property
    def qbit_port(self) -> int:
        try:
            return int(self._values.get("QBIT_PORT", "8080"))
        except ValueError:
            return 8080

    @property
    def qbit_username(self) -> str:
        return self._values.get("QBIT_USERNAME", "")

    @property
    def qbit_password(self) -> str:
        return self._values.get("QBIT_PASSWORD", "")

    @property
    def gofile_ttl_days(self) -> int:
        """Days a GoFile folder lives before the scheduler archives it.

        GOFILE_TTL_DAYS in .env, integer, default 30. A missing or invalid
        value falls back to 30 silently (a non-integer or a non-positive one
        is invalid; no error is surfaced for a preference like this)."""
        try:
            value = int(str(self._values.get("GOFILE_TTL_DAYS", "30")).strip())
        except ValueError:
            return 30
        if value <= 0:
            return 30
        return value

    @property
    def handoff_default(self) -> str:
        """What a handed-off torrent does once it is cached on Torbox (R36).

        HANDOFF_DEFAULT in .env: "ask" (popup), "pc" (download to this PC),
        "torbox" (leave it on the account). Anything else reads as "ask".
        There is deliberately no GoFile option here — the user's rule is
        that a GoFile link can never be the default behavior."""
        value = str(self._values.get("HANDOFF_DEFAULT", "")).strip().lower()
        return value if value in ("ask", "pc", "torbox") else "ask"
