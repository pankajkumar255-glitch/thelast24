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
# ig_design (new dynamic layouts) kept available but not used by default;
# the previous slide design is the active one. Import made safe/optional.
try:
    import ig_design as ig
except Exception:
    ig = None
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
    "national": ["#IndiaNews", "#India", "#BharatNews", "#NewsUpdate", "#CurrentAffairs", "#IndianExpress", "#BreakingNews"],
    "world": ["#WorldNews", "#GlobalNews", "#InternationalNews", "#WorldAffairs", "#Geopolitics", "#NewsToday"],
    "business": ["#Business", "#Markets", "#Economy", "#StockMarket", "#BusinessNews", "#Finance", "#IndianEconomy", "#Sensex"],
    "tech": ["#Tech", "#Technology", "#TechNews", "#Innovation", "#Startups", "#IndianStartups", "#DigitalIndia", "#Gadgets"],
    "ai": ["#AI", "#ArtificialIntelligence", "#MachineLearning", "#TechNews", "#FutureTech", "#AINews", "#Innovation"],
    "sports": ["#Sports", "#Cricket", "#IndianSports", "#SportsNews", "#TeamIndia", "#Football", "#SportsUpdate"],
    "entertainment": ["#Entertainment", "#Bollywood", "#BollywoodNews", "#Cinema", "#OTT", "#EntertainmentNews", "#IndianCinema", "#Movies"],
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


SECTION_STOCK_QUERIES = {
    "national": ["india parliament building", "india flag government", "indian city street"],
    "world": ["world map globe", "international flags", "city skyline night"],
    "business": ["stock market chart", "indian rupee money", "business office building"],
    "tech": ["technology circuit", "smartphone laptop desk", "data server room"],
    "ai": ["artificial intelligence abstract", "computer code screen", "robot technology"],
    "sports": ["cricket stadium india", "sports stadium crowd", "football pitch"],
    "entertainment": ["cinema film reel", "movie theater seats", "stage lights concert"],
}


def story_background(st, hue, used_images, sid=None):
    """Per-story background: strong relevant photo (dimmed) else branded
    pattern. Returns (image, used_url_or_None, is_photo).

    Primary source is the image the edition ALREADY resolved and stored on the
    story (st['image']) — this guarantees the carousel shows the same photo the
    website shows. Only if that's missing do we try a fresh lookup, and finally
    a section-generic stock photo, so a slide gets a REAL image wherever
    possible rather than the abstract branded pattern."""
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
        # Last resort BEFORE the abstract pattern: a section-generic stock photo,
        # so the slide still shows a real, on-theme image.
        if not chosen_url and sid:
            for q in SECTION_STOCK_QUERIES.get(sid, []):
                try:
                    photo = _be.fetch_photo(q, used_images)
                except Exception:
                    photo = None
                if photo and photo.get("image"):
                    chosen_url = photo["image"]
                    break
    if chosen_url:
        bg = _photo_background(chosen_url)
        if bg is not None:
            return bg, chosen_url, True
    return _branded_pattern(hue), None, False


# ----------------------------------------------------------------------------
# Slides
# ----------------------------------------------------------------------------
def _cover_phrase(section_name, sid):
    """Natural-reading cover phrase per section. 'National' -> 'the nation',
    'World' -> 'the world', etc., so it reads 'Everything that happened in the
    nation' rather than the awkward 'Everything that happened in National'."""
    overrides = {
        "national": "the nation",
        "world": "the world",
        "business": "business & markets",
        "tech": "technology",
        "ai": "AI",
        "sports": "sports",
        "entertainment": "entertainment",
    }
    return overrides.get(sid, section_name.lower())


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
    phrase = _cover_phrase(section_name, sid)
    for line in wrap(d, f"Everything that happened in {phrase}", head_f, SIZE - 150):
        d.text((70, y), line, font=head_f, fill=PAPER); y += 78
    d.rectangle([74, y + 6, 74 + 90, y + 12], fill=hue)
    d.text((70, y + 34), f"on {date_label}", font=font(F_BODY, 36), fill=PAPER)
    d.text((70, HEIGHT - 150), "Flip through to read more  \u2192",
           font=font(F_DISPLAY, 32), fill=GREEN_BRIGHT)
    draw_strip(d, 70, HEIGHT - 80, SIZE - 140, hue)
    return img


def story_slide(st, section_name, sid, idx, total, used_images):
    hue = SECTION_HUES.get(sid, (14, 123, 82))
    bg, used_url, is_photo = story_background(st, hue, used_images, sid)
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
def build_linkedin_caption(section_name, sid, stories, date_label):
    """A LinkedIn-native caption with a strong opinionated hook and a real point
    of view — modelled on what actually performs: a bold/contrarian opening line
    in the first ~200 chars, POV-led commentary ('what this means'), no external
    link in the body, 3-5 hashtags."""
    LI_TAGS = {
        "ai": ["#ArtificialIntelligence", "#AI", "#Technology", "#Innovation"],
        "tech": ["#Technology", "#Innovation", "#Startups", "#India"],
        "world": ["#WorldNews", "#GlobalAffairs", "#Geopolitics"],
    }
    tags = LI_TAGS.get(sid, ["#News"]) + ["#TheLast24"]
    tagline = " ".join(tags[:5])
    if _be is not None:
        items = "\n".join(f"- {s['headline']}: {s.get('what','')}" for s in stories)
        sys_prompt = (
            "You write LinkedIn posts for 'The Last 24', a verified Indian news "
            "brief, in the voice of a sharp industry commentator with a clear "
            "POINT OF VIEW — the kind of post professionals actually stop to read "
            "and argue with in the comments. NOT a neutral news summary, NOT the "
            "casual Instagram voice.\n"
            f"Write ONE LinkedIn post reacting to today's {section_name} stories "
            f"({date_label}).\n"
            "WHAT MAKES IT WORK (follow closely):\n"
            "- HOOK FIRST: the opening 1-2 lines (under ~200 characters) must land "
            "before LinkedIn's 'see more' cut. Use a bold statement, a contrarian "
            "take, a striking specific number, or 'here's what everyone's missing' "
            "energy. Take a POSITION — opinionated openings outperform neutral ones.\n"
            "- THEN THE SUBSTANCE: pull together the day's key developments and add "
            "YOUR read — what it means, why it matters, what to watch next. React "
            "as a commentator, don't just relay headlines. Name the specifics "
            "(companies, numbers, people).\n"
            "- Short paragraphs / line breaks for readability on mobile.\n"
            "- Close with a light prompt for discussion (an open question or a "
            "'what's your take?'), NOT a hard sell.\n"
            "- LENGTH: aim 600-1100 characters. Tight and punchy beats padded.\n"
            "- Do NOT put any external link or URL in the text (LinkedIn throttles "
            "posts with links). Do NOT add hashtags yourself. At most one tasteful "
            "emoji, optional.\n"
            "Indian English, accurate, never invent facts.\n"
            'Respond with ONLY JSON: {"caption":"...the post text..."}')
        try:
            data = _be.extract_json(
                _be.call_claude(sys_prompt, f"Stories:\n{items}", 1500), "caption")
            cap = str(data.get("caption", "")).strip()
            if cap:
                return cap + "\n\n" + tagline
        except Exception as exc:
            print(f"  LinkedIn caption generation failed ({exc}); using simple caption")
    lead = stories[0]
    lines = [f"{lead['headline']}.", "",
             "The stories shaping " + section_name.lower() + f" today ({date_label}):", ""]
    for s in stories:
        summ = (s.get("what") or "").split(". ")[0]
        lines.append(f"• {s['headline']} — {summ}.")
    lines += ["", "What's your read on this?", "", tagline]
    return "\n".join(lines)


def build_caption(section_name, sid, stories, date_label):
    """Rich, Instagram-friendly caption written by Claude: varied opening, short
    per-story summaries, warm-but-credible voice, hashtags. Falls back to a
    simple assembled caption if the API is unavailable."""
    tags = HASHTAGS.get(sid, ["#IndiaNews"]) + ["#TheLast24", "#NewsIndia", "#5MinuteRead", "#StayInformed"]
    tagline = " ".join(tags)
    if _be is not None:
        items = "\n".join(f"- {s['headline']}: {s.get('what','')}" for s in stories)
        sys_prompt = (
            "You write scroll-stopping Instagram captions for 'The Last 24', a "
            "verified Indian news brief. Voice: a sharp, clued-in friend who reads "
            "everything and gives the real gist — confident, human, a little "
            "personality. Native to Instagram, NOT a press release.\n"
            f"Write ONE caption for the day's {section_name} stories ({date_label}).\n"
            "FORMAT (Instagram-native):\n"
            "- Open with a STRONG hook line: a bold statement, a striking number, "
            "or 'here's what you actually need to know' energy. One tasteful emoji "
            "is fine; never spammy.\n"
            "- Then 2-4 tight lines, each capturing one story in plain, punchy "
            "language — what happened and why you'd care. Line breaks between them "
            "so it's skimmable. A leading arrow (\u2192) per line is fine.\n"
            "- Close pointing to the full brief at thelast24.in, plus an "
            "engagement nudge like 'Save this \U0001F4CC' or 'Follow @thelast24 for "
            "your daily 5-minute brief'.\n"
            "Under 1500 characters. Indian English, accurate, never invent facts. "
            "Do NOT add hashtags yourself — they're appended separately.\n"
            'Respond with ONLY JSON: {"caption":"...the caption text..."}')
        try:
            data = _be.extract_json(
                _be.call_claude(sys_prompt, f"Stories:\n{items}", 1500), "caption")
            cap = str(data.get("caption", "")).strip()
            if cap:
                return cap + "\n\n" + tagline
        except Exception as exc:
            print(f"  caption generation failed ({exc}); using simple caption")
    lines = [f"Here's what mattered in {section_name} today \U0001F4F0", ""]
    for s in stories:
        summ = (s.get("what") or "").split(". ")[0]
        lines.append(f"\u2192 {s['headline']} \u2014 {summ}.")
    lines += ["", "Full brief \U0001F449 thelast24.in", "Save this for later \U0001F4CC",
              "", tagline]
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Read yesterday, build
# ----------------------------------------------------------------------------
def _story_fingerprint(st):
    """Loose fingerprint matching the SAME story even when reworded by a
    different publisher. Set of significant words (>3 chars, minus filler) from
    the headline. Same event -> mostly the same words."""
    stop = {"the", "and", "for", "with", "from", "that", "this", "after", "over",
            "into", "amid", "says", "said", "will", "your", "you", "are", "was",
            "has", "have", "its", "his", "her", "their", "they", "them", "than",
            "more", "most", "new", "now", "set", "get", "but", "not", "all"}
    import re as _re
    words = _re.findall(r"[a-z0-9]+", (st.get("headline") or "").lower())
    return frozenset(w for w in words if len(w) > 3 and w not in stop)


def _is_dupe_fp(fp, seen_fps):
    """True if fp overlaps a seen fingerprint enough to be the same event."""
    if not fp or len(fp) < 4:
        return False
    for s in seen_fps:
        if not s or len(s) < 4:
            continue
        overlap = len(fp & s); union = len(fp | s)
        if union and overlap / union >= 0.5:   # 0.5 = aggressive for social
            return True
    return False


FRESH_WINDOW_HOURS = 28   # how far back to pull stories for the daily social run
STALE_AFTER_HOURS = 30    # drop any story older than this outright


def _story_age_hours(st):
    """Best-effort age of a story in hours, from any timestamp it carries.
    Returns None if no parseable time is found (treated as 'keep')."""
    for k in ("published", "pub_iso", "timestamp", "created", "date"):
        v = st.get(k)
        if not v:
            continue
        s = str(v).strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d %H:%M IST", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s.replace("Z", "+0000"), fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=IST)
                return (NOW - dt).total_seconds() / 3600.0
            except (ValueError, TypeError):
                continue
    return None


def yesterday_sections():
    """Collate stories for the daily social run from a ROLLING RECENT WINDOW of
    editions (not just 'yesterday'), so the 4 AM run uses the freshest stories —
    including today's midnight edition — and DROPS stale ones. Kept the function
    name for compatibility with main()."""
    by_section, order = {}, []
    cutoff_date = (NOW - timedelta(hours=FRESH_WINDOW_HOURS + 24)).strftime("%Y-%m-%d")
    label_day = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
    # NEWEST editions FIRST, so the freshest copy of a story is the one kept
    # (a breaking story with an image in the midnight edition beats a stale,
    # image-less copy of the same story from an earlier edition).
    paths = sorted(glob.glob("editions/*.json"), reverse=True)
    paths = [p for p in paths if os.path.basename(p)[:10] >= cutoff_date]
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                ed = json.load(f)
        except Exception:
            continue
        for sec in ed.get("sections", []):
            sid = sec["id"]
            if sid not in by_section:
                by_section[sid] = {"name": sec["name"], "stories": [],
                                   "seen": set(), "fps": []}
                order.append(sid)
            for st in sec.get("stories", []):
                # Drop stale stories outright (older than STALE_AFTER_HOURS).
                age = _story_age_hours(st)
                if age is not None and age > STALE_AFTER_HOURS:
                    continue
                key = st.get("slug") or st.get("headline")
                if key in by_section[sid]["seen"]:
                    continue
                fp = _story_fingerprint(st)
                dupe_idx = None
                for i, seen_fp in enumerate(by_section[sid]["fps"]):
                    if _is_dupe_fp(fp, [seen_fp]):
                        dupe_idx = i
                        break
                if dupe_idx is not None:
                    # We process newest-first, so the EXISTING copy is the fresher
                    # one — keep it. Only swap in the new (older) copy if it has an
                    # image and the kept one doesn't (a better visual).
                    existing = by_section[sid]["stories"][dupe_idx]
                    new_has_img = bool((st.get("image") or "").startswith("http"))
                    old_has_img = bool((existing.get("image") or "").startswith("http"))
                    if new_has_img and not old_has_img:
                        # keep the fresher copy's breaking flag, take the image
                        merged = dict(st)
                        merged["breaking"] = existing.get("breaking") or st.get("breaking")
                        by_section[sid]["stories"][dupe_idx] = merged
                    continue
                by_section[sid]["seen"].add(key)
                by_section[sid]["fps"].append(fp)
                by_section[sid]["stories"].append(st)
    # Within each section, freshest first (stories with a known age sort by age;
    # unknown-age stories keep their original order at the end).
    for sid in by_section:
        sl = by_section[sid]["stories"]
        sl.sort(key=lambda s: (_story_age_hours(s) is None, _story_age_hours(s) or 0))
    return label_day, order, by_section


def _wc_font(bold=True, size=48):
    return font("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)


def build_worldcup_summary_slide(sdir, slide_index):
    """Build a SINGLE Instagram slide summarising recent FIFA World Cup 2026
    results ("Team A beat Team B 2-1" with real scores and dates), to be slotted
    into the Sports carousel — instead of a separate World Cup carousel.
    Returns (slide_path, headline) or (None, None) if no data."""
    try:
        import build_worldcup as bwc
        if not bwc.ENABLED:
            return None, None
        data = bwc._fetch()
    except Exception as exc:
        print(f"World Cup summary slide: data fetch failed ({exc}); skipping.")
        return None, None
    recent, today, upcoming = bwc._matches_view(data.get("matches", []))
    if not recent:
        return None, None

    WC = (22, 135, 107)
    img = Image.new("RGB", (SIZE, HEIGHT), INK)
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, SIZE, HEIGHT], fill=(WC[0], WC[1], WC[2], 24))
    d.ellipse([SIZE - 360, -120, SIZE + 120, 320], fill=(WC[0], WC[1], WC[2], 45))
    logo(d, 70, 72, 38)
    d.text((70, 250), "FIFA WORLD CUP 2026", font=_wc_font(True, 40), fill=GREEN_BRIGHT)
    d.text((70, 308), "Latest results", font=font(F_DISPLAY, 60), fill=PAPER)
    y = 430
    # group results under their date so readers know when each happened
    last_date = None
    shown = 0
    for m in recent[:6]:
        if shown >= 6 or y > HEIGHT - 240:
            break
        dlabel = m.get("date_label", "")
        if dlabel and dlabel != last_date:
            d.text((70, y), dlabel.upper(), font=_wc_font(False, 26), fill=GREEN_BRIGHT)
            y += 46
            last_date = dlabel
        result = m.get("result") or f"{m['team1']} {m['score']} {m['team2']}"
        for line in wrap(d, result, font(F_DISPLAY, 38), SIZE - 170):
            d.text((90, y), line, font=font(F_DISPLAY, 38), fill=PAPER); y += 48
        sub = m.get("group", "")
        if m.get("ist"):
            sub = (sub + "  ·  " + m["ist"]) if sub else m["ist"]
        d.text((90, y), sub, font=font(F_MONO, 22), fill=META); y += 50
        shown += 1
    draw_strip(d, 70, HEIGHT - 80, SIZE - 140, WC)
    p = os.path.join(sdir, f"slide-{slide_index:02d}.png")
    img.save(p)
    return p, "FIFA World Cup 2026: latest results"


def build_instagram_stories(base, by_section, order, date_label):
    """Build up to 8 Instagram STORY images (9:16, 1080x1920) from the day's
    most important stories — one headline per story image, branded, with a
    'Read more on our page' cue (Buffer can auto-post Story media; tappable
    links aren't supported via the API, so we use the in-bio convention).
    Returns a list of {image, headline} dicts for the manifest."""
    STORY_W, STORY_H = 1080, 1920
    sdir = os.path.join(base, "stories")
    os.makedirs(sdir, exist_ok=True)
    # Gather the strongest stories across sections: prefer ones with a real image
    # and that are flagged breaking/important, keep section variety.
    pool = []
    for sid in order:
        for st in by_section[sid]["stories"]:
            pool.append((sid, st))
    # breaking first, then those with images, preserve order otherwise
    pool.sort(key=lambda p: (not p[1].get("breaking", False),
                             not (p[1].get("image") or "").startswith("http")))
    out, used_images = [], set()
    for idx, (sid, st) in enumerate(pool[:8], start=1):
        hue = SECTION_HUES.get(sid, (14, 123, 82))
        # vertical background from the story's photo, else section stock, else pattern
        bg, used_url, is_photo = story_background(st, hue, used_images, sid)
        if used_url:
            used_images.add(used_url)
        img = bg.resize((STORY_W, STORY_H)).convert("RGB") if bg.size != (STORY_W, STORY_H) else bg.convert("RGB")
        # rebuild as a true 9:16 canvas to avoid distortion: cover-crop
        src = bg.convert("RGB")
        scale = max(STORY_W / src.width, STORY_H / src.height)
        nw, nh = int(src.width * scale), int(src.height * scale)
        src = src.resize((nw, nh))
        left, top = (nw - STORY_W) // 2, (nh - STORY_H) // 2
        img = src.crop((left, top, left + STORY_W, top + STORY_H))
        d = ImageDraw.Draw(img, "RGBA")
        # darken for legibility
        d.rectangle([0, 0, STORY_W, STORY_H], fill=(8, 11, 9, 130))
        d.rectangle([0, STORY_H - 760, STORY_W, STORY_H], fill=(8, 11, 9, 150))
        logo(d, 70, 110, 46)
        # section kicker
        d.rectangle([70, 980, 70 + 90, 980 + 10], fill=hue)
        d.text((70, 1010), by_section[sid]["name"].upper(),
               font=font(F_MONO, 32), fill=(230, 232, 226))
        # headline
        y = 1080
        head_f = font(F_DISPLAY, 72)
        for line in wrap(d, st.get("headline", ""), head_f, STORY_W - 140)[:6]:
            d.text((70, y), line, font=head_f, fill=PAPER); y += 88
        # CTA
        d.text((70, STORY_H - 180), "Full story on our page  \u2192",
               font=font(F_DISPLAY, 40), fill=GREEN_BRIGHT)
        draw_strip(d, 70, STORY_H - 90, STORY_W - 140, hue)
        p = os.path.join(sdir, f"story-{idx:02d}.png")
        img.save(p)
        out.append({"image": p, "headline": st.get("headline", ""), "section": sid})
    print(f"  Instagram Stories: {len(out)} story images built")
    return out


def _carousel_pdf(slide_paths, sdir, name):
    """Compile a carousel's slide PNGs into a single PDF (for LinkedIn reuse).
    Returns the PDF path, or None on failure."""
    if not slide_paths:
        return None
    try:
        imgs = [Image.open(p).convert("RGB") for p in slide_paths]
        pdf_path = os.path.join(sdir, "carousel.pdf")
        imgs[0].save(pdf_path, "PDF", resolution=150.0,
                     save_all=True, append_images=imgs[1:])
        return pdf_path
    except Exception as exc:
        print(f"  PDF export failed for {name}: {exc}")
        return None


def main():
    date_str, order, by_section = yesterday_sections()
    if not order:
        print(f"No editions found for yesterday ({date_str}); nothing to build.")
        return
    date_label = (NOW - timedelta(days=1)).strftime("%A, %d %B %Y")
    base = f"social/instagram/{date_str}"
    li_base = f"social/linkedin/{date_str}"
    os.makedirs(li_base, exist_ok=True)
    os.makedirs(base, exist_ok=True)
    manifest = {"date": date_str, "label": date_label, "sections": []}

    for sid in order:
        sec = by_section[sid]
        # Prefer stories that have a real image (so slides aren't repetitive
        # generative art), while preserving recency order within each group.
        _all = sec["stories"]
        _with_img = [s for s in _all if (s.get("image") or "").startswith("http")]
        _without = [s for s in _all if not (s.get("image") or "").startswith("http")]
        stories = (_with_img + _without)[:5]
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

        # Sports carousel gets a FIFA World Cup 2026 match-summary slide (who beat
        # whom, with scores and dates) slotted in before the outro — replacing
        # the old standalone World Cup carousel.
        if sid == "sports":
            wc_slide, wc_head = build_worldcup_summary_slide(sdir, len(slides) + 1)
            if wc_slide:
                slides.append(wc_slide)
                print("  + FIFA World Cup 2026 match-summary slide added to Sports")

        outro = outro_slide(sid)
        p = os.path.join(sdir, f"slide-{len(slides)+1:02d}.png"); outro.save(p); slides.append(p)

        caption = build_caption(sec["name"], sid, stories, date_label)
        with open(os.path.join(sdir, "caption.txt"), "w", encoding="utf-8") as f:
            f.write(caption)

        pdf_path = _carousel_pdf(slides, sdir, sec["name"])

        # LinkedIn: for the professional-fit sections only (AI/Tech/World),
        # write a PDF + a LinkedIn-friendly caption into a SEPARATE folder.
        li_pdf = li_caption_file = None
        if sid in ("ai", "tech", "world"):
            li_dir = os.path.join(li_base, sid)
            os.makedirs(li_dir, exist_ok=True)
            li_pdf = _carousel_pdf(slides, li_dir, sec["name"] + " (LinkedIn)")
            li_cap = build_linkedin_caption(sec["name"], sid, stories, date_label)
            li_caption_file = os.path.join(li_dir, "caption.txt")
            with open(li_caption_file, "w", encoding="utf-8") as f:
                f.write(li_cap)

        manifest["sections"].append({
            "id": sid, "name": sec["name"], "slides": slides,
            "caption_file": os.path.join(sdir, "caption.txt"),
            "pdf": pdf_path,
            "linkedin_pdf": li_pdf,
            "linkedin_caption_file": li_caption_file,
            "slide_count": len(slides),
        })
        print(f"  {sec['name']}: {len(slides)} slides" + (" + PDF" if pdf_path else "")
              + (" + LinkedIn" if li_pdf else ""))

    # (The old standalone World Cup carousel has been replaced by a single
    # match-summary slide injected into the Sports carousel above.)

    # Instagram Stories: 8 vertical headline images from the day's top stories.
    try:
        stories_imgs = build_instagram_stories(base, by_section, order, date_label)
        if stories_imgs:
            manifest["stories"] = stories_imgs
    except Exception as exc:
        print(f"  Instagram Stories skipped: {exc}")

    with open(os.path.join(base, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"Instagram carousels built for {len(manifest['sections'])} sections -> {base}")


if __name__ == "__main__":
    main()
