#!/usr/bin/env python3
"""
The Last 24 — Instagram carousel generator.

Runs once a day (08:00 IST). Reads YESTERDAY's saved editions and renders, per
section, a branded Instagram carousel (1080x1080 PNG slides) summarising the
day: a cover slide + one slide per story + an outro slide. Also writes a
caption with hashtags per carousel. n8n picks up social/instagram/<date>/ and
posts each section's carousel.

Brand: dark tile, green "24", category colour accents, the 24-hour-strip motif.
No real people are drawn; slides are typographic (headline + context on brand
background), which is fully compliant and on-brand.

Output:
  social/instagram/<YYYY-MM-DD>/<section>/slide-01.png ...
  social/instagram/<YYYY-MM-DD>/<section>/caption.txt
  social/instagram/<YYYY-MM-DD>/manifest.json   (for n8n: sections, files, captions)
"""
import os, json, glob, textwrap
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw, ImageFont

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(IST)
SIZE = 1080

INK = (13, 18, 13)
PAPER = (242, 244, 238)
GREEN_BRIGHT = (59, 203, 141)
META = (146, 156, 142)
CELL_OFF = (38, 49, 42)
VERMILION = (222, 74, 36)

SECTION_HUES = {
    "national": (14, 123, 82), "world": (31, 95, 168), "business": (176, 122, 31),
    "tech": (106, 63, 181), "ai": (14, 142, 142), "sports": (206, 61, 29),
    "entertainment": (194, 49, 126),
}
HASHTAGS = {
    "national": ["#IndiaNews", "#India"], "world": ["#WorldNews", "#India"],
    "business": ["#Business", "#Markets", "#India"], "tech": ["#Tech", "#India"],
    "ai": ["#AI", "#ArtificialIntelligence"], "sports": ["#Sports", "#India"],
    "entertainment": ["#Entertainment", "#Bollywood"],
}

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
def font(name, size):
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)

F_DISPLAY = "DejaVuSans-Bold.ttf"
F_BODY = "DejaVuSans.ttf"
F_MONO = "DejaVuSansMono.ttf"


def wrap(draw, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=fnt) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_strip(d, x, y, w, hue):
    """The signature 24-hour cell strip."""
    n, gap = 24, 5
    cw = (w - gap * (n - 1)) / n
    lit = {2, 5, 7, 8, 11, 14, 17, 20, 22}
    for i in range(n):
        cx = x + i * (cw + gap)
        color = hue if i in lit else CELL_OFF
        d.rounded_rectangle([cx, y, cx + cw, y + 12], radius=3, fill=color)


def logo(d, x, y, size=40):
    f = font(F_DISPLAY, size)
    d.text((x, y), "The Last ", font=f, fill=PAPER)
    w = d.textlength("The Last ", font=f)
    d.text((x + w, y), "24", font=f, fill=GREEN_BRIGHT)


def cover_slide(section_name, sid, date_label, count):
    img = Image.new("RGB", (SIZE, SIZE), INK)
    d = ImageDraw.Draw(img)
    hue = SECTION_HUES.get(sid, (14, 123, 82))
    logo(d, 70, 70, 44)
    d.text((70, 140), "VERIFIED PUBLISHERS ONLY", font=font(F_MONO, 20), fill=META)
    # big section label
    d.text((70, 360), section_name.upper(), font=font(F_DISPLAY, 78), fill=PAPER)
    d.rectangle([70, 470, 70 + 120, 478], fill=hue)
    d.text((70, 510), "What mattered yesterday", font=font(F_BODY, 40), fill=PAPER)
    d.text((70, 575), date_label, font=font(F_MONO, 26), fill=META)
    draw_strip(d, 70, 880, SIZE - 140, hue)
    d.text((70, 920), f"{count} stories  ·  swipe →", font=font(F_MONO, 24), fill=META)
    return img


def story_slide(st, section_name, sid, idx, total):
    img = Image.new("RGB", (SIZE, SIZE), PAPER)
    d = ImageDraw.Draw(img)
    hue = SECTION_HUES.get(sid, (14, 123, 82))
    # top band
    d.rectangle([0, 0, SIZE, 90], fill=INK)
    logo(d, 50, 26, 30)
    d.text((SIZE - 160, 36), f"{idx}/{total}", font=font(F_MONO, 24), fill=META)
    # kicker
    d.ellipse([70, 150, 88, 168], fill=hue)
    d.text((100, 148), section_name.upper(), font=font(F_MONO, 24), fill=hue)
    if st.get("breaking"):
        d.text((100 + d.textlength(section_name.upper(), font=font(F_MONO, 24)) + 30, 148),
               "● BREAKING", font=font(F_MONO, 24), fill=VERMILION)
    # headline
    hl_font = font(F_DISPLAY, 54)
    y = 230
    for line in wrap(d, st["headline"], hl_font, SIZE - 140)[:5]:
        d.text((70, y), line, font=hl_font, fill=INK)
        y += 66
    # context (the "what")
    y += 20
    ctx = st.get("what", "")
    ctx_font = font(F_BODY, 33)
    for line in wrap(d, ctx, ctx_font, SIZE - 140)[:6]:
        d.text((70, y), line, font=ctx_font, fill=(67, 73, 63))
        y += 46
    # why it matters
    if st.get("lens"):
        y = max(y + 20, 760)
        d.rectangle([70, y, 76, y + 110], fill=hue)
        d.text((96, y), "WHY IT MATTERS", font=font(F_MONO, 22), fill=hue)
        wy = y + 36
        for line in wrap(d, st["lens"], font(F_BODY, 28), SIZE - 200)[:3]:
            d.text((96, wy), line, font=font(F_BODY, 28), fill=(67, 73, 63))
            wy += 38
    # source footer
    d.text((70, 1000), f"via {st.get('source','')}  ✓", font=font(F_MONO, 24), fill=META)
    return img


def outro_slide(sid):
    img = Image.new("RGB", (SIZE, SIZE), INK)
    d = ImageDraw.Draw(img)
    hue = SECTION_HUES.get(sid, (14, 123, 82))
    logo(d, 70, 380, 60)
    d.text((70, 480), "Full brief, every day:", font=font(F_BODY, 40), fill=PAPER)
    d.text((70, 540), "thelast24.in", font=font(F_DISPLAY, 52), fill=GREEN_BRIGHT)
    d.text((70, 640), "Everything that mattered in India,", font=font(F_BODY, 30), fill=META)
    d.text((70, 680), "in five minutes.", font=font(F_BODY, 30), fill=META)
    draw_strip(d, 70, 880, SIZE - 140, hue)
    return img


def build_caption(section_name, sid, stories, date_label):
    lead = stories[0]["headline"] if stories else ""
    lines = [f"📍 {section_name} — what mattered in India yesterday ({date_label})", ""]
    for st in stories:
        lines.append(f"• {st['headline']}")
    lines += ["", "Full brief → thelast24.in", "Curated from verified publishers only. ✓", ""]
    tags = HASHTAGS.get(sid, ["#IndiaNews"]) + ["#TheLast24", "#News"]
    lines.append(" ".join(tags))
    return "\n".join(lines)


def yesterday_sections():
    """Collect yesterday's stories grouped by section from saved editions."""
    y = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
    by_section = {}
    order = []
    for path in sorted(glob.glob("editions/*.json")):
        if not os.path.basename(path).startswith(y):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                ed = json.load(f)
        except Exception:
            continue
        for sec in ed.get("sections", []):
            sid = sec["id"]
            if sid not in by_section:
                by_section[sid] = {"name": sec["name"], "stories": [], "seen": set()}
                order.append(sid)
            for st in sec.get("stories", []):
                key = st.get("slug") or st.get("headline")
                if key in by_section[sid]["seen"]:
                    continue
                by_section[sid]["seen"].add(key)
                by_section[sid]["stories"].append(st)
    return y, order, by_section


def main():
    date_str, order, by_section = yesterday_sections()
    if not order:
        print(f"No editions found for yesterday ({date_str}); nothing to build.")
        return
    date_label = (NOW - timedelta(days=1)).strftime("%A, %d %B %Y")
    base = f"social/instagram/{date_str}"
    os.makedirs(base, exist_ok=True)
    manifest = {"date": date_str, "label": date_label, "sections": []}

    for sid in order:
        sec = by_section[sid]
        stories = sec["stories"][:5]  # up to 5 per carousel
        if not stories:
            continue
        sdir = os.path.join(base, sid)
        os.makedirs(sdir, exist_ok=True)
        slides = []

        cover = cover_slide(sec["name"], sid, date_label, len(stories))
        p = os.path.join(sdir, "slide-01.png"); cover.save(p); slides.append(p)
        for i, st in enumerate(stories, start=1):
            s = story_slide(st, sec["name"], sid, i, len(stories))
            p = os.path.join(sdir, f"slide-{i+1:02d}.png"); s.save(p); slides.append(p)
        outro = outro_slide(sid)
        p = os.path.join(sdir, f"slide-{len(stories)+2:02d}.png"); outro.save(p); slides.append(p)

        caption = build_caption(sec["name"], sid, stories, date_label)
        with open(os.path.join(sdir, "caption.txt"), "w", encoding="utf-8") as f:
            f.write(caption)

        manifest["sections"].append({
            "id": sid, "name": sec["name"], "slides": slides,
            "caption_file": os.path.join(sdir, "caption.txt"),
            "slide_count": len(slides),
        })
        print(f"  {sec['name']}: {len(slides)} slides")

    with open(os.path.join(base, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"Instagram carousels built for {len(manifest['sections'])} sections -> {base}")


if __name__ == "__main__":
    main()
