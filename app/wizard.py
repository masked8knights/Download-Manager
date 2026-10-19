"""app/wizard.py: the first-run startup wizard (R36).

The user's rule: "everything is done at startup, so that the user doesn't
have to do anything manually." So when the app starts without a Torbox API
key, main() opens this small centered dialog BEFORE the main window builds:
the user pastes their Torbox API key (and, optionally, a free-tier GoFile
token), Save writes them into .env with comments and unknown keys
preserved, and the main window then builds with the real Config — no
restart ever needed, because nothing has started yet.

Values are masked (show="*"), never printed, never logged, and never
returned to the caller in any form; the module communicates success with a
plain True. Skippable: closing the window or pressing Skip starts the app
degraded, exactly as previous rounds did, and Settings can fill the keys
in later."""

from pathlib import Path
import tkinter as tk
from tkinter import ttk

# The keys this wizard writes. Names only — the values live in .env alone.
_WIZARD_KEYS = ("TORBOX_API_KEY", "GOFILE_API_TOKEN")


def merge_env(path: Path, updates: dict) -> bool:
    """Write NAME=value pairs into a .env file, preserving comments and any
    unknown keys. Empty or missing values are skipped (an empty GoFile box
    must not clobber an existing token with nothing). Returns True when the
    file now exists with at least one of the updates applied. Values are
    never echoed anywhere; the return value is all the caller sees."""
    updates = {k: str(v).strip() for k, v in dict(updates).items()
               if str(v or "").strip()}
    if not updates:
        return False
    lines: list[str] = []
    if path.exists():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
    # The values are masked in the UI and are never logged; the only copy
    # on disk is this file, as with the Settings editor.
    pending = dict(updates)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.partition("=")[0].strip()
        if key in pending:
            lines[index] = f"{key}={pending.pop(key)}"
    for key, value in pending.items():
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"# added by the first-run wizard")
        lines.append(f"{key}={value}")
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    return True


def run_startup_wizard(env_path: Path) -> bool:
    """Open the first-run dialog and save what the user enters to .env.

    Returns True only when the user pressed Save and the write succeeded;
    every other exit (Skip, window close, no display server) returns False
    and the app starts exactly as it would have without the wizard. Must be
    called before the main window builds: it runs on its own short-lived
    tk.Tk root."""
    try:
        root = tk.Tk()
    except Exception:
        return False   # no display (headless start): nothing to show
    root.title("Welcome to Torbox Downloader")
    root.withdraw()
    saved = {"ok": False}

    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Welcome to Torbox Downloader",
              font=("", 13, "bold")).pack(anchor="w")
    ttk.Label(frame, text=(
        "Two keys get everything working. They are stored only in the\n"
        ".env file next to the app, are never printed or logged, and\n"
        "are never sent anywhere except to their own service."
    ), justify="left").pack(anchor="w", pady=(6, 12))

    ttk.Label(frame, text="Torbox API key  (torbox.app \u2192 settings \u2192 API)"
              ).pack(anchor="w")
    key_box = ttk.Entry(frame, show="\u2022", width=52)
    key_box.pack(fill="x", pady=(2, 10))
    key_box.focus_set()

    ttk.Label(frame, text="GoFile API token  (optional \u2014 gofile.io, free tier)"
              ).pack(anchor="w")
    tok_box = ttk.Entry(frame, show="\u2022", width=52)
    tok_box.pack(fill="x", pady=(2, 10))

    note = ttk.Label(frame, text="", foreground="#a04000")
    note.pack(anchor="w")

    def save() -> None:
        values = {"TORBOX_API_KEY": key_box.get(),
                  "GOFILE_API_TOKEN": tok_box.get()}
        if not values["TORBOX_API_KEY"]:
            note.config(text="The Torbox API key is needed to add torrents.")
            return
        if merge_env(Path(env_path), values):
            saved["ok"] = True
            root.destroy()
        else:
            note.config(text="Could not write the .env file next to the app.")

    def skip() -> None:
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(8, 0))
    ttk.Button(buttons, text="Save and start", command=save).pack(
        side="right", padx=(6, 0))
    ttk.Button(buttons, text="Skip for now", command=skip).pack(side="right")

    # Centered on the screen (same rule as the app's own popups).
    root.update_idletasks()
    try:
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w = root.winfo_reqwidth() or 460
        h = root.winfo_reqheight() or 300
        root.geometry(f"+{max((sw - w) // 2, 0)}+{max((sh - h) // 2, 0)}")
    except tk.TclError:
        pass
    root.deiconify()
    root.protocol("WM_DELETE_WINDOW", skip)
    try:
        root.mainloop()
    except Exception:
        return False
    return saved["ok"]
