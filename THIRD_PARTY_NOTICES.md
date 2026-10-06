# Third-party notices

Ghostline's own code is MIT licensed (see [LICENSE](LICENSE)). It ships or uses the following.

## Fonts (SIL Open Font License 1.1, from [Velvetyne](https://velvetyne.fr))

| Font | Files | License text |
|------|-------|--------------|
| Grotesk (Gras), Frank Adebiaye | `frontend/fonts/Grotesk-Gras.woff2`, `backend/assets/Grotesk-Gras.otf` | `frontend/fonts/Grotesk-LICENSE.txt` |
| Lack, Adrien Midzic | `frontend/fonts/Lack-Regular.woff2` | `frontend/fonts/Lack-LICENSE.txt` |
| Sligoil, Ariel Martín Pérez | `frontend/fonts/Sligoil-*.woff2`, `backend/assets/Sligoil-MicroBold.otf` | `frontend/fonts/sligoil-LICENSE.txt` |

The fonts are converted to woff2 and served unmodified otherwise. They stay under the OFL; the MIT license does not
apply to them.

## JavaScript (vendored in `frontend/vendor`)

| Library | Version | License |
|---------|---------|---------|
| [GSAP](https://gsap.com) | 3.12.5 | GSAP Standard "No Charge" License, https://gsap.com/standard-license |
| [Lenis](https://github.com/darkroomengineering/lenis) | see file header | MIT |
| [plotly.js basic](https://github.com/plotly/plotly.js) | 2.35.2 | MIT |

## Python packages

Installed from PyPI by `setup.bat` (see `requirements.txt`): FastAPI, Starlette, Uvicorn, Pydantic (MIT),
NumPy, SciPy (BSD-3-Clause), Pillow (MIT-CMU), FastF1 (MIT). They are not included in this repository.

## Data

- Real-world laps come from Formula 1 timing data through [FastF1](https://github.com/theOehrly/Fast-F1). They
  are downloaded on demand and never committed. Formula 1 data is for personal, non-commercial use.
- Car and track names, lengths and corner names are read at runtime from your own Assetto Corsa install. None of
  the game's files are included here. Assetto Corsa is a trademark of its owners; Ghostline is not affiliated with
  Kunos Simulazioni or 505 Games.
