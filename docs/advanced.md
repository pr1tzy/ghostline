# Advanced

Nothing here is needed to use Ghostline. It's for tweaking it, publishing it, or working on the code.

## Where things are

| Path | What |
|------|------|
| `data/` | Everything recorded: `race.db` (SQLite), one `.npz` file per lap, `ghostline.log`. Back it up to keep your laps; delete it to start over. |
| `config/tracks.json`, `config/cars.json` | Your overrides for corner names, track lengths, car names and classes. |
| `config/site.json` | Only for publishing (see below). Not committed; copy `config/site.example.json`. |
| `samples/` | The sample laps loaded on first start. |

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

## How ghosts are kept fair

- **Pruning**: only your laps and the best lap of the top 3 other drivers per car and track are kept
  (`KEEP_DRIVERS` in `backend/store.py`).
- **Cut detection**: the game doesn't share other drivers' penalties, so each ghost lap is compared with your own
  best clean line. More than 15 m off it, or more than 20 m shorter, and it's dropped. This needs one clean lap of
  your own on that track first.
- **Estimated pedals**: throttle and brake for other cars are estimated from their speed, and shown dotted.

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

## Working on the code

- No build step. `backend/` is FastAPI (recorder, ingest, analysis, SQLite store, share images). `frontend/` is
  plain HTML, CSS and JS with vendored GSAP, Lenis and Plotly. `ac_app/RaceLogger` is the in-game app, which runs
  on AC's Python 3.3, so no f-strings there.
- Run a second server against the same data, without the recorder:
  `set GHOSTLINE_PORT=8766 && .venv\Scripts\python -m uvicorn backend.app:app --port 8766`
- Tests (throwaway database each): `.venv\Scripts\python tests/test_samples.py` runs offline on the sample laps
  (this is what CI runs; needs `pip install httpx`). `tests/test_compare.py` also imports two real F1 laps, so it needs
  internet and F1's servers, which often refuse cloud machines.
- Dependency check: `.venv\Scripts\python -m pip install pip-audit && .venv\Scripts\python -m pip_audit -r requirements.txt`.

Issues and pull requests are welcome. Keep changes small and say how you tested them.
