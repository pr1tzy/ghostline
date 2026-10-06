"""Per-comparison share preview images (1200x630 PNG), rendered with Pillow and cached on disk."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import store

W, H = 1200, 630
BG, FG, MUTE, GHOST, VIO, LOSS, GAIN = "#0b0a0f", "#efecf4", "#8a8597", "#3ef0ff", "#9d6bff", "#ff4f81", "#42f5c8"
FONT_DISP = Path(__file__).parent / "assets" / "Grotesk-Gras.otf"
FONT_NUM = Path(__file__).parent / "assets" / "Sligoil-MicroBold.otf"
OUT = store.DATA / "og"
OUT.mkdir(exist_ok=True)


def _fmt(ms):
    s = ms / 1000
    return f"{int(s // 60)}:{s % 60:06.3f}"


def _glow(img, xy, r, color, alpha):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x, y = xy
    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    d.ellipse((x - r, y - r, x + r, y + r), fill=rgb + (alpha,))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(r / 2)))


def _slant(img, box_text, font, fill, pos):
    """Draw text with a racing slant (the display font has no italic)."""
    w, h = int(font.getlength(box_text)) + 60, font.size + 40
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((20, 10), box_text, font=font, fill=fill)
    layer = layer.transform(layer.size, Image.AFFINE, (1, 0.2, -0.2 * h, 0, 1, 0), resample=Image.BICUBIC)
    img.alpha_composite(layer, pos)


def render(c, key):
    path = OUT / f"{key}.png"
    if path.exists():
        return path
    img = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 24):   # telemetry graph paper, same as the site
        d.line([(x, 0), (x, H)], fill="#15131c" if x % 120 else "#1e1b27")
    for y in range(0, H, 24):
        d.line([(0, y), (W, y)], fill="#15131c" if y % 120 else "#1e1b27")
    disp = lambda s: ImageFont.truetype(str(FONT_DISP), s)
    num = lambda s: ImageFont.truetype(str(FONT_NUM), s)

    m = c.get("map")
    if m:   # track on the right: base line + ghost line, coloured by where time is lost
        xs, zs = m["x"], m["z"]
        x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
        sc = 470 / max(x1 - x0, z1 - z0)
        ox, oy = 1150 - (x1 - x0) * sc, (H - (z1 - z0) * sc) / 2
        pts = [(ox + (x - x0) * sc, oy + (z - z0) * sc) for x, z in zip(xs, zs)]
        d.line(pts + pts[:1], fill="#1e1b27", width=26, joint="curve")
        for i in range(1, len(pts)):
            r = m["rate"][i]
            col = LOSS if r > 0.006 else GAIN if r < -0.006 else "#4a4560"
            d.line([pts[i - 1], pts[i]], fill=col, width=5)

    d.text((72, 64), "GHOSTLINE", font=disp(26), fill=FG)
    d.text((72, 108), f"{c['track_name'].upper()} / {c['a']['car_name'].upper()}", font=num(18), fill=MUTE)
    d.text((72, 200), "ME", font=num(20), fill=MUTE)
    d.text((72, 226), _fmt(c["a"]["lap_ms"]), font=num(64), fill=FG)
    d.text((72, 318), "GHOST", font=num(20), fill=MUTE)
    d.text((72, 344), _fmt(c["b"]["lap_ms"]), font=num(64), fill=GHOST)
    tot = c["total"]
    d.text((68, 440), f"{'+' if tot > 0 else '-'}{abs(tot):.3f}", font=disp(104), fill=LOSS if tot > 0 else GAIN)
    if c["insights"]:
        i = c["insights"][0]
        d.text((72, 566), f"BIGGEST LOSS: {i['corner'].upper()}  +{i['loss']:.3f}s", font=num(18), fill=VIO)
    img.convert("RGB").save(path, optimize=True)
    return path
