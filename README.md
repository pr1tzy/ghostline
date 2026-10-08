# Ghostline

[![CI](https://github.com/pr1tzy/ghostline/actions/workflows/ci.yml/badge.svg)](https://github.com/pr1tzy/ghostline/actions/workflows/ci.yml) [![Release](https://img.shields.io/github/v/release/pr1tzy/ghostline)](https://github.com/pr1tzy/ghostline/releases/latest) ![Windows](https://img.shields.io/badge/platform-Windows-blue) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Find out exactly where you're losing time in Assetto Corsa.** Ghostline records your laps, quietly logs the
fastest drivers on the server you're racing on, and shows you corner by corner where they're quicker and why.

**Live demo:** [ghostline.prithvisingh.fyi](https://ghostline.prithvisingh.fyi), a read-only copy with real laps.

![Home](docs/home.png)

## What you get

- **Your laps, recorded automatically.** Speed, throttle, brake, steering, gear and your line, 60 times a second.
  No buttons, no exporting.
- **Ghosts of the fastest drivers.** A small in-game app logs every other car on the server (or the AI). The best
  lap of the three fastest drivers is kept as a ghost for each car and track. Laps that cut the track are thrown out.
- **A debrief that tells you what to fix.** "Roggia: brake 14 m later", "Lesmo 2: carry 3 km/h more through the
  apex". Plus speed, gap and pedal charts, and a track map coloured by where you gain and lose.
- **A live dash for a second monitor.** Gap to your best and to the ghost, predicted lap, sectors, how you did in
  the last corner, standings with gaps, tyres, brakes and fuel.
- **Stats.** A ghost leaderboard with sectors, your ideal lap from your best mini-sectors, and progress over time.

| Compare | Where the time goes | Stats |
|---|---|---|
| ![Compare](docs/compare.png) | ![Map and charts](docs/map.png) | ![Stats](docs/stats.png) |

Two sample comparisons (Monza and Spa, Lotus Exos 125 S1) are loaded on first start so you can look around
before you drive. They disappear once your own laps start coming in.

## Install

You need Windows 10 or 11 and Assetto Corsa from Steam. Content Manager is optional.

1. Download **[GhostlineSetup.exe](https://github.com/pr1tzy/ghostline/releases/latest/download/GhostlineSetup.exe)** (about 25 MB).
2. Run it. It installs just for you, so there's no admin prompt. It asks one thing: whether Ghostline should start
   when you start a session in Assetto Corsa (and close a few minutes after the game). Nothing is ever added to
   Windows startup.
3. Ghostline opens in your browser. Start a session in Assetto Corsa and drive. The first time, restart that session
   once so the game loads Ghostline's in-game app.

**"Windows protected your PC"?** Ghostline isn't code-signed yet (free signing for open-source projects is on its
way). Click **More info > Run anyway**. Every release is built by GitHub from this repository's source, and the release
page lists checksums and a build-provenance record so you can check the file is the real one.

Prefer no installer? Each release also has `Ghostline-portable.zip` (unzip, run `Ghostline.exe`), and you can run it
from source: see [docs/advanced.md](docs/advanced.md#run-from-source).

## Using it

- While Ghostline runs, its icon sits by the clock. Click it to open the site; right-click for the menu (start with
  the game on/off, quit).
- Open it any time from the Start Menu to look at your laps without the game.
- The site lives at http://127.0.0.1:8765. Put the **Live** page on a second monitor while you race.
- For ghosts, race online (or against the AI). Ghostline installs its in-game app into AC for you.
- Logger settings (how often cars are sampled, which cars, on/off) are in the Ghostline Logger window in the game if
  you have Custom Shaders Patch, or in a settings file: see [docs/advanced.md](docs/advanced.md#logger-settings).

## FAQ

**Can this get me banned? Is it a cheat?**
No. It doesn't change the game, your car or the server. Your own laps come from the same telemetry that SimHub and
Crew Chief read. Ghosts come from a normal in-game Python app that sees what your game already shows (where each
car is and how fast it's going). Some servers block custom apps; there, your laps still record but ghosts don't.

**Does it work online?**
Yes, that's the main use. Ghosts are logged from whichever server you're on, for the car you're driving.

**Does it send my data anywhere?**
No. Everything stays on your PC (in `%LOCALAPPDATA%\Ghostline`). Nothing is uploaded and there's no account. Once a
day Ghostline asks GitHub whether a newer version exists; you can switch that off on the References page.

**Does it run in the background all the time?**
No. If you chose "start with the game", it starts when you start a session in Assetto Corsa and closes a few minutes
after you quit the game. Otherwise it only runs when you open it. It never starts with Windows.

**Which cars and tracks work?**
Every official Assetto Corsa car and track, including the DLCs. Mod cars and tracks are skipped, because mod
versions differ between servers, so the comparison wouldn't be fair.

**Will it hurt my FPS?**
No. The in-game app only copies each car's numbers into shared memory (no files, no text) and does nothing while
Ghostline isn't running; everything else runs outside the game. In tests it costs about 0.02 ms per frame, and about
0.001 ms with Custom Shaders Patch, which gets an even lighter Lua version automatically. Its window shows the real
cost on your PC.

**Can my friends see it?**
By default only you can, on your own PC. If you want a public read-only copy, see
[docs/advanced.md](docs/advanced.md#publish-online).

**How do I update?**
Ghostline tells you when a new version is out (tray menu and References page). Download the new installer and run
it; your laps and settings stay where they are.

**How do I uninstall it?**
Windows Settings > Apps > Ghostline > Uninstall. It also removes the in-game apps from Assetto Corsa, and asks
whether to keep your laps for a later reinstall.

## Something not working?

- **Live says "Waiting for AC"**: the game only shares telemetry in a session (on track or in the pits), not in
  the menus.
- **No ghosts**: ghosts are only recorded while Ghostline is running. Open the **References** page, which shows
  whether the in-game app is installed and active. Restart your AC session after the first install. In Content
  Manager, check Settings > Assetto Corsa > Apps and tick RaceLogger.
- **"Mod content: not recorded"**: that car or track isn't official content (see the FAQ).
- **Ghostline won't start**: the log is in `%LOCALAPPDATA%\Ghostline\data\ghostline.log`.

Still stuck? [Open an issue](https://github.com/pr1tzy/ghostline/issues) with the log.

## More

- [CHANGELOG.md](CHANGELOG.md): what changed in each version.
- [docs/advanced.md](docs/advanced.md): settings, renaming corners, running from source, publishing online, the
  security model, building releases, and working on the code.
- [ROADMAP.md](ROADMAP.md): what's planned next.
- License: [MIT](LICENSE). Fonts and libraries: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- Ghostline is a fan project, not affiliated with or endorsed by Kunos Simulazioni, 505 Games or Formula 1.
