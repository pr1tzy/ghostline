# Changelog

## 2.3.0

A full dash inside the game, so Ghostline is the only app you need.

- **One horizontal dash** (Ghostline Dash) with five sections you can switch off one by one: Standings (relative
  with live gaps, or the full order), Timing (lap, sectors, last / best / ghost, position, fuel and laps left), Gear
  + delta (rev bar, gear, speed, ABS / TC / bias / DRS, gap to the best lap or session best, predicted lap), Pedals
  (with the best lap's brake and throttle at the same spot, a 4 second trace and steering) and Tyres (temperatures
  against the tyre's optimum, pressure, wear, brakes).
- In Ghostline's own style and fonts: a solid slab with cut corners and hairlines, violet for you, cyan for the ghost.
- **Brake boards stay put**: one sign per corner, on the outside, where the best lap braked. The countdown still
  comes from your speed.
- **Racing line like the F1 games'**: chevrons along the best lap's line, green / yellow / red, full or corners
  only. It was invisible before: the 3D world is HDR, and the colours now go through CSP's white point.
- **The racing line follows your speed** like the F1 line: red starts where you'd have to brake at your speed, so
  it moves earlier when you're faster. The board stays where the best lap braked.
- **3D ghost is your car's shape** in see-through cyan (CSP's car mesh), fading out when it's on top of you. New:
  a ghost of your own session best, it shows up to 1 km away, and the window says where it is.
- **Ghost laps with online lag are thrown out.** A remote car that lags gets teleported ahead; one such lap was
  the Monza "best" (1:16.8, 861 m of jumps) and made the ghost rocket after the chicane and the gap jump by a second.
  Such laps aren't kept any more, and ones already stored are removed once at startup.
- **Other drivers' laps had twice their real lap time** since 2.0 (CSP calls the in-game app twice a frame, and its
  clock counted both). The app now runs once a frame on the game's own clock; the Standings gaps and the pedal trace
  were doubled by the same thing.
- **Laps take 2.6x less space**: stored at the precision they're measured with (existing laps are converted once,
  with every comparison unchanged).
- **Easier to find the ghost**: a cyan marker above it, drawn from both sides, and where it is on the dash map.
- **More on the dash**: a track map with every car and the ghost, race flags (bar along the top), pit limiter, tyre
  compound, damage, and fuel left at the flag in races.
- **Compare no longer fails** on laps where a chicane's two halves were merged into one corner, and the ideal-lap
  compare says "no laps of yours yet" instead of failing for cars you haven't driven.

## 2.2.0

Coaching on the track, inside the game (needs Custom Shaders Patch), from the best lap for your car.

- **Brake boards** where that lap braked, moved for the speed you're carrying, with the gear and the corner's
  slowest speed above them.
- **Tick-tick-brake countdown**, timed to within half a frame, so you brake on the beat instead of reacting late.
- **Racing line** ahead of you that turns yellow and red where you need to slow down, also following your speed.
- **3D ghost** of that lap: the car's own model, see-through, with your gap above it.
- All of it is drawn only on your screen (online too), costs about 0.03 ms per frame, and can be switched off in the
  Ghostline Logger window. Details in docs/advanced.md, "In-game coaching".

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
