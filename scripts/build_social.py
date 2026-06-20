#!/usr/bin/env python3
"""
The Last 24 — Instagram carousel generator (v2).

Runs once a day (08:00 IST). Reads YESTERDAY's saved editions and renders, per
section, a branded Instagram carousel (1080x1080 PNG slides) summarising the
day, plus a rich, Claude-written caption.

Design (v2):
  - Cover slide: "Everything that happened in <Category> on <Date> — flip
    through to read more."
  - Story slides: lighter text (headline + one tight context line). Background
    is MIXED per story:
      * a highly-relevant image (Wikimedia real-subject photo, or a strongly
        scored stock photo), dimmed so text stays readable; OR
      * a branded pattern in the category colour (24-strip motif / shapes)
        when no strong image match exists.
    No real-people AI images; weak matches fall back to patterns, not random
    photos.
  - Caption: written by Claude — varied opening, short per-story summaries,
    warm-but-credible voice, hashtags. (~1 API call per section.)

Output:
  social/instagram/<YYYY-MM-DD>/<section>/slide-01.png ...
  social/instagram/<YYYY-MM-DD>/<section>/caption.txt
  social/instagram/<YYYY-MM-DD>/manifest.json
"""
import os, json, glob, io
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import requests

# Reuse the relevance-first image resolver + Claude helpers from the pipeline.
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "build_edition", os.path.join(os.path.dirname(__file__), "build_edition.py"))
_be = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_be)
except Exception as _e:
    print(f"warn: could not import build_edition helpers: {_e}")
    _be = None

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(IST)
SIZE = 1080         # width
HEIGHT = 1350       # height — Instagram 4:5 portrait (1080x1350)

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
    "national": ["#IndiaNews", "#India"], "world": ["#WorldNews", "#GlobalNews"],
    "business": ["#Business", "#Markets", "#Economy"], "tech": ["#Tech", "#Technology"],
    "ai": ["#AI", "#ArtificialIntelligence"], "sports": ["#Sports", "#Cricket"],
    "entertainment": ["#Entertainment", "#Bollywood"],
}

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
def font(name, size):
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)

F_DISPLAY = "DejaVuSans-Bold.ttf"
F_BODY = "DejaVuSans.ttf"
F_MONO = "DejaVuSansMono.ttf"


# ----------------------------------------------------------------------------
# Text helpers
# ----------------------------------------------------------------------------
def wrap(draw, text, fnt, max_w):
    words, lines, cur = (text or "").split(), [], ""
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


def draw_strip(d, x, y, w, hue, h=12):
    n, gap = 24, 5
    cw = (w - gap * (n - 1)) / n
    lit = {2, 5, 7, 8, 11, 14, 17, 20, 22}
    for i in range(n):
        cx = x + i * (cw + gap)
        color = hue if i in lit else CELL_OFF
        d.rounded_rectangle([cx, y, cx + cw, y + h], radius=3, fill=color)


def logo(d, x, y, size=40):
    f = font(F_DISPLAY, size)
    d.text((x, y), "The Last ", font=f, fill=PAPER)
    w = d.textlength("The Last ", font=f)
    d.text((x + w, y), "24", font=f, fill=GREEN_BRIGHT)


# ----------------------------------------------------------------------------
# Backgrounds: relevant photo (dimmed) OR branded pattern
# ----------------------------------------------------------------------------
def _branded_pattern(hue):
    """Branded pattern background in the category hue: dark base, soft tonal
    shapes, and a ring accent. Always on-brand, never blank."""
    import random
    img = Image.new("RGB", (SIZE, HEIGHT), INK)
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, SIZE, HEIGHT], fill=(hue[0], hue[1], hue[2], 26))
    rnd = random.Random(hue[0] * 100 + hue[1])
    for _ in range(5):
        r = rnd.randint(140, 320)
        cx = rnd.randint(0, SIZE); cy = rnd.randint(0, HEIGHT)
        a = rnd.randint(18, 40)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(hue[0], hue[1], hue[2], a))
    d.ellipse([SIZE - 360, -120, SIZE + 120, 360], outline=(hue[0], hue[1], hue[2], 90), width=6)
    return img


def _photo_background(image_url):
    """Download a photo and turn it into a readable dimmed background: cover-
    cropped square, darkened, slight blur, dark scrim at the foot so white text
    reads. Returns an Image or None on failure."""
    try:
        r = requests.get(image_url, timeout=20,
                         headers={"User-Agent": "TheLast24/1.0 (support@thelast24.in)"})
        r.raise_for_status()
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception as exc:
        print(f"  bg photo failed ({exc}); using pattern")
        return None
    w, h = im.size
    # cover-crop to 4:5 portrait (1080x1350)
    target_ratio = SIZE / HEIGHT
    if w / h > target_ratio:
        new_w = int(h * target_ratio)
        x0 = (w - new_w) // 2
        im = im.crop((x0, 0, x0 + new_w, h))
    else:
        new_h = int(w / target_ratio)
        y0 = (h - new_h) // 2
        im = im.crop((0, y0, w, y0 + new_h))
    im = im.resize((SIZE, HEIGHT))
    im = ImageEnhance.Brightness(im).enhance(0.55)
    im = im.filter(ImageFilter.GaussianBlur(1.2))
    scrim = Image.new("RGBA", (SIZE, HEIGHT), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    for y in range(HEIGHT):
        if y < HEIGHT * 0.42:
            a = 60
        else:
            a = int(60 + (y - HEIGHT * 0.42) / (HEIGHT * 0.58) * 150)
        sd.line([(0, y), (SIZE, y)], fill=(8, 11, 8, min(a, 220)))
    im = Image.alpha_composite(im.convert("RGBA"), scrim).convert("RGB")
    return im


def story_background(st, hue, used_images):
    """Per-story background: strong relevant photo (dimmed) else branded
    pattern. Returns (image, used_url_or_None, is_photo).

    Primary source is the image the edition ALREADY resolved and stored on the
    story (st['image']) — this guarantees the carousel shows the same photo the
    website shows. Only if that's missing do we try a fresh lookup."""
    chosen_url = None
    # Primary: the photo already resolved by build_edition (website's image).
    existing = st.get("image")
    if existing and isinstance(existing, str) and existing.startswith("http") \
            and existing not in used_images:
        chosen_url = existing
    elif _be is not None:
        # Fallback: resolve fresh (Wikimedia subject, then stock query).
        subject = st.get("image_subject")
        query = st.get("image_query") or st.get("headline")
        try:
            wiki = _be.fetch_wikimedia(subject) if subject else None
        except Exception:
            wiki = None
        if wiki and wiki.get("image") and wiki["image"] not in used_images:
            chosen_url = wiki["image"]
        else:
            try:
                photo = _be.fetch_photo(query, used_images) if query else None
            except Exception:
                photo = None
            if photo and photo.get("image"):
                chosen_url = photo["image"]
    if chosen_url:
        bg = _photo_background(chosen_url)
        if bg is not None:
            return bg, chosen_url, True
    return _branded_pattern(hue), None, False


# ----------------------------------------------------------------------------
# Slides
# ----------------------------------------------------------------------------
def cover_slide(section_name, sid, date_label):
    img = Image.new("RGB", (SIZE, HEIGHT), INK)
    d = ImageDraw.Draw(img, "RGBA")
    hue = SECTION_HUES.get(sid, (14, 123, 82))
    d.rectangle([0, 0, SIZE, HEIGHT], fill=(hue[0], hue[1], hue[2], 22))
    d.ellipse([SIZE - 380, -140, SIZE + 120, 340], fill=(hue[0], hue[1], hue[2], 40))
    d.ellipse([-160, HEIGHT - 300, 240, HEIGHT + 120], fill=(hue[0], hue[1], hue[2], 30))
    logo(d, 70, 72, 40)
    y = 360
    head_f = font(F_DISPLAY, 64)
    for line in wrap(d, f"Everything that happened in {section_name}", head_f, SIZE - 150):
        d.text((70, y), line, font=head_f, fill=PAPER); y += 78
    d.rectangle([74, y + 6, 74 + 90, y + 12], fill=hue)
    d.text((70, y + 34), f"on {date_label}", font=font(F_BODY, 36), fill=PAPER)
    d.text((70, HEIGHT - 150), "Flip through to read more  \u2192",
           font=font(F_DISPLAY, 32), fill=GREEN_BRIGHT)
    draw_strip(d, 70, HEIGHT - 80, SIZE - 140, hue)
    return img


def story_slide(st, section_name, sid, idx, total, used_images):
    hue = SECTION_HUES.get(sid, (14, 123, 82))
    bg, used_url, is_photo = story_background(st, hue, used_images)
    img = bg.copy()
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, SIZE, 88], fill=(13, 18, 13, 235))
    logo(d, 50, 26, 30)
    d.text((SIZE - 150, 34), f"{idx}/{total}", font=font(F_MONO, 24), fill=META)
    d.ellipse([70, 150, 88, 168], fill=hue)
    d.text((100, 147), section_name.upper(), font=font(F_MONO, 24), fill=PAPER)
    if st.get("breaking"):
        kw = d.textlength(section_name.upper(), font=font(F_MONO, 24))
        d.text((100 + kw + 26, 147), "\u25cf BREAKING", font=font(F_MONO, 24), fill=VERMILION)
    hl_font = font(F_DISPLAY, 52)
    hl_lines = wrap(d, st["headline"], hl_font, SIZE - 140)[:5]
    block_h = len(hl_lines) * 62
    ctx = (st.get("what") or "").strip()
    if ctx:
        first = ctx.split(". ")[0].strip()
        if not first.endswith("."):
            first += "."
        ctx = first
    ctx_font = font(F_BODY, 30)
    ctx_lines = wrap(d, ctx, ctx_font, SIZE - 140)[:2]
    total_h = block_h + 24 + len(ctx_lines) * 42
    y = HEIGHT - 150 - total_h
    for line in hl_lines:
        d.text((70, y), line, font=hl_font, fill=PAPER); y += 62
    y += 20
    for line in ctx_lines:
        d.text((70, y), line, font=ctx_font, fill=(214, 220, 210)); y += 42
    d.text((70, HEIGHT - 70), f"via {st.get('source','')}  \u2713", font=font(F_MONO, 22), fill=META)
    return img, used_url


def outro_slide(sid):
    img = _branded_pattern(SECTION_HUES.get(sid, (14, 123, 82)))
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, SIZE, HEIGHT], fill=(13, 18, 13, 150))
    hue = SECTION_HUES.get(sid, (14, 123, 82))
    logo(d, 70, 480, 56)
    d.text((70, 580), "The full brief, every day:", font=font(F_BODY, 38), fill=PAPER)
    d.text((70, 636), "thelast24.in", font=font(F_DISPLAY, 50), fill=GREEN_BRIGHT)
    d.text((70, 732), "Everything that mattered in India,", font=font(F_BODY, 28), fill=(214, 220, 210))
    d.text((70, 768), "in five minutes.", font=font(F_BODY, 28), fill=(214, 220, 210))
    draw_strip(d, 70, HEIGHT - 130, SIZE - 140, hue)
    return img


# ----------------------------------------------------------------------------
# Caption (Claude-written)
# ----------------------------------------------------------------------------
def build_caption(section_name, sid, stories, date_label):
    """Rich, Instagram-friendly caption written by Claude: varied opening, short
    per-story summaries, warm-but-credible voice, hashtags. Falls back to a
    simple assembled caption if the API is unavailable."""
    tags = HASHTAGS.get(sid, ["#IndiaNews"]) + ["#TheLast24", "#NewsIndia"]
    tagline = " ".join(tags)
    if _be is not None:
        items = "\n".join(f"- {s['headline']}: {s.get('what','')}" for s in stories)
        sys_prompt = (
            "You write Instagram captions for 'The Last 24', a verified Indian "
            "news brief. Voice: warm but credible — a smart friend who reads the "
            "news so others don't have to. Not stiff, not clickbait.\n"
            f"Write ONE caption summarising the day's {section_name} stories for "
            f"{date_label}.\n"
            "Structure: (1) a fresh, varied opening line that hooks — vary it, "
            "don't always start the same way; sometimes a teaser of the biggest "
            "story, sometimes a 'here's what you missed', sometimes a question. "
            "(2) a short, plain-language 1-2 sentence summary of EACH story, in "
            "flowing form (you may use a line break between stories, but keep it "
            "natural, not rigidly bulleted). (3) a soft close pointing readers to "
            "the full brief at thelast24.in. Keep it under 1400 characters before "
            "hashtags. Indian English, accurate, no invented facts.\n"
            'Respond with ONLY JSON: {"caption":"...the caption text..."}')
        try:
            data = _be.extract_json(
                _be.call_claude(sys_prompt, f"Stories:\n{items}", 1500), "caption")
            cap = str(data.get("caption", "")).strip()
            if cap:
                return cap + "\n\n" + tagline
        except Exception as exc:
            print(f"  caption generation failed ({exc}); using simple caption")
    lines = [f"What mattered in {section_name} \u2014 {date_label}", ""]
    for s in stories:
        summ = (s.get("what") or "").split(". ")[0]
        lines.append(f"\u2022 {s['headline']} \u2014 {summ}.")
    lines += ["", "Full brief \u2192 thelast24.in", "", tagline]
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Read yesterday, build
# ----------------------------------------------------------------------------
def yesterday_sections():
    y = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
    by_section, order = {}, []
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


def _wc_font(bold=True, size=48):
    return font("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)


def build_worldcup_carousel(base):
    """Generate a World Cup daily Instagram carousel: cover + scores + standings.
    Pulls data via build_worldcup. Returns a manifest section dict or None."""
    try:
        import build_worldcup as bwc
        if not bwc.ENABLED:
            return None
        data = bwc._fetch()
    except Exception as exc:
        print(f"World Cup IG: data fetch failed ({exc}); skipping.")
        return None
    recent, today, upcoming = bwc._matches_view(data.get("matches", []))
    standings = bwc._compute_standings(data.get("matches", []))
    if not recent and not standings:
        return None

    WC = (22, 135, 107)
    sdir = os.path.join(base, "worldcup")
    os.makedirs(sdir, exist_ok=True)
    slides = []
    date_label = NOW.strftime("%A, %d %B %Y")

    # --- Slide 1: cover ---
    img = Image.new("RGB", (SIZE, HEIGHT), INK); d = ImageDraw.Draw(img)
    d.rectangle([0, 0, SIZE, 12], fill=WC)
    d.text((80, 440), "FIFA WORLD CUP", font=_wc_font(True, 86), fill=PAPER)
    d.text((80, 550), "2026", font=_wc_font(True, 120), fill=GREEN_BRIGHT)
    d.text((80, 740), "Daily scores & standings", font=_wc_font(False, 46), fill=PAPER)
    d.text((80, 800), date_label, font=_wc_font(False, 38), fill=META)
    d.text((80, HEIGHT - 80), "THE LAST 24  ·  times in IST", font=_wc_font(False, 30), fill=META)
    p = os.path.join(sdir, "slide-01.png"); img.save(p); slides.append(p)

    # --- Slide 2: latest scores ---
    if recent:
        img = Image.new("RGB", (SIZE, HEIGHT), PAPER); d = ImageDraw.Draw(img)
        d.rectangle([0, 0, SIZE, 110], fill=WC)
        d.text((70, 32), "LATEST RESULTS", font=_wc_font(True, 50), fill=PAPER)
        y = 190
        for m in recent[:6]:
            d.text((70, y), f"{m['team1']}", font=_wc_font(True, 44), fill=INK)
            d.text((SIZE - 70, y), m["score"], font=_wc_font(True, 52), fill=WC, anchor="ra")
            d.text((70, y + 56), f"{m['team2']}", font=_wc_font(True, 44), fill=INK)
            d.text((70, y + 112), m["group"], font=_wc_font(False, 28), fill=META)
            y += 200
            if y > HEIGHT - 160:
                break
        p = os.path.join(sdir, "slide-02.png"); img.save(p); slides.append(p)

    # --- Slide 3+: standings (2 groups per slide) ---
    grp_items = list(standings.items())
    slide_no = len(slides) + 1
    for i in range(0, min(len(grp_items), 8), 2):
        img = Image.new("RGB", (SIZE, HEIGHT), PAPER); d = ImageDraw.Draw(img)
        d.rectangle([0, 0, SIZE, 110], fill=WC)
        d.text((70, 32), "GROUP STANDINGS", font=_wc_font(True, 50), fill=PAPER)
        y = 180
        for grp, rows in grp_items[i:i + 2]:
            d.text((70, y), grp, font=_wc_font(True, 40), fill=WC); y += 64
            for pos, r in enumerate(rows, 1):
                col = INK if pos <= 2 else META
                d.text((80, y), f"{pos}", font=_wc_font(True, 32), fill=col)
                d.text((140, y), r["team"], font=_wc_font(pos <= 2, 34), fill=col)
                d.text((SIZE - 80, y), str(r["Pts"]), font=_wc_font(True, 36),
                       fill=WC if pos <= 2 else META, anchor="ra")
                y += 52
            y += 40
        p = os.path.join(sdir, f"slide-{slide_no:02d}.png"); img.save(p)
        slides.append(p); slide_no += 1

    # caption
    top = "; ".join(f"{m['team1']} {m['score']} {m['team2']}" for m in recent[:3])
    caption = (f"FIFA World Cup 2026 — daily scores & standings ({date_label}).\n\n"
               f"{top}\n\nFull tables and fixtures (in IST) on our World Cup page.\n\n"
               "#FIFAWorldCup #WorldCup2026 #Football #IndiaNews #TheLast24")
    with open(os.path.join(sdir, "caption.txt"), "w", encoding="utf-8") as f:
        f.write(caption)
    print(f"World Cup IG carousel: {len(slides)} slides.")
    return {"id": "worldcup", "name": "World Cup", "slides": slides,
            "caption_file": os.path.join(sdir, "caption.txt"), "slide_count": len(slides)}


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
        stories = sec["stories"][:5]
        if not stories:
            continue
        sdir = os.path.join(base, sid)
        os.makedirs(sdir, exist_ok=True)
        slides, used_images = [], set()

        cover = cover_slide(sec["name"], sid, date_label)
        p = os.path.join(sdir, "slide-01.png"); cover.save(p); slides.append(p)

        for i, st in enumerate(stories, start=1):
            s, used_url = story_slide(st, sec["name"], sid, i, len(stories), used_images)
            if used_url:
                used_images.add(used_url)
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

    # World Cup daily carousel (scores + standings), if the tournament is on.
    try:
        wc_sec = build_worldcup_carousel(base)
        if wc_sec:
            manifest["sections"].append(wc_sec)
            print(f"  World Cup: {wc_sec['slide_count']} slides")
    except Exception as exc:
        print(f"  World Cup IG carousel skipped: {exc}")

    with open(os.path.join(base, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"Instagram carousels built for {len(manifest['sections'])} sections -> {base}")


if __name__ == "__main__":
    main()
