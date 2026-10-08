# Changelog

## 2.1.0

Ghostline now installs like a normal Windows app.

- **GhostlineSetup.exe**: about 25 MB, installs for your user only (no admin prompt), Start Menu entry, uninstall
  from Windows Settings (removes the in-game apps too, and asks whether to keep your laps). Laps and settings live
  in `%LOCALAPPDATA%\Ghostline`, so updates never touch them. A portable zip is there too.
- **Starts with the game, not with Windows.** If you choose it in the installer, the in-game app starts Ghostline when
  you start a session, and Ghostline closes a few minutes after the game. Nothing is added to Windows startup.
- **Tray icon** while it runs: open the site, turn start-with-the-game on or off, quit.
- **Update notice**, if you tick it in the installer: once a day Ghostline asks GitHub whether a newer version exists (change it on the References
  page).
- **Lighter**: scipy replaced by a few lines of numpy (identical results), and the real-world F1 import now uses the
  free OpenF1 API (seasons from 2023) instead of FastF1. The install went from about 390 MB of packages to about 80 MB.
- **Release builds** are made by GitHub from the tagged source, checked by actually starting the built app, with
  checksums and a build-provenance record. Code signing switches on once the free open-source signing is approved.

## 2.0.0

The in-game side was rebuilt to cost almost nothing inside Assetto Corsa.

- **Shared memory instead of files.** The in-game app now only copies every car's position, speed and lap times
  into shared memory. Ghostline does lap detection, ghost laps, standings and gaps outside the game. No disk access,
  no text and no lap logic inside the game's frame loop.
- **CSP version.** With Custom Shaders Patch, a Lua version of the app (Ghostline Logger) runs instead of the Python
  one. It's even lighter, and passes on the game's own verdict on every lap (valid, number of cuts), which Ghostline
  now uses for other drivers' laps. The Python app stands down by itself while it runs.
- **Idle when not needed.** The apps do nothing while Ghostline isn't running, and send full detail only for cars
  that can be your ghost (your car or class by default).
- **Settings.** Sample rate, lap-time rate, Live page rate, which cars get full detail, and on/off, in
  `config/logger.json` or in the CSP app's window.
- **Smoother Live page.** Faster updates (30 car samples and 20 page updates a second by default), and the map moves
  every frame instead of jumping between updates.
- **Per-frame cost** shown in the in-game app's window.
- **Why a lap doesn't count.** Your invalid laps show the reason ("cut at Rettifilo"), and Compare says when a faster
  lap of yours was cut. "Places it still beats you" when you're quicker than the reference.
- **Get it page** on the site with a direct download and three install steps.
- Requires Python 3.12 or newer (set up automatically by `start.bat`).

## 1.0.1

- Python 3.12 or newer; updated packages. `start.bat` reinstalls packages after an update.

## 1.0.0

- First public release: auto-recorded laps, ghosts of the fastest drivers on your server, corner-by-corner debrief,
  live second-monitor dash, stats, sample laps, official cars and tracks only.
