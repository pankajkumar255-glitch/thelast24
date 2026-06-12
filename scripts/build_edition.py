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
    "Technology":         "India technology OR startup OR AI",
    "Sports":             "India cricket OR sports",
    "Entertainment":      "Bollywood OR Indian entertainment OR OTT",
}
PER_SECTION = 4

SECTION_HUES = {  # category accent colors (also used by generative art)
    "national": "#0E7B52", "world": "#1F5FA8", "business": "#B07A1F",
    "tech": "#6A3FB5", "sports": "#CE3D1D", "entertainment": "#C2317E",
}

# ---------------------------------------------------------------- collect ---
def gnews_rss(query, window):
    q = requests.utils.quote(f"{query} {window}")
    return f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"

# The moat: only stories from established, verified publishers pass this filter.
TRUSTED_PUBLISHERS = [
    "the hindu", "hindustan times", "indian express", "times of india",
    "economic times", "mint", "livemint", "business standard", "moneycontrol",
    "reuters", "press trust of india", "pti", "ani", "ndtv", "india today",
    "the print", "deccan herald", "telegraph india", "financial express",
    "cnbc", "bbc", "news18", "firstpost", "outlook", "frontline", "the wire",
    "espncricinfo", "cricbuzz", "sportstar", "olympics.com",
    "bollywood hungama", "film companion", "pinkvilla", "variety", "pib",
]

def is_trusted(source_name):
    n = (source_name or "").lower()
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
SYSTEM_RULES = """You are the editor of "The Last 24", an automated brief covering everything that mattered in India in the last 24 hours, for a general Indian reader. Every headline you receive comes from a verified, established publisher.

EDITORIAL RULES:
- Sort stories into sections (only those with stories): national (National), world (World), business (Business & Markets), tech (Technology), sports (Sports), entertainment (Entertainment). Input may suggest a section in [brackets]; re-assign if clearly wrong.
- Pick the strongest stories per section; drop weak/duplicate ones (keep 2 per section normally; keep up to 6 per section if the input is a multi-day backfill).
- WRITE DIRECTLY AND CONCRETELY: name the companies, brands, people, places and figures exactly as the headlines give them ("Reliance", "Zomato", "Virat Kohli", "Rs 2,000 crore"). NEVER use vague substitutes like "a major company", "two platforms", or "a leading bank".
- "what" = a substantial 3-4 sentence standfirst (roughly 55-80 words): state the development precisely, add the key detail, and close with one line of immediate significance. Built strictly from the headline plus universally known background — this is the homepage preview and must deliver real value on its own without a click.
- "lens" = 1 sharp sentence: why this matters to an everyday Indian reader — money, daily life, or the bigger picture. Never vague.
- Structured summary (a detailed, well-developed brief of roughly 450-600 words total — citable and strictly grounded):
  - "what_happened" = 4-6 sentences attributing the publisher by name (e.g. "The Hindu reports that..."). Restate the development fully and precisely. Use ONLY what the headline states plus universally known facts; NEVER invent quotes, statistics, numbers, or names.
  - "context" = 4-6 sentences of widely-known background: the history of this issue, the key players and their roles, relevant prior developments, and how India typically handles such matters. Depth must come from established general knowledge, never speculation about this specific event.
  - "why_it_matters" = 3-5 sentences of concrete impact: on prices, jobs, daily life, investments, or the bigger national picture. Specific and practical, expanding well beyond the one-line lens.
  - "whats_next" = 2-3 sentences on the likely sequence ahead and what readers should watch for, clearly framed as expectation ("expect", "likely", "watch for") not fact.
- "image_query" = a 2-4 word GENERIC stock-photo phrase for the story (e.g. "stock market screens", "cricket stadium floodlights"). Never names of real people or brands.
- "hour" = integer 0-23 from the IST time. "time" = "HH:MM IST". "breaking" = true for at most 1-2 items.
- Keep source names and URLs exactly as given.
- "topline" = one sentence capturing the day's arc, naming the biggest entities directly.

Respond with ONLY a JSON object (no markdown fences):
{"date":"...","edition":"...","topline":"...","lensLabel":"Why it matters","sections":[{"id":"...","name":"...","stories":[{"hour":0,"time":"...","headline":"...","what":"...","lens":"...","what_happened":"...","context":"...","why_it_matters":"...","whats_next":"...","image_query":"...","source":"...","url":"...","breaking":false}]}]}"""

def write_edition(raw):
    key = os.environ.get("ANTHROPIC_API_KEY") or sys.exit("ANTHROPIC_API_KEY not set.")
    r = requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": "claude-sonnet-4-6", "max_tokens": 12000, "system": SYSTEM_RULES,
              "messages": [{"role": "user", "content":
                  f"Edition date: {NOW.strftime('%A, %d %B %Y')}\nEdition number: {NOW.strftime('%Y-%m-%d %H:%M')}\n\nRaw headlines from the last 24 hours:\n{raw}"}]},
        timeout=300)
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json()["content"] if b["type"] == "text")
    return json.loads(re.sub(r"```json|```", "", text).strip())

# ---------------------------------------------------------- licensed photos ---
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "")

def fetch_photo(query):
    """Free, commercially-licensed photo from Pexels. Returns None on any miss
    (the generative art fallback takes over). Never scrape publisher images:
    credit is not a license — that's copyright infringement."""
    if not PEXELS_KEY or not query:
        return None
    try:
        r = requests.get("https://api.pexels.com/v1/search",
                         headers={"Authorization": PEXELS_KEY},
                         params={"query": query, "per_page": 1, "orientation": "landscape"},
                         timeout=20)
        r.raise_for_status()
        photos = r.json().get("photos") or []
        if not photos:
            return None
        p = photos[0]
        return {"image": p["src"]["large"],
                "image_credit": p.get("photographer", "Pexels"),
                "image_credit_url": p.get("photographer_url", "https://www.pexels.com")}
    except Exception as exc:
        print(f"pexels miss for '{query}': {exc}")
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

def slugify(headline):
    s = re.sub(r"[^a-z0-9]+", "-", headline.lower()).strip("-")
    return s[:70].rstrip("-")

# ----------------------------------------------------------- article page ---
def summary_blocks(story):
    """Ordered (label, text) pairs; tolerates older 'article' format."""
    blocks = [("What happened", story.get("what_happened")),
              ("The context", story.get("context")),
              ("Why it matters", story.get("why_it_matters")),
              ("What's next", story.get("whats_next"))]
    blocks = [(l, t) for l, t in blocks if t]
    if not blocks and story.get("article"):
        blocks = [("The brief", p.strip()) for p in story["article"].split("\n\n") if p.strip()]
    return blocks

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
        hero = (f'<figure class="hero"><img src="{e(story["image"])}" alt="{e(story["headline"])}" loading="eager">'
                f'<figcaption>Photo: <a href="{e(story.get("image_credit_url","#"))}" rel="noopener" target="_blank">'
                f'{e(story.get("image_credit","Pexels"))}</a> via Pexels (free license)</figcaption></figure>')
    else:
        hero = f'<div class="hero">{art_svg(story["headline"], section["id"])}</div>'
    blocks = "".join(
        f'<div class="block"><h2>{e(label)}</h2><p>{e(text)}</p></div>'
        for label, text in summary_blocks(story))
    src_name = e(story.get("source", "the original source"))
    src_url = e(story.get("url", "#"))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{e(story['headline'])} — {SITE_NAME}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{SITE_URL}/articles/{story['slug']}.html">
<meta property="og:type" content="article"><meta property="og:title" content="{e(story['headline'])}">
<meta property="og:description" content="{desc}"><meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:url" content="{SITE_URL}/articles/{story['slug']}.html">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{jsonld}</script>
<style>
:root{{--paper:#F7F7F5;--ink:#111511;--ink-soft:#454B43;--meta:#73786F;--hairline:#E6E8E2;--hue:{hue};
--display:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
--body:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
--mono:ui-monospace,"SF Mono",SFMono-Regular,"Roboto Mono",Menlo,Consolas,monospace}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--paper);color:var(--ink);font-family:var(--body);line-height:1.6;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:660px;margin:0 auto;padding:0 20px}}
.topbar{{background:#0E130E;margin-bottom:30px}}
.top{{font-family:var(--mono);font-size:12px;padding:16px 20px;display:flex;justify-content:space-between;align-items:center;max-width:660px;margin:0 auto}}
.top a{{color:#F2F4EE;text-decoration:none;font-weight:800;font-family:var(--display);font-size:22px}}.top a span{{color:#3BCB8D}}
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
.block{{padding:18px 0;border-bottom:1px solid var(--hairline)}}
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
<div class="topbar"><div class="top"><a href="../index.html">The Last <span>24</span></a><span class="cat">{e(section['name'])}</span></div></div>
<div class="wrap">
<p class="kick"><b>✓ Verified source:</b> {src_name} · {e(story['time'])} · {e(edition['date'])}</p>
<h1>{e(story['headline'])}</h1>
{hero}
<article>
{blocks}
</article>
<a class="cta" href="{src_url}" rel="noopener" target="_blank">Read the full story at {src_name} →</a>
<p class="cite">This is a summary brief. Original reporting and all facts: <a href="{src_url}" rel="noopener" target="_blank">{src_name}</a>.</p>
<div class="ad-slot"><!-- AD SLOT: article-mid. Paste your AdSense/ad-network snippet here. -->Ad space</div>
</div>
<footer><div class="wrap"><p><a href="../index.html">Today's brief</a> · <a href="../about.html">About</a> · <a href="../contact.html">Contact</a> · <a href="../privacy.html">Privacy</a></p><p>{SITE_NAME} curates exclusively from verified publishers. Founded by Pankaj.</p></div></footer>
</body></html>"""

# ---------------------------------------------------------------- outputs ---
def write_outputs(edition):
    os.makedirs("articles", exist_ok=True)
    os.makedirs("editions", exist_ok=True)
    for sec in edition["sections"]:
        for st in sec["stories"]:
            st["slug"] = NOW.strftime("%Y%m%d") + "-" + slugify(st["headline"])
            photo = fetch_photo(st.pop("image_query", None))
            if photo: st.update(photo)
            with open(f"articles/{st['slug']}.html", "w", encoding="utf-8") as f:
                f.write(article_page(st, sec, edition))
    # homepage data (article text not needed client-side)
    slim = json.loads(json.dumps(edition, ensure_ascii=False))
    for sec in slim["sections"]:
        for st in sec["stories"]:
            for k in ("article", "what_happened", "context", "why_it_matters", "whats_next"):
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
    for path in sorted(glob.glob("editions/*.json"), reverse=True):
        stamp = os.path.basename(path)[:13]
        try:
            when = datetime.strptime(stamp, "%Y-%m-%d-%H").replace(tzinfo=IST)
        except ValueError:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                editions.append((when, json.load(f)))
        except Exception:
            continue
    seen, dates, cats, sources = set(), [], {}, set()
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
                seen.add(key)
                sources.add(st.get("source", ""))
                if dkey not in rows_by_date:
                    rows_by_date[dkey] = (dlabel, [])
                    dates.append((dkey, dlabel))
                link = (f"articles/{st['slug']}.html" if st.get("slug") else st.get("url", "#"))
                hue = SECTION_HUES.get(sec["id"], "#0E7B52")
                rows_by_date[dkey][1].append(
                    f'<li class="ar" data-d="{dkey}" data-c="{sec["id"]}" data-s="{e(st.get("source",""))}">'
                    f'<span class="tm">{e(st.get("time",""))}</span>'
                    f'<span class="cd" style="background:{hue}" title="{e(sec["name"])}"></span>'
                    f'<a class="hl" href="{e(link)}">{e(st["headline"])}</a>'
                    f'<span class="so">{e(st.get("source",""))}</span></li>')
    groups = "".join(
        f'<div class="day" data-d="{dkey}"><h2>{e(dlabel)}</h2><ul>{"".join(rows_by_date[dkey][1])}</ul></div>'
        for dkey, dlabel in dates)
    date_opts = "".join(f'<option value="{d}">{l}</option>' for d, l in dates)
    cat_opts = "".join(f'<option value="{c}">{e(n)}</option>' for c, n in sorted(cats.items(), key=lambda x: x[1]))
    src_opts = "".join(f'<option value="{e(s)}">{e(s)}</option>' for s in sorted(x for x in sources if x))
    total = len(seen)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Archive — {SITE_NAME}</title>
<meta name="description" content="Browse every story published by {SITE_NAME}, by date, category and source. All stories from verified publishers, each linked to the original reporting.">
<link rel="canonical" href="{SITE_URL}/archive.html">
<meta property="og:type" content="website"><meta property="og:title" content="Archive — {SITE_NAME}">
<link rel="manifest" href="manifest.json"><meta name="theme-color" content="#0E130E">
<style>
:root{{--paper:#F6F6F4;--ink:#101410;--ink-soft:#43493F;--meta:#71766C;--hairline:#E5E7E0;--dark:#0D120D;--green:#0E7B52;--green-bright:#3BCB8D;
--display:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
--body:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
--mono:ui-monospace,"SF Mono",SFMono-Regular,"Roboto Mono",Menlo,Consolas,monospace}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--paper);color:var(--ink);font-family:var(--body);line-height:1.55;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:900px;margin:0 auto;padding:0 24px}}
.topbar{{background:var(--dark)}}
.top{{font-family:var(--mono);font-size:12px;padding:16px 24px;display:flex;justify-content:space-between;align-items:center;max-width:900px;margin:0 auto}}
.top a{{color:#F2F4EE;text-decoration:none;font-weight:800;font-family:var(--display);font-size:22px}}.top a span{{color:var(--green-bright)}}
.top .pg{{color:#929C8E;font-size:11px;letter-spacing:.12em;text-transform:uppercase}}
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
<div class="topbar"><div class="top"><a href="index.html">The Last <span>24</span></a><span class="pg">Archive</span></div></div>
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
<footer><div class="wrap"><p><a href="index.html">Today's brief</a><a href="about.html">About</a><a href="contact.html">Contact</a><a href="privacy.html">Privacy</a></p>
<p>{SITE_NAME} — automated brief from verified publishers. Founded by Pankaj.</p></div></footer>
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
    with open("archive.html", "w", encoding="utf-8") as f:
        f.write(page)
    print(f"archive.html rebuilt: {total} stories across {len(dates)} days.")

def main():
    raw = collect_headlines()
    raw = "\n".join(raw.splitlines()[:10])
    print(f"Collected {len(raw.splitlines())} headlines.")
    write_outputs(write_edition(raw))
    build_archive()

if __name__ == "__main__":
    main()
