#!/usr/bin/env python3
"""
The Last 24 — Instagram slide design system (v3, dynamic layouts).

Design language (from the approved samples):
  - Poppins typography (Light/Regular/Medium/Bold) for a modern, confident look.
  - ALTERNATING light and dark slides to break monotony.
  - A floating rounded card on body slides (not full-bleed text).
  - Slide numbers ("02 / 05") and small mono kickers ("01 — The brief").
  - Colored/bold emphasis on key phrases; points use dots or a left accent.
  - Real images woven in where available (photo band on some layouts).
  - Cover keeps the established design language (dark, ambient, big headline,
    verified pill, swipe prompt).

This module exposes render helpers used by build_social.py. It does NOT fetch or
caption — it only renders given content dicts.
"""
import os, random, math
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

SIZE, HEIGHT = 1080, 1350

# palette
INK = (16, 20, 18)
INK_CARD = (22, 28, 25)
PAPER = (244, 243, 238)
PAPER_CARD = (255, 255, 255)
WHITE = (255, 255, 255)
GREEN = (39, 185, 123)
GREEN_DEEP = (12, 110, 73)
META_DARK = (150, 158, 148)     # meta text on dark
META_LIGHT = (120, 126, 118)    # meta text on light
INK_SOFT = (69, 75, 67)

SECTION_HUES = {
    "national": (61, 122, 92), "world": (62, 96, 136), "business": (160, 122, 60),
    "tech": (106, 92, 154), "ai": (60, 133, 133), "sports": (181, 87, 63),
    "entertainment": (166, 84, 120), "worldcup": (22, 135, 107),
}

GF = "/usr/share/fonts/truetype/google-fonts"
DV = "/usr/share/fonts/truetype/dejavu"
# Optional: a fonts/ folder bundled in the repo (preferred if present).
REPO_FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
_cache = {}

def _load(candidates, size):
    """Load the first available font from a list of candidate paths, at `size`.
    Falls back through the list so the build never crashes if a font is missing
    on a given environment (e.g. Poppins absent on the GitHub runner)."""
    key = (tuple(candidates), size)
    if key in _cache:
        return _cache[key]
    for path in candidates:
        try:
            f = ImageFont.truetype(path, size)
            _cache[key] = f
            return f
        except Exception:
            continue
    # Last resort: PIL's built-in default (always works, just plain).
    f = ImageFont.load_default()
    _cache[key] = f
    return f

def bold(s):
    return _load([f"{REPO_FONTS}/Poppins-Bold.ttf", f"{GF}/Poppins-Bold.ttf",
                  f"{DV}/DejaVuSans-Bold.ttf"], s)
def medium(s):
    return _load([f"{REPO_FONTS}/Poppins-Medium.ttf", f"{GF}/Poppins-Medium.ttf",
                  f"{DV}/DejaVuSans-Bold.ttf"], s)
def regular(s):
    return _load([f"{REPO_FONTS}/Poppins-Regular.ttf", f"{GF}/Poppins-Regular.ttf",
                  f"{DV}/DejaVuSans.ttf"], s)
def light(s):
    return _load([f"{REPO_FONTS}/Poppins-Light.ttf", f"{GF}/Poppins-Light.ttf",
                  f"{DV}/DejaVuSans.ttf"], s)
def mono(s):
    return _load([f"{DV}/DejaVuSansMono.ttf"], s)


def _f(path, size):  # kept for any direct callers
    return _load([path, f"{DV}/DejaVuSans.ttf"], size)


def _wrap(d, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=fnt) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _rounded(d, box, r, fill):
    d.rounded_rectangle(box, radius=r, fill=fill)


def _ambient(d, hue, dark=True):
    """Soft ambient circles for depth (cover + dark slides)."""
    base = INK if dark else PAPER
    glow = tuple(min(255, c + (40 if dark else -14)) for c in (hue if dark else (210, 208, 200)))
    rnd = random.Random(hue[0] * 7 + hue[1])
    for _ in range(4):
        r = rnd.randint(150, 330)
        cx = rnd.randint(60, SIZE - 60); cy = rnd.randint(40, HEIGHT - 40)
        a = rnd.randint(16, 34)
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  fill=(glow[0], glow[1], glow[2], a))


def _logo(d, x, y, size=40, on_dark=True):
    f = bold(size)
    col = WHITE if on_dark else INK
    d.text((x, y), "The Last ", font=f, fill=col)
    w = d.textlength("The Last ", font=f)
    d.text((x + w, y), "24", font=f, fill=GREEN)


def _strip(d, x, y, w, hue, on_dark=True):
    """The little 24-tick strip motif."""
    n, gap = 16, w / 16
    for i in range(n):
        lit = i in (2, 5, 9, 13)
        col = hue if lit else ((70, 78, 70) if on_dark else (205, 205, 198))
        d.rectangle([x + i * gap, y, x + i * gap + gap * 0.55, y + 6], fill=col)


def _photo(url, w, h):
    """Fetch + cover-crop a photo to (w,h). Returns Image or None."""
    try:
        import urllib.request, io
        req = urllib.request.Request(url, headers={"User-Agent": "thelast24/1.0"})
        raw = urllib.request.urlopen(req, timeout=20).read()
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        iw, ih = im.size
        tr = w / h
        if iw / ih > tr:
            nw = int(ih * tr); x0 = (iw - nw) // 2
            im = im.crop((x0, 0, x0 + nw, ih))
        else:
            nh = int(iw / tr); y0 = (ih - nh) // 2
            im = im.crop((0, y0, iw, y0 + nh))
        return im.resize((w, h))
    except Exception:
        return None


# --------------------------------------------------------------------------
# COVER — keeps the established design language (dark, ambient, big headline)
# --------------------------------------------------------------------------
def cover(section_name, sid, date_label, headline, source=None):
    hue = SECTION_HUES.get(sid, (39, 185, 123))
    img = Image.new("RGB", (SIZE, HEIGHT), INK)
    d = ImageDraw.Draw(img, "RGBA")
    _ambient(d, hue, dark=True)
    # brand
    _logo(d, 70, 80, 44, on_dark=True)
    d.text((72, 140), date_label.upper(), font=mono(22), fill=META_DARK)
    # strip motif mid
    _strip(d, 70, 430, SIZE - 140, hue, on_dark=True)
    # category eyebrow with dot
    ey = 470
    d.ellipse([72, ey + 7, 86, ey + 21], fill=hue)
    d.text((100, ey), section_name.upper(), font=mono(24), fill=hue)
    # big headline
    y = 520
    hf = bold(76)
    for line in _wrap(d, headline, hf, SIZE - 150)[:5]:
        d.text((70, y), line, font=hf, fill=WHITE); y += 88
    # verified pill
    if source:
        py = max(y + 20, HEIGHT - 230)
        label = f"✓ via {source}"
        pw = d.textlength(label, font=mono(24)) + 44
        _rounded(d, [70, py, 70 + pw, py + 50], 25, (hue[0], hue[1], hue[2], 60))
        d.text((92, py + 12), label, font=mono(24), fill=WHITE)
    # footer
    d.text((70, HEIGHT - 90), "Swipe", font=medium(30), fill=GREEN)
    sw = d.textlength("Swipe", font=medium(30))
    ax = 70 + sw + 16; ay = HEIGHT - 75
    d.line([(ax, ay), (ax + 30, ay)], fill=GREEN, width=3)
    d.line([(ax + 22, ay - 8), (ax + 30, ay), (ax + 22, ay + 8)], fill=GREEN, width=3, joint="curve")
    d.text((SIZE - 70, HEIGHT - 86), "@thelast24", font=mono(24), fill=META_DARK, anchor="ra")
    return img


# --------------------------------------------------------------------------
# LIGHT body slide — floating white card, dots, slide number, kicker
# --------------------------------------------------------------------------
def light_slide(kicker, heading, points, idx, total, source_line=None, photo_url=None):
    img = Image.new("RGB", (SIZE, HEIGHT), PAPER)
    d = ImageDraw.Draw(img, "RGBA")
    _ambient(d, (210, 208, 200), dark=False)
    # slide number top-right
    d.text((SIZE - 60, 70), f"{idx:02d} / {total:02d}", font=mono(24), fill=META_LIGHT, anchor="ra")
    # optional photo band at top of the card area
    card_top = 150
    card = [60, card_top, SIZE - 60, HEIGHT - 150]
    _rounded(d, card, 28, PAPER_CARD)
    inner_x = 100
    y = card_top + 56
    if photo_url:
        ph = _photo(photo_url, SIZE - 160, 300)
        if ph is not None:
            # rounded photo at top inside card
            mask = Image.new("L", ph.size, 0)
            md = ImageDraw.Draw(mask)
            md.rounded_rectangle([0, 0, ph.size[0], ph.size[1]], radius=18, fill=255)
            img.paste(ph, (80, card_top + 30), mask)
            y = card_top + 30 + 300 + 40
    # kicker
    d.text((inner_x, y), kicker.upper(), font=mono(22), fill=GREEN_DEEP); y += 44
    # heading
    hf = bold(58)
    for line in _wrap(d, heading, hf, SIZE - 2 * inner_x)[:3]:
        d.text((inner_x, y), line, font=hf, fill=INK); y += 66
    y += 24
    # points with colored dots + emphasis
    for pt in points[:4]:
        d.ellipse([inner_x, y + 12, inner_x + 14, y + 26], fill=GREEN)
        pf = regular(34)
        for i, line in enumerate(_wrap(d, pt, pf, SIZE - 2 * inner_x - 44)[:3]):
            d.text((inner_x + 40, y), line, font=pf, fill=INK_SOFT); y += 46
        y += 22
    # footer: sources left, brand right
    fy = HEIGHT - 150 - 56
    if source_line:
        d.text((inner_x, fy), source_line, font=mono(20), fill=META_LIGHT)
    _logo(d, SIZE - 230, fy - 6, 28, on_dark=False)
    return img


# --------------------------------------------------------------------------
# DARK body slide — big heading, left-accent points, green emphasis
# --------------------------------------------------------------------------
def dark_slide(kicker, heading, points, idx, total, source_line=None, photo_url=None):
    hue = (39, 185, 123)
    img = Image.new("RGB", (SIZE, HEIGHT), INK)
    d = ImageDraw.Draw(img, "RGBA")
    _ambient(d, (39, 120, 90), dark=True)
    d.text((SIZE - 60, 70), f"{idx:02d} / {total:02d}", font=mono(24), fill=META_DARK, anchor="ra")
    x = 80
    y = 150
    if photo_url:
        ph = _photo(photo_url, SIZE - 160, 320)
        if ph is not None:
            ph = ImageEnhance.Brightness(ph).enhance(0.85)
            mask = Image.new("L", ph.size, 0)
            md = ImageDraw.Draw(mask)
            md.rounded_rectangle([0, 0, ph.size[0], ph.size[1]], radius=20, fill=255)
            img.paste(ph, (80, y), mask)
            y += 320 + 46
    # kicker
    d.text((x, y), kicker.upper(), font=mono(22), fill=GREEN); y += 44
    # heading
    hf = bold(62)
    for line in _wrap(d, heading, hf, SIZE - 2 * x)[:3]:
        d.text((x, y), line, font=hf, fill=WHITE); y += 72
    y += 28
    # points with left accent bar
    for pt in points[:4]:
        pf = regular(34)
        lines = _wrap(d, pt, pf, SIZE - 2 * x - 30)[:3]
        block_h = len(lines) * 46
        d.rectangle([x, y + 4, x + 6, y + block_h], fill=GREEN)
        yy = y
        for line in lines:
            d.text((x + 28, yy), line, font=pf, fill=(214, 220, 212)); yy += 46
        y += block_h + 28
    fy = HEIGHT - 110
    if source_line:
        d.text((x, fy), source_line, font=mono(20), fill=META_DARK)
    _logo(d, SIZE - 230, fy - 6, 28, on_dark=True)
    return img


# --------------------------------------------------------------------------
# OUTRO — dark, CTA
# --------------------------------------------------------------------------
def outro(sid):
    hue = SECTION_HUES.get(sid, (39, 185, 123))
    img = Image.new("RGB", (SIZE, HEIGHT), INK)
    d = ImageDraw.Draw(img, "RGBA")
    _ambient(d, hue, dark=True)
    _logo(d, 70, 470, 56, on_dark=True)
    d.text((70, 580), "The full brief, every day", font=regular(38), fill=(214, 220, 212))
    d.text((70, 640), "thelast24.in", font=bold(54), fill=GREEN)
    d.text((70, 740), "Everything that mattered in India,", font=regular(30), fill=META_DARK)
    d.text((70, 782), "in five minutes.", font=regular(30), fill=META_DARK)
    _strip(d, 70, HEIGHT - 130, SIZE - 140, hue, on_dark=True)
    d.text((SIZE - 70, HEIGHT - 88), "@thelast24", font=mono(24), fill=META_DARK, anchor="ra")
    return img
