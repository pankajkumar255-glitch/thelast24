#!/usr/bin/env python3
"""
The Last 24 — automatic media-house builder.

Runs every 3 hours via GitHub Actions:
  1. Pulls fresh headlines from Google News RSS across all categories
  2. Claude writes the edition: brief + a short grounded article per story
  3. Writes: data.js (homepage), articles/*.html (SEO article pages),
     editions/*.json (archive for the newsletter), sitemap.xml

Requires env: ANTHROPIC_API_KEY. Optional env: SITE_URL.
"""

import os, json, re, sys, html, hashlib
from datetime import datetime, timedelta, timezone
import feedparser, requests

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(IST)
CUTOFF = NOW - timedelta(hours=24)
SITE_URL = os.environ.get("SITE_URL", "https://thelast24.in").rstrip("/")
SITE_NAME = "The Last 24"

SECTION_QUERIES = {
    "National":           "India government OR policy OR supreme court",
    "World":              "world news OR geopolitics OR international",
    "Business & Markets": "India economy OR Sensex OR business OR trade",
    "Technology":         "India technology OR startup OR software",
    "Artificial Intelligence": "artificial intelligence OR AI model OR OpenAI OR Anthropic OR Gemini",
    "Sports":             "India cricket OR sports",
    "Entertainment":      "Bollywood OR Indian entertainment OR OTT",
}
PER_SECTION = 4

SECTION_HUES = {  # category accent colors (also used by generative art)
    "national": "#0E7B52", "world": "#1F5FA8", "business": "#B07A1F",
    "tech": "#6A3FB5", "ai": "#0E8E8E", "sports": "#CE3D1D", "entertainment": "#C2317E",
}

# ---------------------------------------------------------------- collect ---
def gnews_rss(query, window):
    q = requests.utils.quote(f"{query} {window}")
    return f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"

# The moat: only stories from established, verified publishers pass this filter.
TRUSTED_PUBLISHERS = [
    # Tier-1 Indian newspapers / business press
    "the hindu", "hindustan times", "hindustantimes", "indian express",
    "the indian express", "times of india", "economic times", "mint", "livemint",
    "business standard", "moneycontrol", "the print", "deccan herald",
    "telegraph india", "financial express", "frontline", "scroll", "the quint",
    # International wires/quality
    "reuters", "bbc", "cnbc", "bloomberg", "the guardian", "associated press",
    # General Indian (reputable digital)
    "ndtv", "india today", "news18", "firstpost", "outlook",
    # Sports (specialist, reputable)
    "espncricinfo", "cricbuzz", "sportstar", "olympics.com", "espn", "wisden",
    # Entertainment (reputable trade)
    "film companion", "variety", "pinkvilla", "filmfare", "ottplay", "ott play",
    # Tech / business / startup (reputable)
    "techcrunch", "the verge", "wired", "venturebeat", "analytics india",
    "inc42", "yourstory", "medianama", "gadgets 360", "entrackr",
    # Government / official
    "pib", "press information bureau",
]

# Explicitly EXCLUDED even if they appear (agency wires that republish without
# original reporting, and outlets widely flagged for bias / low editorial rigor).
EXCLUDED_PUBLISHERS = [
    "ani", "asian news international", "pti", "press trust of india",
    "republic", "zee news", "zeenews", "dna", "abp", "rediff", "indiatimes",
    "opindia", "tfipost", "swarajya", "koimoi", "bollywood life", "bollywood hungama",
]

def is_trusted(source_name):
    n = (source_name or "").lower()
    if any(x in n for x in EXCLUDED_PUBLISHERS):
        return False
    return any(t in n for t in TRUSTED_PUBLISHERS)

def resolve_url(link):
    """Try to resolve Google News redirect to the publisher's own URL so the
    'Read more' link lands on the original source. Falls back to the feed link."""
    try:
        r = requests.get(link, timeout=12, allow_redirects=True, stream=True,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; TheLast24/1.0)"})
        final = r.url
        r.close()
        if "news.google" not in final:
            return final
    except Exception:
        pass
    return link

def collect_headlines():
    backfill_days = int(os.environ.get("BACKFILL_DAYS", "0") or 0)
    window = f"when:{backfill_days}d" if backfill_days > 0 else "when:1d"
    cutoff = NOW - timedelta(days=backfill_days) if backfill_days > 0 else CUTOFF
    per_section = 8 if backfill_days > 0 else PER_SECTION
    lines, skipped = [], 0
    for section, query in SECTION_QUERIES.items():
        feed = feedparser.parse(gnews_rss(query, window))
        count = 0
        for e in feed.entries:
            if count >= per_section: break
            try:
                pub = datetime(*e.published_parsed[:6], tzinfo=timezone.utc).astimezone(IST)
            except Exception:
                pub = NOW
            if pub < cutoff: continue
            src = getattr(e, "source", None)
            src = src.title if src and hasattr(src, "title") else ""
            if not is_trusted(src):
                skipped += 1
                continue
            title = re.sub(r"\s+-\s+[^-]+$", "", e.title).strip()
            url = resolve_url(e.link)
            lines.append(f"{pub.strftime('%H:%M')} IST | [{section}] {title} | {src} | {url}")
            count += 1
    print(f"Filtered out {skipped} items from non-allowlisted sources.")
    if not lines:
        sys.exit("No headlines collected from trusted publishers.")
    return "\n".join(lines)

# ------------------------------------------------------------------ write ---
SECTION_IDS = {
    "National": "national", "World": "world", "Business & Markets": "business",
    "Technology": "tech", "Artificial Intelligence": "ai", "Sports": "sports", "Entertainment": "entertainment",
}

EDITORIAL_RULES = """You are the editor of "The Last 24", an automated brief covering everything that mattered in India in the last 24 hours, for a general Indian reader. Every headline you receive comes from a verified, established publisher. You will be given the raw headlines for ONE section and must produce that section's stories.

EDITORIAL RULES:
- Keep only the strongest stories up to the limit given; drop weak/duplicate ones. Treat two items as duplicates if they report the SAME underlying event even when the headlines are worded differently — keep only the single best one.
- WRITE DIRECTLY AND CONCRETELY: name the companies, brands, people, places and figures exactly as the headlines give them ("Reliance", "Zomato", "Virat Kohli", "Rs 2,000 crore"). NEVER use vague substitutes like "a major company" or "two platforms".
- CARRY THE CORE FACTS. If the story has specific concrete details that are its whole point, INCLUDE them rather than gesturing at them. Examples: a squad/team announcement -> name the key players actually picked; a budget/scheme -> the amount and who it's for; a match result -> the score and standout performers; an appointment -> who, to what post; a policy -> the specific change. A summary that says "the squad was announced" without naming anyone is a FAILURE.
- "what" = a substantial 3-4 sentence standfirst (roughly 55-80 words): the development precisely, the key concrete details, one line of immediate significance. Strictly from the headline plus universally known background.
- "lens" = 1 sharp, SPECIFIC sentence: why this exact story matters to an everyday Indian reader — money, daily life, or the bigger picture. It must be concrete to THIS story, not a generic platitude. If you cannot write a genuinely specific reason, write a plainer factual significance instead of a vague one. Never filler like "this is an important development".
- Structured summary (concise, fact-rich, strictly grounded): write a single flowing "article" of 3-4 short paragraphs (~180-240 words total) that reads as one continuous brief — NOT divided into labelled sections. Open with what happened (attributing the publisher by name, e.g. "The Hindu reports..."), weave in the concrete core facts (names, numbers, the actual squad/figures/decision), give the essential widely-known context, and close with why it matters to an everyday Indian reader. Strictly the headline plus universally-known facts; NEVER invent quotes, statistics, numbers, or names. Put this in the "article" field as plain text with paragraphs separated by blank lines.
- "key_facts" = an array of 2-5 short, concrete bullet strings capturing the HARD FACTS of the story that a reader would want at a glance — the actual specifics, not generalities. For a squad: the key players named. For a scheme/budget: the amount and beneficiaries. For a result: the score and top performers. For an appointment: who and to what role. For a deal: the parties and value. Each bullet under ~12 words, factual, drawn only from the headline + well-known facts. If the story genuinely has no hard specifics, use an empty array [].
- "image_subject" = the SINGLE most photographable real subject of the story for an encyclopedia image lookup — a real person's full name, a place, a landmark, or an institution exactly as it would title a Wikipedia article (e.g. "Narendra Modi", "Supreme Court of India", "Wankhede Stadium", "Reserve Bank of India", "Rohit Sharma"). Use "" (empty) if the story has no specific real named subject (pure concept/abstract stories).
- "image_query" = a 3-5 word search phrase for a stock-photo library capturing the VISUAL SUBJECT of the story as specifically as possible WITHOUT naming real people or brands. Think what a relevant photo would show. Examples: a Supreme Court ruling -> "indian courtroom justice gavel"; a cricket ODI -> "cricket batsman stadium india"; a startup-jobs story -> "indian office workers"; a bullet-train story -> "high speed train railway". Prefer Indian/contextual terms. Never real people or brand names.
- "image_query" = a 3-5 word search phrase for a stock-photo library that captures the VISUAL SUBJECT of the story as specifically as possible WITHOUT naming real people or brands. Think about what a relevant photo would actually show. Examples: a Supreme Court ruling -> "indian courtroom justice gavel"; a cricket ODI -> "cricket batsman stadium india"; a startup-jobs story -> "indian office workers technology"; a bullet train story -> "high speed train railway". Prefer Indian or contextual terms where the story is Indian. Never names of real people or brands.
- "image_safety" = classify the story for image handling. Use "real" if the story centres on a specific named real person OR a specific real event/incident (politics, court rulings, deaths, disasters, match results, named individuals). Use "concept" ONLY if it is an abstract/thematic story (markets, economy, technology trends, lifestyle) with no specific real person or event as its subject. When unsure, use "real".
- "hour" = integer 0-23 from the IST time. "time" = "HH:MM IST". "breaking" = true for at most 1 story.
- Keep source names and URLs exactly as given.

Respond with ONLY a JSON object, no markdown fences, no text before or after it:
{"stories":[{"hour":0,"time":"...","headline":"...","what":"...","lens":"...","article":"...","key_facts":["...","..."],"image_subject":"...","image_query":"...","source":"...","url":"...","breaking":false}]}"""

API_URL = "https://api.anthropic.com/v1/messages"
# Current Sonnet. If this ever 400s with a model error, update this ONE line.
MODEL = "claude-sonnet-4-6"

def call_claude(system, user, max_tokens):
    """One Claude call with a single retry. On HTTP errors, surface the API's
    actual JSON error body (which says exactly what's wrong) instead of a bare
    status code."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("ANTHROPIC_API_KEY not set.")
    last_err = None
    for attempt in (1, 2):
        try:
            r = requests.post(API_URL,
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": MODEL, "max_tokens": max_tokens,
                      "system": system,
                      "messages": [{"role": "user", "content": user}]},
                timeout=240)
            if r.status_code != 200:
                # The body explains the real cause (bad model, token limit, etc.)
                detail = r.text[:500]
                print(f"Attempt {attempt}: HTTP {r.status_code} — {detail}")
                last_err = f"HTTP {r.status_code}: {detail}"
                if attempt == 1:
                    print("  retrying once...")
                continue
            data = r.json()
            if data.get("stop_reason") == "max_tokens":
                print("WARNING: response hit the max_tokens limit; output may be truncated.")
            text = "".join(b.get("text", "") for b in data.get("content", [])
                           if b.get("type") == "text").strip()
            if text:
                return text
            print(f"Attempt {attempt}: Claude returned empty text" +
                  (", retrying once..." if attempt == 1 else "."))
            last_err = "empty response"
        except Exception as exc:
            last_err = exc
            print(f"Attempt {attempt}: request error: {exc}" +
                  (", retrying once..." if attempt == 1 else "."))
    raise RuntimeError(f"No usable text from Claude after 2 attempts: {last_err}")

def extract_json(text, context=""):
    """Parse JSON even if Claude wraps it in fences or adds text around it.
    On failure, print the raw response to the logs, then raise."""
    clean = re.sub(r"```json|```", "", text).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    start, end = clean.find("{"), clean.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(clean[start:end + 1])
        except json.JSONDecodeError:
            pass
    print(f"--- RAW CLAUDE RESPONSE ({context}) START ---")
    print(text[:3000])
    if len(text) > 3000:
        print(f"... [{len(text) - 3000} more characters truncated]")
    print(f"--- RAW CLAUDE RESPONSE ({context}) END ---")
    raise ValueError(f"Could not parse JSON from Claude response ({context}).")

REQUIRED_FIELDS = ("headline", "what", "lens", "source", "url", "time")

def clean_stories(items, section_name):
    """Drop malformed stories instead of failing the run."""
    out = []
    for st in items if isinstance(items, list) else []:
        if not isinstance(st, dict) or not all(st.get(f) for f in REQUIRED_FIELDS):
            print(f"  Skipping malformed story in {section_name}: {str(st)[:120]}")
            continue
        try:
            st["hour"] = max(0, min(23, int(st.get("hour", 12))))
        except (TypeError, ValueError):
            st["hour"] = 12
        st["breaking"] = bool(st.get("breaking", False))
        out.append(st)
    return out

def write_edition(raw):
    """One small Claude call per section — short JSON outputs parse reliably."""
    backfill = int(os.environ.get("BACKFILL_DAYS", "0") or 0) > 0
    per_cap = 6 if backfill else 5
    groups = {}
    for line in raw.splitlines():
        m = re.search(r"\[([^\]]+)\]", line)
        if m:
            groups.setdefault(m.group(1), []).append(line)

    sections = []
    for name, sid in SECTION_IDS.items():
        lines = groups.get(name)
        if not lines:
            print(f"Section {name}: no headlines collected this run.")
            continue
        print(f"Writing section: {name} ({len(lines)} headlines, keep up to {per_cap})")
        stories = []
        # Attempt 1: full request. Attempt 2 (on failure): same story count, but a
        # simpler/cleaner instruction and a fresh call (handles transient failures
        # and the occasional unparseable response without slashing the section).
        attempts = [
            (per_cap, f"Section: {name}\nKeep at most {per_cap} of the strongest stories.\n\n"
                      f"Raw headlines from the last 24 hours:\n" + "\n".join(lines)),
            (per_cap, f"Section: {name}\nSelect up to {per_cap} of the strongest, clearest stories. "
                      f"Be factual and concise. Return valid JSON only.\n\n"
                      f"Headlines:\n" + "\n".join(lines)),
        ]
        for cap, user in attempts:
            try:
                data = extract_json(call_claude(EDITORIAL_RULES, user, 8000), name)
                stories = clean_stories(data.get("stories", []), name)[:cap]
                if stories:
                    break
                print(f"  -> attempt returned no valid stories; trying a simpler request...")
            except (RuntimeError, ValueError) as exc:
                print(f"  -> attempt failed ({exc}); trying a simpler request...")
        if stories:
            # Drop near-duplicates within the section (same event from 2 sources).
            deduped, fps = [], []
            for st in stories:
                fp = _story_fingerprint(st)
                if _is_dupe(fp, fps):
                    print(f"  -> dropped near-duplicate: {st.get('headline','')[:50]}")
                    continue
                deduped.append(st); fps.append(fp)
            stories = deduped
            sections.append({"id": sid, "name": name, "stories": stories})
            print(f"  -> {len(stories)} stories kept for {name}.")
        else:
            print(f"  -> {name} produced nothing after retry; section skipped this run.")

    if not sections:
        sys.exit("Every section failed — no edition produced this run.")

    # Topline: tiny call, with a clean natural-language fallback (never the clumsy count line).
    heads = [st["headline"] for sec in sections for st in sec["stories"]][:10]
    topline = ""
    try:
        t = extract_json(call_claude(
            'Respond with ONLY this JSON, nothing else: {"topline":"..."} — one sharp, natural sentence '
            "capturing the day's arc across these headlines, naming the biggest entities directly. "
            "Do not mention how many stories there are.",
            "\n".join(heads), 300), "topline")
        topline = str(t.get("topline", "")).strip()
    except (RuntimeError, ValueError) as exc:
        print(f"Topline call failed, using fallback: {exc}")
    if not topline and heads:
        lead = heads[0].rstrip(".")
        topline = f"Today's headlines, led by: {lead}."
    elif not topline:
        topline = "The day's most important stories from across India."

    edition = {
        "date": NOW.strftime("%A, %d %B %Y"),
        "edition": NOW.strftime("%Y-%m-%d %H:%M"),
        "topline": topline,
        "lensLabel": "Why it matters",
        "sections": sections,
    }
    topup_and_sort(edition, target=per_cap)
    return edition


def _story_dt(st):
    """Best-effort IST datetime for a story, for accurate newest-first sorting.
    Uses the edition date the story was filed under (set during top-up) plus its
    hour; falls back to hour-only within today."""
    base = st.get("_edition_date")
    try:
        if base:
            d = datetime.strptime(base, "%Y-%m-%d").replace(tzinfo=IST)
        else:
            d = NOW
        return d.replace(hour=int(st.get("hour", 0)), minute=0, second=0, microsecond=0)
    except Exception:
        return NOW


def _story_fingerprint(st):
    """A loose fingerprint that matches the SAME story even when the headline is
    reworded. Uses the set of significant words (>3 chars, minus common filler)
    from the headline. Two headlines about the same event share most of these."""
    stop = {"the", "and", "for", "with", "from", "that", "this", "after", "over",
            "into", "amid", "says", "said", "will", "your", "you", "are", "was",
            "has", "have", "its", "his", "her", "their", "they", "them", "than",
            "more", "most", "new", "now", "set", "get", "but", "not", "all"}
    words = re.findall(r"[a-z0-9]+", (st.get("headline") or "").lower())
    sig = frozenset(w for w in words if len(w) > 3 and w not in stop)
    return sig

def _is_dupe(fp, seen_fps):
    """True only if fp shares a strong majority of significant words with a seen
    fingerprint AND both have enough words to be confident (same event, reworded).
    Conservative by design: better to allow a rare dupe than drop a real story."""
    if not fp or len(fp) < 4:
        return False  # too few words to judge confidently
    for s in seen_fps:
        if not s or len(s) < 4:
            continue
        overlap = len(fp & s)
        union = len(fp | s)
        # Jaccard similarity: shared / total distinct words. 0.7+ = same story.
        if union and overlap / union >= 0.65:
            return True
    return False

def topup_and_sort(edition, target=5, lookback_hours=48):
    """Ensure each section shows up to `target` stories by topping up thin
    sections with the most recent UNIQUE stories from previous editions (within
    `lookback_hours`), then sort every section newest-first by IST timestamp.
    Fresh stories from this run always rank above older top-ups."""
    import glob
    # Tag this run's stories with today's date so timestamps sort correctly.
    today = NOW.strftime("%Y-%m-%d")
    for sec in edition["sections"]:
        for st in sec["stories"]:
            st.setdefault("_edition_date", today)

    # Gather recent past stories per section id, newest editions first.
    cutoff = NOW - timedelta(hours=lookback_hours)
    past = {}
    for path in sorted(glob.glob("editions/*.json"), reverse=True):
        stamp = os.path.basename(path)[:13]  # YYYY-MM-DD-HH
        try:
            when = datetime.strptime(stamp, "%Y-%m-%d-%H").replace(tzinfo=IST)
        except ValueError:
            continue
        if when < cutoff:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                ed = json.load(f)
        except Exception:
            continue
        edate = when.strftime("%Y-%m-%d")
        for sec in ed.get("sections", []):
            for st in sec.get("stories", []):
                st["_edition_date"] = st.get("_edition_date", edate)
                past.setdefault(sec["id"], []).append(st)

    have = {sec["id"]: sec for sec in edition["sections"]}
    for sid, sec in have.items():
        seen = {(s.get("slug") or s.get("headline")) for s in sec["stories"]}
        seen_fps = [_story_fingerprint(s) for s in sec["stories"]]
        if len(sec["stories"]) < target:
            for st in past.get(sid, []):
                key = st.get("slug") or st.get("headline")
                if key in seen:
                    continue
                fp = _story_fingerprint(st)
                if _is_dupe(fp, seen_fps):
                    continue
                sec["stories"].append(st)
                seen.add(key)
                seen_fps.append(fp)
                if len(sec["stories"]) >= target:
                    break
        # Newest-first by IST timestamp, then trim to target.
        sec["stories"].sort(key=_story_dt, reverse=True)
        sec["stories"] = sec["stories"][:target]
        # _edition_date is internal; drop it from what ships if older than today
        for st in sec["stories"]:
            if st.get("_edition_date") == today:
                st.pop("_edition_date", None)

# ----------------------------------------------------- three-tier imagery ---
# Tier 1: real licensed photo (Pexels) — used for real-person/real-event stories
#         and as the first choice everywhere.
# Tier 2: AI illustration (Gemini / "Nano Banana") — ONLY for abstract concept
#         stories, never for a named real person or specific real event, and
#         always labelled "AI illustration" on the page.
# Tier 3: deterministic editorial art — always-available fallback.
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "")
UNSPLASH_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash-image"

def _score(query, text):
    """Relevance score: how many query words appear in the candidate's own
    title/tags/description. Higher = better match. Lets us pick across sources."""
    q = {w for w in re.findall(r"[a-z]+", (query or "").lower()) if len(w) > 2}
    if not q:
        return 0
    t = (text or "").lower()
    return sum(1 for w in q if w in t)

def _pexels(query):
    if not PEXELS_KEY:
        return []
    try:
        r = requests.get("https://api.pexels.com/v1/search",
                         headers={"Authorization": PEXELS_KEY},
                         params={"query": query, "per_page": 5, "orientation": "landscape"},
                         timeout=20)
        r.raise_for_status()
        out = []
        for p in r.json().get("photos", []):
            # Pexels exposes alt text describing the photo — use it for scoring.
            # Use large2x for a reliable, well-sized hotlink-friendly URL.
            src = p.get("src", {})
            img_url = src.get("large2x") or src.get("large") or src.get("original")
            if not img_url:
                continue
            out.append({"image": img_url, "image_kind": "photo",
                        "image_credit": p.get("photographer", "Pexels"),
                        "image_credit_url": p.get("photographer_url", "https://www.pexels.com"),
                        "_text": p.get("alt", ""), "_src": "Pexels"})
        return out
    except Exception as exc:
        print(f"  pexels miss for '{query}': {exc}")
        return []

def _unsplash(query):
    if not UNSPLASH_KEY:
        return []
    try:
        r = requests.get("https://api.unsplash.com/search/photos",
                         headers={"Authorization": f"Client-ID {UNSPLASH_KEY}"},
                         params={"query": query, "per_page": 5, "orientation": "landscape"},
                         timeout=20)
        r.raise_for_status()
        out = []
        for p in r.json().get("results", []):
            desc = p.get("description") or p.get("alt_description") or ""
            tags = " ".join(t.get("title", "") for t in (p.get("tags") or []))
            out.append({"image": p["urls"]["regular"], "image_kind": "photo",
                        "image_credit": (p.get("user") or {}).get("name", "Unsplash"),
                        "image_credit_url": ((p.get("user") or {}).get("links") or {}).get("html", "https://unsplash.com"),
                        "_text": desc + " " + tags, "_src": "Unsplash"})
        return out
    except Exception as exc:
        print(f"  unsplash miss for '{query}': {exc}")
        return []

def _pixabay(query):
    if not PIXABAY_KEY:
        return []
    try:
        r = requests.get("https://pixabay.com/api/",
                         params={"key": PIXABAY_KEY, "q": query, "per_page": 5,
                                 "image_type": "photo", "orientation": "horizontal",
                                 "safesearch": "true"},
                         timeout=20)
        r.raise_for_status()
        out = []
        for p in r.json().get("hits", []):
            out.append({"image": p.get("largeImageURL") or p.get("webformatURL"),
                        "image_kind": "photo",
                        "image_credit": p.get("user", "Pixabay"),
                        "image_credit_url": f"https://pixabay.com/users/{p.get('user','')}-{p.get('user_id','')}/",
                        "_text": p.get("tags", ""), "_src": "Pixabay"})
        return out
    except Exception as exc:
        print(f"  pixabay miss for '{query}': {exc}")
        return []

def fetch_photo(query, used=None):
    """Query Pexels, Unsplash and Pixabay, then return the most relevant photo
    across all three that hasn't already been used this run. None if all empty."""
    if not query:
        return None
    used = used or set()
    candidates = _pexels(query) + _unsplash(query) + _pixabay(query)
    # Drop candidates without a usable https URL, and any already used this run.
    candidates = [c for c in candidates
                  if isinstance(c.get("image"), str) and c["image"].startswith("http")
                  and c["image"] not in used]
    if not candidates:
        return None
    # Best relevance wins; ties keep source order (Pexels, Unsplash, Pixabay).
    best = max(candidates, key=lambda c: _score(query, c.get("_text", "")))
    print(f"  photo: '{query}' -> {best['_src']} (matched {_score(query, best.get('_text',''))} terms, {len(candidates)} unused candidates)")
    return {k: v for k, v in best.items() if not k.startswith("_")}

def generate_ai_image(prompt, slug):
    """AI illustration via Gemini ('Nano Banana'). Concept stories ONLY — callers
    must never pass a real named person or specific real event. Saves a PNG into
    /articles/img and returns its site-relative path. None on any failure."""
    if not GEMINI_KEY or not prompt:
        return None
    safe_prompt = ("A clean, abstract editorial illustration for a news brief, "
                   "conceptual and non-photorealistic, no real people, no faces, "
                   "no text, no logos, no flags. Subject: " + prompt)
    try:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}")
        r = requests.post(url, timeout=90,
            headers={"content-type": "application/json"},
            json={"contents": [{"parts": [{"text": safe_prompt}]}]})
        r.raise_for_status()
        parts = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        for part in parts:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                import base64
                os.makedirs("articles/img", exist_ok=True)
                path = f"articles/img/{slug}.png"
                with open(path, "wb") as f:
                    f.write(base64.b64decode(inline["data"]))
                return {"image": "img/" + slug + ".png", "image_home": "articles/img/" + slug + ".png",
                        "image_kind": "ai", "image_credit": "AI illustration",
                        "image_credit_url": ""}
        print("  gemini returned no image data")
        return None
    except Exception as exc:
        print(f"  gemini miss for '{prompt[:40]}': {exc}")
        return None

def fetch_wikimedia(subject):
    """Real, freely-licensed photo of a named subject from Wikipedia/Wikimedia.
    This is the relevance tier: a genuine photo of the actual person/place/
    institution, legal to use WITH attribution (which we display). None on miss.

    Uses the Wikipedia REST summary endpoint to get the lead image of the most
    relevant article, plus the file's licensed author for credit."""
    if not subject or len(subject) < 3:
        return None
    try:
        # Resolve the best-matching article title first.
        s = requests.get("https://en.wikipedia.org/w/api.php",
                         params={"action": "query", "list": "search",
                                 "srsearch": subject, "srlimit": 1,
                                 "format": "json"},
                         headers={"User-Agent": "TheLast24/1.0 (news brief; contact support@thelast24.in)"},
                         timeout=20)
        s.raise_for_status()
        hits = s.json().get("query", {}).get("search", [])
        if not hits:
            return None
        title = hits[0]["title"]
        # Relevance guard: the matched article title should share a significant
        # word with the subject. This prevents a vague subject ("cricket match")
        # from grabbing an unrelated article's image (e.g. a football photo).
        subj_words = {w for w in re.findall(r"[a-z]+", subject.lower()) if len(w) > 3}
        title_words = {w for w in re.findall(r"[a-z]+", title.lower()) if len(w) > 3}
        if subj_words and not (subj_words & title_words):
            print(f"  wikimedia: '{subject}' -> '{title}' rejected (no subject overlap)")
            return None
        # Get the page's lead image (thumbnail) + the original file name.
        p = requests.get("https://en.wikipedia.org/w/api.php",
                         params={"action": "query", "titles": title,
                                 "prop": "pageimages", "piprop": "original|name",
                                 "format": "json"},
                         headers={"User-Agent": "TheLast24/1.0 (news brief; contact support@thelast24.in)"},
                         timeout=20)
        p.raise_for_status()
        pages = p.json().get("query", {}).get("pages", {})
        page = next(iter(pages.values()), {})
        original = page.get("original", {})
        img_url = original.get("source")
        if not img_url or not img_url.startswith("http"):
            return None
        # Skip SVGs/logos and tiny images — we want real photographs.
        if img_url.lower().endswith((".svg", ".png")):
            return None
        # Fetch the file's attribution (artist) for a proper credit line.
        credit = "Wikimedia Commons"
        fname = page.get("pageimage")
        if fname:
            try:
                m = requests.get("https://en.wikipedia.org/w/api.php",
                                 params={"action": "query", "titles": "File:" + fname,
                                         "prop": "imageinfo", "iiprop": "extmetadata",
                                         "format": "json"},
                                 headers={"User-Agent": "TheLast24/1.0 (support@thelast24.in)"},
                                 timeout=20)
                meta = next(iter(m.json().get("query", {}).get("pages", {}).values()), {})
                ext = (meta.get("imageinfo", [{}])[0].get("extmetadata", {}))
                artist = ext.get("Artist", {}).get("value", "")
                # Strip any HTML tags from the artist field.
                artist = re.sub(r"<[^>]+>", "", artist).strip()
                if artist:
                    credit = artist[:80]
            except Exception:
                pass
        print(f"  wikimedia: '{subject}' -> {title}")
        return {"image": img_url, "image_kind": "photo",
                "image_credit": credit + " / Wikimedia Commons",
                "image_credit_url": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")}
    except Exception as exc:
        print(f"  wikimedia miss for '{subject}': {exc}")
        return None

def resolve_image(st, used=None):
    """Image policy: real subject first, then stock fill for coverage.
    1) Wikimedia Commons photo of the named real subject (most relevant).
    2) Stock photo (Pexels + Unsplash + Pixabay), best unused relevance match —
       provides coverage so cards aren't blank when Wikimedia has no match.
    3) Editorial art (rendered at display time) — silent last resort only.
    No AI generation of real people/events."""
    used = used or set()
    subject = st.get("image_subject")
    query = st.get("image_query") or st.get("headline", "")
    # Tier 1: real photo of the actual named subject.
    wiki = fetch_wikimedia(subject)
    if wiki and wiki.get("image") and wiki["image"] not in used:
        return wiki
    # Tier 2: stock photo for coverage (best unused match across libraries).
    photo = fetch_photo(query, used)
    if photo and photo.get("image"):
        return photo
    # Tier 3: no match -> None; render layer draws editorial art.
    return None

# -------------------------------------------------------- generative art ---
def art_svg(seed_text, section_id, w=1200, h=560):
    """Deterministic editorial art per story — unique, legal, zero-cost."""
    hue = SECTION_HUES.get(section_id, "#0E7B52")
    hsh = hashlib.sha256(seed_text.encode()).digest()
    v = lambda i, lo, hi: lo + (hsh[i % 32] / 255) * (hi - lo)
    shapes = []
    for i in range(6):
        cx, cy = v(i*3, 0.05, 0.95)*w, v(i*3+1, 0.1, 0.9)*h
        r = v(i*3+2, 0.04, 0.22)*w
        op = round(v(i*5+1, 0.06, 0.20), 2)
        if hsh[i*2] % 3 == 0:
            shapes.append(f'<rect x="{cx-r:.0f}" y="{cy-r/2:.0f}" width="{r*2:.0f}" height="{r:.0f}" rx="{r/5:.0f}" fill="{hue}" opacity="{op}" transform="rotate({v(i,-20,20):.0f} {cx:.0f} {cy:.0f})"/>')
        else:
            shapes.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r:.0f}" fill="{hue}" opacity="{op}"/>')
    bars = "".join(f'<rect x="{60+i*((w-120)/24):.0f}" y="{h-44}" width="{(w-120)/24-4:.0f}" height="10" rx="3" fill="{hue}" opacity="{0.9 if hsh[i] % 4 == 0 else 0.15}"/>' for i in range(24))
    return (f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Editorial art">'
            f'<rect width="{w}" height="{h}" fill="#F6F7F4"/>{"".join(shapes)}{bars}'
            f'<circle cx="{v(20,0.15,0.85)*w:.0f}" cy="{v(21,0.2,0.7)*h:.0f}" r="{v(22,0.05,0.10)*w:.0f}" fill="none" stroke="{hue}" stroke-width="3" opacity="0.85"/></svg>')

def masthead_css():
    """Shared masthead CSS — identical across article, archive and CA pages,
    matching the homepage band/brand/nav treatment (minus the ticker).
    Returns single-brace CSS (inserted as a variable, not inside an f-string)."""
    return """
.band{background:var(--dark);color:#F2F4EE;padding:20px 0}
.band .wrap{max-width:var(--mw,920px);margin:0 auto;padding:0 20px}
.brand-row{display:flex;justify-content:space-between;align-items:center;gap:14px}
.brand-row .brand{font-family:var(--display);font-weight:800;font-size:clamp(28px,4vw,34px);letter-spacing:-.02em;text-decoration:none;line-height:1;color:#F2F4EE}
.brand-row .brand span{color:var(--green-bright)}
.brand-side{display:flex;align-items:center;gap:18px;flex-wrap:wrap;justify-content:flex-end}
.brand-nav{display:flex;align-items:center;gap:10px}
.m-ca{font-family:var(--mono);font-size:12px;font-weight:600;color:#0D120D;background:var(--green-bright);text-decoration:none;padding:7px 14px;border-radius:999px;transition:all .18s;white-space:nowrap}
.m-ca:hover{background:#fff;color:#0D120D}
.m-link{font-family:var(--mono);font-size:12px;color:#F2F4EE;text-decoration:none;border:1px solid rgba(255,255,255,.25);padding:7px 14px;border-radius:999px;transition:all .18s;white-space:nowrap}
.m-link:hover{border-color:var(--green-bright);color:var(--green-bright)}
.brand-meta{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:#929C8E;text-align:right;line-height:1.7}
.brand-meta .v{color:var(--green-bright);font-weight:600}
@media (max-width:600px){
  .brand-meta{display:none}
  .brand-row{flex-wrap:wrap;gap:10px}
  .brand-side{width:100%;justify-content:flex-start}
  .m-ca,.m-link{font-size:11px;padding:6px 12px}
}
"""

def masthead_html(links, date_label=""):
    """Shared masthead markup. `links` is a list of (label, href, primary) —
    primary=True renders the filled green button (used for Current Affairs)."""
    btns = ""
    for label, href, primary in links:
        cls = "m-ca" if primary else "m-link"
        btns += f'<a class="{cls}" href="{href}">{label}</a>'
    meta = (f'<div class="brand-meta"><span class="v">✓ Verified publishers only</span>'
            f'<br>{html.escape(date_label)}</div>') if date_label else \
           '<div class="brand-meta"><span class="v">✓ Verified publishers only</span></div>'
    return (f'<div class="band"><div class="wrap"><div class="brand-row">'
            f'<a class="brand" href="/">The Last <span>24</span></a>'
            f'<div class="brand-side"><div class="brand-nav">{btns}</div>{meta}'
            f'</div></div></div></div>')

def slugify(headline):
    s = re.sub(r"[^a-z0-9]+", "-", headline.lower()).strip("-")
    return s[:70].rstrip("-")

# ----------------------------------------------------------- article page ---
def summary_blocks(story):
    """Render the flowing 'article' as plain paragraphs (no labelled sections).
    Falls back to the older structured fields if an old edition is present."""
    if story.get("article"):
        paras = [p.strip() for p in story["article"].split("\n\n") if p.strip()]
        return [("", p) for p in paras]
    # Backwards-compatibility with older editions that used labelled fields.
    blocks = [story.get("what_happened"), story.get("context"),
              story.get("why_it_matters")]
    return [("", t) for t in blocks if t]

def article_page(story, section, edition):
    e = html.escape
    hue = SECTION_HUES.get(section["id"], "#0E7B52")
    desc = e(story["what"][:155])
    jsonld = json.dumps({
        "@context": "https://schema.org", "@type": "NewsArticle",
        "headline": story["headline"], "description": story["what"],
        "datePublished": NOW.isoformat(), "dateModified": NOW.isoformat(),
        "articleSection": section["name"],
        "author": {"@type": "Organization", "name": SITE_NAME},
        "publisher": {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL},
        "mainEntityOfPage": f"{SITE_URL}/articles/{story['slug']}.html",
        "isBasedOn": story.get("url", ""),
        **({"image": [story["image"]]} if story.get("image") else {}),
    }, ensure_ascii=False)
    if story.get("image"):
        if story.get("image_kind") == "ai":
            cap = '<figcaption>⚠ AI illustration — generated for visual context, not a real photograph. The reporting belongs to the cited source.</figcaption>'
        else:
            cap = (f'<figcaption>Photo: <a href="{e(story.get("image_credit_url","#"))}" rel="noopener" target="_blank">'
                   f'{e(story.get("image_credit","Pexels"))}</a> via Pexels (free license)</figcaption>')
        hero = (f'<figure class="hero"><img src="{e(story["image"])}" alt="{e(story["headline"])}" loading="eager">'
                f'{cap}</figure>')
    else:
        hero = f'<div class="hero">{art_svg(story["headline"], section["id"])}</div>'
    blocks = "".join(
        (f'<div class="block">{("<h2>"+e(label)+"</h2>") if label else ""}<p>{e(text)}</p></div>')
        for label, text in summary_blocks(story))
    # Key facts box — the hard specifics (squad, figures, score) at a glance.
    kf = [f for f in (story.get("key_facts") or []) if str(f).strip()]
    facts_box = ""
    if kf:
        items = "".join(f"<li>{e(str(f))}</li>" for f in kf[:5])
        facts_box = f'<div class="facts"><h2>Key facts</h2><ul>{items}</ul></div>'
    src_name = e(story.get("source", "the original source"))
    src_url = e(story.get("url", "#"))
    _mhead = masthead_html([("Current Affairs", "/current-affairs.html", True),
                            ("Archive", "/archive.html", False)],
                           date_label=edition.get("date", ""))
    _mcss = masthead_css()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><!-- Google tag (gtag.js) with Consent Mode v2 --><script async src="https://www.googletagmanager.com/gtag/js?id=G-B1R3X3GKJ3"></script><script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag('consent','default',{{'ad_storage':'denied','ad_user_data':'denied','ad_personalization':'denied','analytics_storage':'denied','wait_for_update':500}});gtag('js',new Date());gtag('config','G-B1R3X3GKJ3');try{{if(localStorage.getItem('cookie-consent')==='granted'){{gtag('consent','update',{{'ad_storage':'granted','ad_user_data':'granted','ad_personalization':'granted','analytics_storage':'granted'}});}}}}catch(e){{}}</script><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{e(story['headline'])} — {SITE_NAME}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{SITE_URL}/articles/{story['slug']}.html">
<meta property="og:type" content="article"><meta property="og:title" content="{e(story['headline'])}">
<meta property="og:description" content="{desc}"><meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:url" content="{SITE_URL}/articles/{story['slug']}.html">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="../favicon.ico" sizes="any"><link rel="apple-touch-icon" href="../apple-touch-icon.png">
<script type="application/ld+json">{jsonld}</script>
<style>
:root{{--paper:#F7F7F5;--ink:#111511;--ink-soft:#454B43;--meta:#73786F;--hairline:#E6E8E2;--hue:{hue};
--display:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
--body:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
--mono:ui-monospace,"SF Mono",SFMono-Regular,"Roboto Mono",Menlo,Consolas,monospace;--dark:#0D120D;--green-bright:#3BCB8D;--mw:660px}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--paper);color:var(--ink);font-family:var(--body);line-height:1.6;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:660px;margin:0 auto;padding:0 20px}}
/*MASTHEAD_CSS*/
.band{{margin-bottom:30px}}
.top{{font-family:var(--mono);font-size:12px;padding:16px 20px;display:flex;justify-content:space-between;align-items:center;max-width:660px;margin:0 auto}}
.top a{{color:#F2F4EE;text-decoration:none;font-weight:800;font-family:var(--display);font-size:26px;letter-spacing:-.02em}}.top a span{{color:#3BCB8D}}
.topnav{{display:flex;gap:16px;align-items:center}}
.topnav a{{font-family:var(--mono)!important;font-size:12px!important;font-weight:600!important;color:#C9D2C5!important;letter-spacing:.04em;transition:color .15s}}
.topnav a:hover{{color:#3BCB8D!important}}
.cat{{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--hue);font-weight:700;background:#fff;padding:5px 12px;border-radius:999px}}
.kick{{font-family:var(--mono);font-size:11px;color:var(--meta);letter-spacing:.08em;text-transform:uppercase;margin-bottom:10px}}
.kick b{{color:#0E7B52}}
h1{{font-family:var(--display);font-weight:800;font-size:clamp(28px,6vw,40px);line-height:1.1;letter-spacing:-.02em;margin:0 0 14px}}
.meta{{font-family:var(--mono);font-size:12px;color:var(--meta);margin-bottom:20px}}
.hero{{border-radius:16px;overflow:hidden;box-shadow:0 8px 24px rgba(14,19,14,.10);margin-bottom:26px}}
.hero svg{{display:block;width:100%;height:auto}}
.hero img{{display:block;width:100%;aspect-ratio:21/10;object-fit:cover}}
.hero figcaption{{font-family:var(--mono);font-size:10.5px;color:var(--meta);padding:8px 14px;background:#fff;border-top:1px solid var(--hairline)}}
.hero figcaption a{{color:var(--meta)}}
@media (max-width:560px){{
  .wrap{{padding:0 16px}}
  .hero img{{aspect-ratio:3/2}}
  .hero{{margin-bottom:20px;border-radius:14px}}
  .block p{{font-size:15.5px;line-height:1.7}}
}}
.block{{padding:18px 0;border-bottom:1px solid var(--hairline)}}
.facts{{background:#fff;border:1px solid var(--hairline);border-left:4px solid var(--hue);border-radius:12px;padding:16px 18px;margin-bottom:8px}}
.facts h2{{font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--hue);margin-bottom:10px}}
.facts ul{{margin:0;padding:0;list-style:none}}
.facts li{{font-size:15px;padding:5px 0 5px 20px;position:relative;line-height:1.5}}
.facts li::before{{content:"▸";position:absolute;left:0;color:var(--hue)}}
.block h2{{font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--hue);margin-bottom:7px}}
.block p{{font-size:16.5px;color:var(--ink-soft)}}
.cta{{display:block;text-align:center;margin:26px 0 8px;background:var(--hue);color:#fff;text-decoration:none;font-family:var(--display);font-weight:700;font-size:15.5px;padding:15px 20px;border-radius:13px;transition:transform .15s,box-shadow .15s}}
.cta:hover{{transform:translateY(-2px);box-shadow:0 10px 26px rgba(14,19,14,.18)}}
.cite{{font-family:var(--mono);font-size:11px;color:var(--meta);text-align:center;line-height:1.7;margin-bottom:8px}}
.cite a{{color:var(--hue)}}
.ad-slot{{margin:28px 0;border:1px dashed #DADDD2;border-radius:12px;min-height:90px;display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:11px;color:var(--meta)}}
footer{{background:#0E130E;color:#939D8F;margin-top:40px;padding:26px 0 64px}}
footer p{{font-size:12px;line-height:1.8;max-width:560px}}
footer a{{color:#3BCB8D;text-decoration:none}}
</style></head>
<body>
{_mhead}
<div class="wrap">
<p class="kick"><b>✓ Verified source:</b> {src_name} · {e(story['time'])} · {e(edition['date'])}</p>
<h1>{e(story['headline'])}</h1>
{hero}
<article>
{facts_box}
{blocks}
</article>
<a class="cta" href="{src_url}" rel="noopener" target="_blank">Read the full story at {src_name} →</a>
<p class="cite">This is a summary brief. Original reporting and all facts: <a href="{src_url}" rel="noopener" target="_blank">{src_name}</a>.</p>
<div class="ad-slot"><!-- AD SLOT: article-mid. Paste your AdSense/ad-network snippet here. -->Ad space</div>
</div>
<footer><div class="wrap"><p><a href="/">Today's brief</a> · <a href="../about.html">About</a> · <a href="../contact.html">Contact</a> · <a href="../privacy.html">Privacy</a></p><p>{SITE_NAME} curates exclusively from verified publishers. Founded by Pankaj Kumar.</p></div></footer>
</body></html>""".replace("/*MASTHEAD_CSS*/", _mcss)

# ---------------------------------------------------------------- outputs ---
def write_outputs(edition):
    os.makedirs("articles", exist_ok=True)
    os.makedirs("editions", exist_ok=True)
    used_images = set()
    for sec in edition["sections"]:
        for st in sec["stories"]:
            st["slug"] = NOW.strftime("%Y%m%d") + "-" + slugify(st["headline"])
            img = resolve_image(st, used_images)
            if img:
                st.update(img)
                if img.get("image"):
                    used_images.add(img["image"])
            st.pop("image_query", None); st.pop("image_safety", None); st.pop("image_subject", None)
            with open(f"articles/{st['slug']}.html", "w", encoding="utf-8") as f:
                f.write(article_page(st, sec, edition))
    # homepage data (article text not needed client-side)
    slim = json.loads(json.dumps(edition, ensure_ascii=False))
    for sec in slim["sections"]:
        for st in sec["stories"]:
            # AI images are saved under articles/img and stored relative to the
            # article page; the homepage sits at root, so use the root-relative path.
            if st.get("image_home"):
                st["image"] = st["image_home"]
            for k in ("article", "what_happened", "context", "why_it_matters", "whats_next", "key_facts", "image_home", "_edition_date"):
                st.pop(k, None)
    with open("data.js", "w", encoding="utf-8") as f:
        f.write("// auto-generated " + NOW.strftime("%Y-%m-%d %H:%M IST") +
                "\nwindow.BRIEF = " + json.dumps(slim, indent=2, ensure_ascii=False) + ";\n")
    with open(f"editions/{NOW.strftime('%Y-%m-%d-%H')}.json", "w", encoding="utf-8") as f:
        json.dump(edition, f, ensure_ascii=False, indent=2)
    # sitemap
    arts = sorted(a for a in os.listdir("articles") if a.endswith(".html"))
    urls = [f"<url><loc>{SITE_URL}/</loc><changefreq>hourly</changefreq><priority>1.0</priority></url>",
            f"<url><loc>{SITE_URL}/archive.html</loc><changefreq>hourly</changefreq><priority>0.8</priority></url>"] + \
           [f"<url><loc>{SITE_URL}/articles/{a}</loc></url>" for a in arts]
    with open("sitemap.xml", "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + "".join(urls) + "</urlset>\n")
    print(f"Wrote {sum(len(s['stories']) for s in edition['sections'])} articles, data.js, archive, sitemap.")


# ----------------------------------------------------------------- archive ---
def build_archive():
    """Regenerates archive.html from every saved edition: a static, crawlable
    listing of all published stories with client-side date/category/source filters."""
    import glob
    e = html.escape
    editions = []
    archive_cutoff = NOW - timedelta(weeks=4)  # keep at most 4 weeks in the archive
    for path in sorted(glob.glob("editions/*.json"), reverse=True):
        stamp = os.path.basename(path)[:13]
        try:
            when = datetime.strptime(stamp, "%Y-%m-%d-%H").replace(tzinfo=IST)
        except ValueError:
            continue
        if when < archive_cutoff:
            continue  # older than 4 weeks — excluded from the archive page
        try:
            with open(path, encoding="utf-8") as f:
                editions.append((when, json.load(f)))
        except Exception:
            continue
    seen, dates, cats, sources = set(), [], {}, set()
    seen_fps = []
    rows_by_date = {}
    for when, ed in editions:
        dkey = when.strftime("%Y-%m-%d")
        dlabel = when.strftime("%A, %d %B %Y")
        for sec in ed.get("sections", []):
            cats[sec["id"]] = sec["name"]
            for st in sec.get("stories", []):
                key = st.get("slug") or st["headline"]
                if key in seen:
                    continue
                fp = _story_fingerprint(st)
                if _is_dupe(fp, seen_fps):
                    continue
                seen.add(key)
                seen_fps.append(fp)
                sources.add(st.get("source", ""))
                if dkey not in rows_by_date:
                    rows_by_date[dkey] = (dlabel, [])
                    dates.append((dkey, dlabel))
                link = (f"articles/{st['slug']}.html" if st.get("slug") else st.get("url", "#"))
                hue = SECTION_HUES.get(sec["id"], "#0E7B52")
                rows_by_date[dkey][1].append(
                    (st.get("hour", 0),
                     f'<li class="ar" data-d="{dkey}" data-c="{sec["id"]}" data-s="{e(st.get("source",""))}">'
                     f'<span class="tm">{e(st.get("time",""))}</span>'
                     f'<span class="cd" style="background:{hue}" title="{e(sec["name"])}"></span>'
                     f'<a class="hl" href="{e(link)}">{e(st["headline"])}</a>'
                     f'<span class="so">{e(st.get("source",""))}</span></li>'))
    def day_html(dkey, dlabel):
        rows = [html_ for _, html_ in sorted(rows_by_date[dkey][1], key=lambda r: -r[0])]
        return f'<div class="day" data-d="{dkey}"><h2>{e(dlabel)}</h2><ul>{"".join(rows)}</ul></div>'
    groups = "".join(day_html(dkey, dlabel) for dkey, dlabel in dates)
    date_opts = "".join(f'<option value="{d}">{l}</option>' for d, l in dates)
    cat_opts = "".join(f'<option value="{c}">{e(n)}</option>' for c, n in sorted(cats.items(), key=lambda x: x[1]))
    src_opts = "".join(f'<option value="{e(s)}">{e(s)}</option>' for s in sorted(x for x in sources if x))
    total = len(seen)
    _arch_mhead = masthead_html([("Current Affairs", "/current-affairs.html", True),
                                 ("Home", "/", False)])
    _arch_mcss = masthead_css()
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><!-- Google tag (gtag.js) with Consent Mode v2 --><script async src="https://www.googletagmanager.com/gtag/js?id=G-B1R3X3GKJ3"></script><script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag('consent','default',{{'ad_storage':'denied','ad_user_data':'denied','ad_personalization':'denied','analytics_storage':'denied','wait_for_update':500}});gtag('js',new Date());gtag('config','G-B1R3X3GKJ3');try{{if(localStorage.getItem('cookie-consent')==='granted'){{gtag('consent','update',{{'ad_storage':'granted','ad_user_data':'granted','ad_personalization':'granted','analytics_storage':'granted'}});}}}}catch(e){{}}</script><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Archive — {SITE_NAME}</title>
<meta name="description" content="Browse every story published by {SITE_NAME}, by date, category and source. All stories from verified publishers, each linked to the original reporting.">
<link rel="canonical" href="{SITE_URL}/archive.html">
<meta property="og:type" content="website"><meta property="og:title" content="Archive — {SITE_NAME}">
<link rel="manifest" href="manifest.json"><meta name="theme-color" content="#0E130E"><link rel="icon" href="favicon.ico" sizes="any"><link rel="apple-touch-icon" href="apple-touch-icon.png">
<style>
:root{{--paper:#F6F6F4;--ink:#101410;--ink-soft:#43493F;--meta:#71766C;--hairline:#E5E7E0;--dark:#0D120D;--green:#0E7B52;--green-bright:#3BCB8D;
--display:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
--body:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
--mono:ui-monospace,"SF Mono",SFMono-Regular,"Roboto Mono",Menlo,Consolas,monospace;--mw:900px}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--paper);color:var(--ink);font-family:var(--body);line-height:1.55;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:900px;margin:0 auto;padding:0 24px}}
/*MASTHEAD_CSS*/
h1{{font-family:var(--display);font-weight:800;font-size:clamp(28px,5vw,38px);letter-spacing:-.02em;margin:32px 0 6px}}
.sub{{font-family:var(--mono);font-size:12px;color:var(--meta);margin-bottom:22px}}
.filters{{display:flex;gap:10px;flex-wrap:wrap;position:sticky;top:0;background:rgba(246,246,244,.94);backdrop-filter:blur(10px);padding:12px 0;border-bottom:1px solid var(--hairline);z-index:5}}
select{{font-family:var(--body);font-size:13.5px;font-weight:600;color:var(--ink);background:#fff;border:1px solid var(--hairline);border-radius:10px;padding:9px 12px;cursor:pointer}}
select:focus{{outline:2px solid var(--green)}}
.day{{padding-top:26px}}
.day h2{{font-family:var(--display);font-weight:800;font-size:15px;letter-spacing:.08em;text-transform:uppercase;border-bottom:1px solid var(--ink);padding-bottom:9px;margin-bottom:4px}}
ul{{list-style:none}}
.ar{{display:flex;align-items:baseline;gap:12px;padding:13px 0;border-bottom:1px solid var(--hairline)}}
.ar .tm{{font-family:var(--mono);font-size:11px;color:var(--meta);flex:0 0 76px}}
.ar .cd{{width:8px;height:8px;border-radius:50%;flex-shrink:0;align-self:center}}
.ar .hl{{font-family:var(--display);font-weight:600;font-size:16px;line-height:1.3;text-decoration:none;flex:1}}
.ar .hl:hover{{text-decoration:underline;text-underline-offset:3px}}
.ar .so{{font-family:var(--mono);font-size:11px;color:var(--meta);flex-shrink:0}}
@media (max-width:560px){{.ar{{flex-wrap:wrap}}.ar .tm{{flex:0 0 auto}}.ar .so{{width:100%;padding-left:20px}}}}
.empty{{font-family:var(--mono);font-size:12.5px;color:var(--meta);padding:40px 0;text-align:center;display:none}}
footer{{background:var(--dark);color:#929C8E;margin-top:48px;padding:28px 0 64px;font-size:12px;line-height:1.8}}
footer a{{color:var(--green-bright);text-decoration:none;margin-right:14px}}
</style></head>
<body>
{_arch_mhead}
<div class="wrap">
<h1>Every story we've published.</h1>
<p class="sub">{total} stories · all from verified publishers · each linked to its original source</p>
<div class="filters">
  <select id="f-d" aria-label="Filter by date"><option value="">All dates</option>{date_opts}</select>
  <select id="f-c" aria-label="Filter by category"><option value="">All categories</option>{cat_opts}</select>
  <select id="f-s" aria-label="Filter by source"><option value="">All sources</option>{src_opts}</select>
</div>
{groups}
<p class="empty" id="empty">No stories match those filters.</p>
</div>
<footer><div class="wrap"><p><a href="/">Today's brief</a><a href="about.html">About</a><a href="contact.html">Contact</a><a href="privacy.html">Privacy</a></p>
<p>{SITE_NAME} — automated brief from verified publishers. Founded by Pankaj Kumar.</p></div></footer>
<script>
(function(){{
  var fd=document.getElementById('f-d'),fc=document.getElementById('f-c'),fs=document.getElementById('f-s');
  function apply(){{
    var d=fd.value,c=fc.value,s=fs.value,any=false;
    document.querySelectorAll('.ar').forEach(function(r){{
      var on=(!d||r.dataset.d===d)&&(!c||r.dataset.c===c)&&(!s||r.dataset.s===s);
      r.style.display=on?'':'none'; if(on) any=true;
    }});
    document.querySelectorAll('.day').forEach(function(g){{
      g.style.display=[].some.call(g.querySelectorAll('.ar'),function(r){{return r.style.display!=='none';}})?'':'none';
    }});
    document.getElementById('empty').style.display=any?'none':'block';
  }}
  [fd,fc,fs].forEach(function(el){{el.addEventListener('change',apply);}});
  var q=new URLSearchParams(location.search);
  if(q.get('cat')) fc.value=q.get('cat');
  if(q.get('date')) fd.value=q.get('date');
  if(q.get('src')) fs.value=q.get('src');
  if(q.get('cat')||q.get('date')||q.get('src')) apply();
}})();
</script>
</body></html>"""
    page = page.replace("/*MASTHEAD_CSS*/", _arch_mcss)
    with open("archive.html", "w", encoding="utf-8") as f:
        f.write(page)
    print(f"archive.html rebuilt: {total} stories across {len(dates)} days.")

def build_tweet_queue(edition, max_per_day=10):
    """After each run, generate personalised reporting tweets for the most
    important new stories and append them to tweets/queue.json (deduped, capped
    at max_per_day per IST day). n8n reads this queue and posts to X."""
    import glob
    os.makedirs("tweets", exist_ok=True)
    qpath = "tweets/queue.json"
    today = NOW.strftime("%Y-%m-%d")

    # Load existing queue; reset the day's counter if it's a new day.
    queue = {"day": today, "posted_keys": [], "pending": []}
    if os.path.exists(qpath):
        try:
            with open(qpath, encoding="utf-8") as f:
                loaded = json.load(f)
            if loaded.get("day") == today:
                queue = loaded
        except Exception:
            pass

    already = set(queue.get("posted_keys", [])) | {t["key"] for t in queue.get("pending", [])}
    day_count = len(queue.get("posted_keys", [])) + len(queue.get("pending", []))
    room = max_per_day - day_count
    if room <= 0:
        print(f"Tweet quota for {today} reached ({day_count}/{max_per_day}); none added.")
        with open(qpath, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        return

    # Rank this run's stories: breaking first, then most recent.
    ranked = []
    for sec in edition["sections"]:
        for st in sec["stories"]:
            ranked.append((sec, st))
    ranked.sort(key=lambda p: (not p[1].get("breaking", False), -(p[1].get("hour", 0))))

    site = os.environ.get("SITE_URL", "https://thelast24.in").rstrip("/")
    added = 0
    for sec, st in ranked:
        if added >= room:
            break
        key = st.get("slug") or st.get("headline")
        if key in already:
            continue
        link = f"{site}/articles/{st['slug']}.html" if st.get("slug") else site
        tweet = generate_tweet(st, sec["name"], link)
        if not tweet:
            continue
        queue["pending"].append({"key": key, "text": tweet, "url": link,
                                 "section": sec["name"],
                                 "created": NOW.strftime("%Y-%m-%d %H:%M IST")})
        already.add(key)
        added += 1

    with open(qpath, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)
    print(f"Tweet queue: added {added}, pending {len(queue['pending'])}, "
          f"day total {day_count + added}/{max_per_day}.")


def generate_tweet(st, section_name, link):
    """One personalised, reporting-style tweet (<=270 chars incl. link) with
    2-3 relevant hashtags. Factual, punchy, never sensational — fits a verified
    news brand. Returns None on failure."""
    sys_prompt = (
        "You write tweets for 'The Last 24', a verified Indian news brief. Voice: "
        "a sharp, trustworthy reporter — punchy but factual, never clickbait, never "
        "sensational, no fabricated detail. Write ONE tweet for the story below.\n"
        "Rules: under 230 characters of text (a link is appended separately). Lead "
        "with the news. Name the real people/places/figures. Add a crisp reason it "
        "matters if it fits. End with 2-3 relevant hashtags (e.g. #IndiaNews plus "
        "topical ones). No 'BREAKING' unless it truly is. No emojis except at most one. "
        'Respond with ONLY this JSON: {"tweet":"...the tweet text with hashtags..."}')
    user = (f"Section: {section_name}\nHeadline: {st['headline']}\n"
            f"Summary: {st.get('what','')}\nWhy it matters: {st.get('lens','')}")
    try:
        data = extract_json(call_claude(sys_prompt, user, 400), "tweet")
        text = str(data.get("tweet", "")).strip()
        if not text:
            return None
        # Keep room for the link (~24 chars on X via t.co) + a space.
        if len(text) > 250:
            text = text[:247].rsplit(" ", 1)[0] + "…"
        return f"{text}\n{link}"
    except (RuntimeError, ValueError) as exc:
        print(f"  tweet generation failed for '{st.get('headline','')[:40]}': {exc}")
        return None


def main():
    raw = collect_headlines()
    print(f"Collected {len(raw.splitlines())} headlines.")
    edition = write_edition(raw)
    write_outputs(edition)
    build_archive()
    build_tweet_queue(edition, max_per_day=10)
    # Current Affairs (UPSC/IAS) — re-curate the same headlines, exam-framed.
    try:
        import build_current_affairs as bca
        bca.build_current_affairs(raw, call_claude, extract_json)
    except Exception as exc:
        print(f"Current affairs step skipped: {exc}")

if __name__ == "__main__":
    main()
