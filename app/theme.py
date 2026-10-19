"""Design system for the Torbox Downloader app.

Colors and widget styling follow the user's spec verbatim (research-material/ui-design-spec.md).
"""

import tkinter as tk
from tkinter import ttk


class Theme:
    BG = "#12141d"            # window background
    PANEL = "#1a1d2b"         # input fields, log background
    PANEL2 = "#232839"        # hover/secondary panels, list selection
    ACCENT = "#5b67d8"        # buttons
    ACCENT_BRIGHT = "#7d88e8" # header text, hover, combobox arrow
    TEXT = "#e8e9f2"          # main text
    MUTED = "#8a8fa8"         # secondary text
    OK = "#4ade80"            # positive status, green
    BAD = "#f87171"           # negative status, red
    LINK = "#8f9cf0"          # hyperlinks
    BUTTON_TEXT = "#12121c"   # dark text on ACCENT buttons


def apply_theme(root: tk.Tk) -> None:
    """Apply the design system to a root window. Call once after Tk() creation."""
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=Theme.BG, foreground=Theme.TEXT,
                    fieldbackground=Theme.PANEL,
                    bordercolor=Theme.PANEL2, lightcolor=Theme.PANEL2,
                    darkcolor=Theme.PANEL2, troughcolor=Theme.PANEL)
    style.configure("TFrame", background=Theme.BG)
    style.configure("TLabel", background=Theme.BG, foreground=Theme.TEXT)
    style.configure("Header.TLabel", background=Theme.BG,
                    foreground=Theme.ACCENT_BRIGHT, font=("Sans", 14, "bold"))
    style.configure("Muted.TLabel", background=Theme.BG, foreground=Theme.MUTED)
    style.configure("TEntry", fieldbackground=Theme.PANEL, foreground=Theme.TEXT,
                    insertcolor=Theme.TEXT, bordercolor=Theme.PANEL2,
                    lightcolor=Theme.PANEL2, darkcolor=Theme.PANEL2, padding=4)
    style.configure("TCombobox", fieldbackground=Theme.PANEL, background=Theme.PANEL2,
                    foreground=Theme.TEXT, arrowcolor=Theme.ACCENT,
                    bordercolor=Theme.PANEL2, lightcolor=Theme.PANEL2,
                    darkcolor=Theme.PANEL2, padding=4)
    style.map("TCombobox", fieldbackground=[("readonly", Theme.PANEL)],
              foreground=[("readonly", Theme.TEXT)],
              selectbackground=[("readonly", Theme.PANEL2)],
              selectforeground=[("readonly", Theme.TEXT)])
    root.option_add("*TCombobox*Listbox.background", Theme.PANEL)
    root.option_add("*TCombobox*Listbox.foreground", Theme.TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", Theme.PANEL2)
    root.option_add("*TCombobox*Listbox.selectForeground", Theme.ACCENT_BRIGHT)
    style.configure("TButton", background=Theme.ACCENT, foreground=Theme.BUTTON_TEXT,
                    borderwidth=0, focusthickness=0, padding=(12, 6))
    style.map("TButton", background=[("active", Theme.ACCENT_BRIGHT)])
    # R14: small image-only buttons (the cog and folder icons). Same colors
    # as TButton but a tighter padding so both render the same compact size
    # and line up on the status line.
    style.configure("Icon.TButton", background=Theme.ACCENT,
                    foreground=Theme.BUTTON_TEXT, borderwidth=0,
                    focusthickness=0, padding=(6, 5))
    style.map("Icon.TButton", background=[("active", Theme.ACCENT_BRIGHT)])
    # R14 fix: on the clam theme a Checkbutton with no explicit styling
    # flashes a white background whenever the pointer hovers it (reported on
    # "Show archived" and on the settings popup's "Show secret values").
    # Pinning every active state to the window background keeps hover silent.
    style.configure("TCheckbutton", background=Theme.BG, foreground=Theme.TEXT,
                    focuscolor=Theme.BG, borderwidth=0)
    style.map("TCheckbutton",
              background=[("active", Theme.BG), ("selected", Theme.BG),
                          ("pressed", Theme.BG), ("disabled", Theme.BG)],
              foreground=[("active", Theme.TEXT), ("selected", Theme.TEXT),
                          ("pressed", Theme.TEXT), ("disabled", Theme.MUTED)],
              indicatorcolor=[("selected", Theme.ACCENT), ("pressed", Theme.ACCENT),
                              ("active", Theme.PANEL2)])
    # R14: small section headers that visually separate the Search, Results,
    # Downloads and Log areas of the window.
    style.configure("Section.TLabel", background=Theme.BG, foreground=Theme.MUTED,
                    font=("Sans", 9, "bold"))
