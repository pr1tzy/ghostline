# Advanced

Nothing here is needed to use Ghostline. It's for tweaking it, publishing it, or working on the code.

## Where things are

Installed with `GhostlineSetup.exe`, the program lives in `%LOCALAPPDATA%\Programs\Ghostline` and everything that's
yours lives in `%LOCALAPPDATA%\Ghostline`, so updates and reinstalls never touch it. Run from source, both are the
repository folder.

| Path (inside the folder above) | What |
|------|------|
| `data/` | Everything recorded: `race.db` (SQLite), one `.npz` file per lap, `ghostline.log`. Back it up to keep your laps; delete it to start over. |
| `config/tracks.json`, `config/cars.json` | Your overrides for corner names, track lengths, car names and classes. |
| `config/logger.json` | In-game logger settings (see below). |
| `config/app.json` | App options: `launch_with_game` (start with Assetto Corsa), `check_updates` (once a day). Also on the References page and in the tray menu. |
| `config/site.json` | Only for publishing (see below). |

The sample laps loaded on first start ship with the program (`samples/`).

## Cars, tracks and corner names

Track names, lengths and corner names (each track's `data/sections.ini`) and car classes (`ui_car.json` tags and
power-to-weight) are read from your AC install by `backend/content.py`. "Same class" ghosts use those classes.

To rename a corner, give a track a length, or change a car's name or class, add an override:

```json
// config/tracks.json
{ "monza": { "corners": [[950, "Rettifilo"], [2120, "Roggia"], [3950, "Ascari"]] } }

// config/cars.json
{ "lotus_exos_125_s1": { "name": "Lotus Exos 125 S1" } }
```

Corner positions are metres from the start line. Overrides always win over what's read from the game. Track ids
are the AC folder name, plus `-<layout>` for tracks with layouts (for example `ks_nordschleife-nordschleife`).

## How other cars are recorded

The in-game app does as little as possible: it copies every car's position, speed and lap times into a block of
shared memory (`GhostlineCars.v1`), the same way AC shares your own car. Ghostline reads it from outside the game
(`backend/carfeed.py`) and does the rest: lap detection, saving ghost laps, standings and gaps.

- With Custom Shaders Patch, `GhostlineLogger` (CSP Lua) does the copying. It also passes on the game's own verdict on
  each lap (valid or not, number of cuts), which Ghostline uses for other drivers' laps.
- Without CSP, the Python `RaceLogger` does it. It stands down by itself while the Lua app is running.
- Ghostline writes a heartbeat and a list of which cars need full detail (your car model or class) into
  `GhostlineWant.v2`, along with the logger settings below. The apps send only track positions for the other cars,
  and nothing at all when Ghostline isn't running. Each car is sampled 30 times a second by default, spread over
  frames.
- Both apps show what they cost per frame in their window.
- Older versions of the app wrote CSV files and `live.json`; those are still picked up.

## Logger settings

`config/logger.json` (created the first time you change something; defaults are built in, see
`config/logger.example.json`):

| Setting | Default | What it does |
|---------|---------|--------------|
| `enabled` | `true` | The in-game app sends anything at all. |
| `sample_hz` | `30` | How often the in-game app reads each car's position, speed and gear (5 to 60). |
| `timing_hz` | `4` | How often it reads lap count, lap times and pit status (1 to 10). |
| `live_hz` | `20` | How often Ghostline refreshes standings and the Live page map (2 to 30). The public site always gets 4. |
| `detail` | `"class"` | Which cars get full detail, which ghost laps need: `"car"` (your car model), `"class"` or `"all"`. |

Edit the file and the change applies within a second. With Custom Shaders Patch you can also change these in the
Ghostline Logger window in the game: it asks Ghostline to save them to the same file. Between updates, the Live
page moves every car at its current pace, so the map stays smooth even at low rates.

## How ghosts are kept fair

- **Pruning**: only your laps and the best lap of the top 3 other drivers per car and track are kept
  (`KEEP_DRIVERS` in `backend/store.py`).
- **Cut detection**: the game doesn't share other drivers' penalties, so each ghost lap is compared with your own
  best clean line. More than 15 m off it, or more than 20 m shorter, and it's dropped. This needs one clean lap of
  your own on that track first.
- **Online lag**: when a remote car lags, the game teleports it to catch up. A lap where the car moves 25 m or more
  at over 1.6x its own speed is marked invalid ("position jumps from connection lag"): as a ghost it would leap
  ahead and make your gap jump by a second. Laps stored before 2.3 are checked once at startup.
- **Estimated pedals**: throttle and brake for other cars are estimated from their speed, and shown dotted.

## In-game coaching

The CSP app (Ghostline) draws three things from the best lap for your car on this track: the fastest valid
lap Ghostline has with that car, yours or another driver's. Ghostline sends it into shared memory
(`GhostlineRef.v1`, `backend/coach.py`) when the session starts and whenever a faster lap is saved; the app switches
to a new one at the start of your next lap. Everything else happens inside the game, every frame, so nothing waits
on Ghostline. The settings are in the app's window (CSP keeps them in
`Documents\Assetto Corsa\cfg\extension\state\lua`).

- **Brake boards**: one sign per corner, on the outside of it, where the best lap first touched the brake after
  its top speed, with the gear and the slowest speed of the corner on top. It stays put, like a real brake board,
  and changes colour with the countdown. Lifts show as LIFT.
- **Countdown**: two ticks 0.6 s and 0.3 s before the board and a higher tone at it, timed from your current
  speed (arrive faster and they come sooner). Each one plays on the frame closest to the exact moment, so it's off by at most half a frame (8 ms at
  60 fps, 4 ms at 120; `tests/test_coach.py` checks this by driving recorded laps frame by frame). A single
  "brake now" beep would always be late by your reaction time (about 0.2 s, 14 m at 250 km/h); a countdown lets you
  brake on the beat instead. **Sound early by** shifts the sounds if your audio has a delay or you want a lead.
- **Racing line**: chevrons along the best lap's line for the next 50-400 m, like the F1 games' line, and like
  theirs it follows your speed. Red starts where you'd have to brake at the speed you're carrying (the best lap's
  braking, from your speed down to its slowest speed): earlier than the board when you're faster, later when you're
  slower. Yellow for the second before that, through lifts and until the best lap was back on full throttle, green
  otherwise. **Corners only** draws just the stretch from 120 m before each board to the
  exit. The chevrons grow with distance so the far ones stay readable from the cockpit. The 3D world is drawn in HDR,
  so every colour goes through CSP's white point; without that, the line came out nearly black on a daylit track.
  The window shows how many chevrons are drawn, how far ahead, and how often the road surface wasn't found.
- **3D ghost**: your car's shape (CSP's simple car mesh), see-through cyan with brighter edges, where the best lap
  was at your current lap time, with your gap above it. Or the ghost of your own fastest valid lap this session
  (recorded in the game, from your second lap on), which is closer to your pace while you're learning a track. It
  shows up to 1 km away; the Ghostline window says where it is (or why it's hidden). It fades out when it's on top of your car so it never fogs
  up the cockpit. If CSP can't give the car shape it shows as a footprint on the road.
- **Laps without pedal data** (other drivers): their brake points are worked out from how hard the car slowed down.
  Checked against 240 corners of laps with real pedal data, that lands 2 m early on average (corrected) and within
  4 m nine times out of ten. The window says "brake points estimated" when that's the case.
- **Cost**: about 0.03 ms per frame measured outside the game; the window shows the real figure.

Only you see any of this: it's drawn on your screen and nothing is sent to the server. If your league doesn't
allow driving aids, untick them in the window.

## In-game dash

One horizontal window, Ghostline Dash: show it and drag it from the CSP app bar (the title bar appears when you
hover it). It works without Ghostline running; only the ghost parts need it. In the Ghostline window you switch each
section on or off (the dash shrinks to what's left) and set its size and background. `ac_app/GhostlineLogger/hud.lua`;
`tests/test_hud.py --png DIR` draws the dash to an image to check the design outside the game.

- **Standings**: cars around you on track with live gaps (relative), or the full order (click to switch). Gaps come
  from when each car passed the same spot, 200 spots per lap. The driver whose lap is your ghost is in cyan.
- **Timing**: current lap (greyed when the game has flagged it), sectors against your best sectors, last / best /
  ghost lap, position, fuel with laps left.
- **Gear + delta**: rev bar (top 45 % of the revs, cyan flash at the shift point), gear, speed, ABS / TC (lit while
  working), brake bias, DRS; under it the gap to the best lap Ghostline sends, or to your session best (click to
  switch), where it was a second ago and the predicted lap.
- **Pedals**: clutch, brake and throttle with the best lap's brake and throttle at the same spot on track (cyan),
  ABS / TC flashes, the last 4 seconds of throttle and brake, steering angle.
- **Tyres**: compound, inside / middle / outside temperature against the tyre's own optimum (cold cyan, in the
  window teal, warm white, hot pink), core temperature, pressure, wear left, brake disc temperature, and damage (the
  hardest hit, in km/h) when there is any.
- **Map**: the track the same way round as the game's own map, every car on it (you in violet, the pits in grey)
  and the ghost in cyan.
- **Flags** (yellow, blue, black, penalty, chequered: the ones the game reports) show as a bar along the top of the
  dash in the flag's colour and in Timing. **Pit limiter** lights up next to ABS / TC. In a race Timing also shows
  the fuel you'll have left at the flag (laps to go times fuel per lap).
- The Ghostline window says whether the dash's fonts loaded.

## Run from source

For working on Ghostline, or if you'd rather not run an installer. Needs Python 3.12 or newer.

1. Download the source (`Ghostline-source.zip` on the release page, or `git clone`).
2. Double-click `start.bat`. The first time it creates a private Python environment in `.venv` and installs the
   packages; it offers to install Python if needed. Close its window to stop Ghostline.

Also there: `ghostline.vbs` starts it without a console window and `stop.bat` stops it; `uninstall.bat` removes the
in-game apps. `autostart.bat` adds Ghostline to Windows startup, but only if you run it (`autostart.bat off` removes it).
Start with the game works from source too: the in-game app starts `pythonw run.py --with-game`.

## Publish online

By default the server only listens on `127.0.0.1`, so nobody else can reach it. To share a read-only copy, you
can use a [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
(free, needs a domain on Cloudflare):

1. Install `cloudflared` and run `cloudflared tunnel login`.
2. Create the tunnel and a hostname:
   ```
   cloudflared tunnel create ghostline
   cloudflared tunnel route dns ghostline ghostline.example.com
   ```
3. Create `cloudflared/ghostline.yml` (not committed):
   ```yaml
   tunnel: ghostline
   ingress:
     - hostname: ghostline.example.com
       service: http://127.0.0.1:8765
       originRequest:
         httpHostHeader: ghostline.example.com
     - service: http_status:404
   ```
   The tunnel credentials stay in `%USERPROFILE%\.cloudflared`; nothing secret goes in the repo.
4. Optional: copy `config/site.example.json` to `config/site.json` and set `credit_name` and `credit_url` to put
   your name in the footer.
5. Restart Ghostline. It starts the tunnel with the site and stops it on exit.

Suggested Cloudflare settings: SSL/TLS **Full (strict)**, **Always Use HTTPS**, **Minimum TLS 1.2**, **HSTS** on,
**Bot Fight Mode** on. No cache rules are needed.

`config/site.json` settings: `public_host` (defaults to the tunnel's hostname), `credit_name`, `credit_url`,
`port`. Environment variables `GHOSTLINE_PORT` and `GHOSTLINE_HOST` override them.

## Security model

There is no login. Only requests made on your PC straight to `127.0.0.1:<port>` are admin (delete laps, notes,
imports, recorder on/off). Anything that arrives through a tunnel or proxy carries forwarding headers and a public
`Host`, so it's public:

- GET only (anything else returns 403). Unknown `Host` headers return 421, which blocks DNS rebinding.
- Other drivers are shown by initials. No local file paths, no API docs.
- Strict Content Security Policy (every script is served from this repo), HSTS, no framing, nosniff.
- Live stream viewers are capped and get a slower stream.

Only publish through something that adds forwarding headers (Cloudflare Tunnel does). Never bind the server to
`0.0.0.0` or forward the port on your router: every visitor would count as admin. To report a security problem,
see [SECURITY.md](../SECURITY.md).

## Overrides

Environment variables, mostly for unusual installs and for tests:

| Variable | What |
|----------|------|
| `GHOSTLINE_AC_PATH` | Assetto Corsa folder, if it isn't a normal Steam install. |
| `GHOSTLINE_DOCUMENTS` | The Documents folder that holds `Assetto Corsa\cfg\python.ini`, if Windows reports the wrong one. |
| `GHOSTLINE_HOME` | Where laps and settings live (default above). |
| `GHOSTLINE_PORT` | Local port (default 8765). |

## Building a release

`python packaging/build.py` builds `dist/Ghostline/` with PyInstaller, starts the built `Ghostline.exe --selftest` to
check it really runs, then makes `Ghostline-portable.zip`, `GhostlineSetup.exe` (with Inno Setup, if installed) and
`SHA256SUMS.txt` in `dist/release/`.

Publishing a GitHub release does all of that on GitHub's Windows machines (`.github/workflows/release.yml`) and
attaches the files, plus the source zip and a build-provenance record. The site and the README link to
`releases/latest/download/GhostlineSetup.exe`, so every release needs that file.

The build is kept unsuspicious on purpose: a folder build rather than one self-unpacking exe, no UPX packing, proper
version information, per-user install without admin rights, nothing added to Windows startup.

**Code signing** (removes the "Windows protected your PC" warning once reputation builds): the workflow signs both the
app and the installer through the [SignPath Foundation](https://signpath.org), which signs open-source projects for
free. After the project is accepted, add repository variables `SIGNPATH_ORGANIZATION_ID`, `SIGNPATH_PROJECT_SLUG`,
`SIGNPATH_POLICY_SLUG` and secret `SIGNPATH_API_TOKEN`, with two artifact configurations in SignPath: `app` (the app
folder, sign `Ghostline.exe`) and `installer` (sign `GhostlineSetup.exe`). Without them, releases are built unsigned.
With a `VT_API_KEY` secret, a VirusTotal scan link is added to each release.

## Working on the code

- No build step. `backend/` is FastAPI (recorder, ingest, analysis, SQLite store, share images). `frontend/` is
  plain HTML, CSS and JS with vendored GSAP, Lenis and Plotly. `ac_app/RaceLogger` is the in-game app, which runs
  on AC's Python 3.3, so no f-strings there.
- Run a second server against the same data, without the recorder:
  `set GHOSTLINE_PORT=8766 && .venv\Scripts\python -m uvicorn backend.app:app --port 8766`
- Tests (throwaway database each): `.venv\Scripts\python tests/test_samples.py` runs offline on the sample laps
  (needs `pip install httpx`). `tests/test_feed.py` runs the in-game app against a fake AC through real shared
memory into the car feed, and `tests/test_lua_app.py` runs the CSP app under LuaJIT (`pip install lupa`). CI runs all three. `tests/test_compare.py` also imports two real F1 laps, so it needs
  internet and F1's servers, which often refuse cloud machines.
- Dependency check: `.venv\Scripts\python -m pip install pip-audit && .venv\Scripts\python -m pip_audit -r requirements.txt`.

- Releases: publish a GitHub release and `.github/workflows/release.yml` attaches `Ghostline.zip` to it. The site's
  download button and the README link to `releases/latest/download/Ghostline.zip`, so every release needs that file.

Issues and pull requests are welcome. Keep changes small and say how you tested them.
