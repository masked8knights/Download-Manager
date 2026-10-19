"""Tiny inline PNG icons for the Torbox Downloader UI.

R14: the settings button is a real drawn cog (the Unicode "⚙" glyph rendered
as a flower-like outline on Windows) and the Presets button is a real drawn
folder (the "📁" emoji rendered as a white crossed box on Windows). Each
icon is a 16x16 RGBA PNG embedded as base64, so the runtime needs no image
library: tk.PhotoImage decodes PNG natively (Tk 8.6+). The images are drawn
at exact display size; keep the caller holding a reference or Tk
garbage-collects the PhotoImage.
"""

import base64
import tkinter as tk

_COG_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAgElEQVR4nKWSQQ7AIAgEF9Kz"
    "V/z/69prP9CeTChZ0FgSE5RFBhFwdl73432/mAYANAaigBXwGpklVdatiewmfwh2KLo1Adwb"
    "ZKIhTAmyyjEx01ECVjUjKVtYMXoBw81aKKcwsKvYUeGtjPb3R9LZnCvr1kSHEwNMzPYaDyoi"
    "pnkBx6tTnwA29M8AAAAASUVORK5CYII=")

_FOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAQElEQVR4nGNgGGjAyMDAwNDV"
    "v+I/PkVlhRGMuOSYqOKCFy8/4XUBPkCxC0YNoIIBLAwMDAwPn/wbOBdQbMDAAwD21AqeNjSn"
    "3wAAAABJRU5ErkJggg==")


def cog_photo(master: tk.Misc) -> tk.PhotoImage:
    """The settings cog as a PhotoImage (16x16, transparent background)."""
    return tk.PhotoImage(master=master, data=_COG_PNG)


def folder_photo(master: tk.Misc) -> tk.PhotoImage:
    """The Presets folder as a PhotoImage (16x16, transparent background)."""
    return tk.PhotoImage(master=master, data=_FOLDER_PNG)
