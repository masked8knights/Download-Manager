# Download Manager

A small, self-contained desktop app: search torrents (through a running
qBittorrent's WebUI search plugins), send them to Torbox (debrid), collect
every piece into ONE folder named after the release, upload that folder to
GoFile as one share link, and optionally unpack it on your own PC.

One window. One Python file. No website, no daemon, no telemetry.

## What it does

- SEARCH: queries qBittorrent's installed search plugins (qBittorrent must
  be running with its WebUI enabled) with a category filter, a per-plugin
  filter and a Trending button; results stream in row by row.
- DOWNLOADS: pressing Download sends the torrent to your Torbox account.
  When Torbox has it cached, the app fetches every piece into one folder
  named after the release (no more randomly-named folders). Multi-part
  archives can be unpacked locally with destination presets.
- GOFILE: "Make GoFile link" uploads the release to your GoFile account
  and renames the storage folder to the release name so the storage reads
  sensibly. Where Torbox supports it, the transfer goes DIRECTLY from
  Torbox to GoFile (nothing touches your PC); otherwise it flows through
  a local copy. Rate limits are retried in the background on a scheduled
  queue so nothing is lost.
- The merged GOFILE table shows every link and your whole GoFile storage:
  one click expands a folder inline, two clicks open the folder's share
  link, and the Where column hyperlinks to wherever the release lives
  (your PC, the Torbox dashboard, or the GoFile link).
- Automatic refresh: TORBOX FILES and GOFILE refresh shortly after
  startup and then every half hour while the window is open (a manual
  refresh still reports errors).
- Handoff: double-clicking a .torrent or magnet link while the app is
  running hands it to the running instance and joins its queue.
- Startup wizard: on first run the app asks for the two API keys and
  saves them to a local `.env` it creates next to the app; later runs
  skip straight to the main window.

## Install

Download the latest release for your platform from the Releases page:

- Windows: `TorboxDownloader.exe` (portable, just run it)
- Linux: `TorboxDownloader-x86_64.AppImage` (chmod +x, then run)

Run from source instead with Python 3.11+ (stdlib only, tkinter needed,
which Linux usually has via the system python3-tk package):

    python -m app

## Setup

You need two API keys, each free to get:

- Torbox: an API key from torbox.app (Settings → API).
- GoFile: a token from gofile.io (account settings; the free tier works).

The first-run wizard asks for both and stores them in `.env` next to the
app. On Linux the file sits next to the AppImage; on Windows next to the
exe. You can edit the values later in-app via the ⚙ Settings popup
(values are masked; a restart applies them).

## How it stays safe with your keys

The API keys live only in the local `.env` file. They are never logged,
never written to the log window, and never included in any generated
link. Your Torbox account's torrents are never deleted by the app's local
buttons; removing things from Torbox is a reminder-and-dashboard job, on
purpose.

## Platform notes

- Windows: the packed exe carries the app icon, so the taskbar button
  shows the app icon rather than the Python logo.
- Linux: desktop notifications go through notify-send.

## License

MIT. See the LICENSE file.
