#!/usr/bin/env python3
"""
The Last 24 — Current Affairs (UPSC/IAS) builder.

Runs as part of the 6-hourly pipeline. Takes the SAME collected headlines and
re-curates them through an exam-relevance lens for UPSC/State PSC aspirants,
organised into the categories aspirants actually study by (Polity & Governance,
Economy, International Relations, Environment, Science & Tech, Schemes, Defence,
Reports & Indices, Persons in News, Places in News, Art & Culture).

Each item gets: a crisp factual summary, the exam angle ("why it's relevant"),
the GS paper it maps to, and key facts to remember.

Outputs:
  current-affairs.js     (window.CA — latest curated current affairs)
  current-affairs.html   (the dedicated, prominently-linked page)
"""
import os, json, html
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(IST)
SITE_URL = os.environ.get("SITE_URL", "https://thelast24.in").rstrip("/")

# UPSC-style categories (mirrors how aspirants study; inspired by standard CA taxonomy)
CA_CATEGORIES = [
    ("polity", "Polity & Governance", "#0E7B52"),
    ("economy", "Economy & Banking", "#B07A1F"),
    ("ir", "International Relations", "#1F5FA8"),
    ("environment", "Environment & Ecology", "#2E8B57"),
    ("scitech", "Science & Technology", "#6A3FB5"),
    ("schemes", "Govt Schemes & Policies", "#0E8E8E"),
    ("defence", "Defence & Security", "#CE3D1D"),
    ("reports", "Reports & Indices", "#9A6A00"),
    ("persons", "Persons & Awards in News", "#C2317E"),
    ("places", "Places in News", "#3B7A57"),
    ("culture", "Art & Culture", "#A8432B"),
]
CA_HUES = {cid: hue for cid, name, hue in CA_CATEGORIES}
CA_NAMES = {cid: name for cid, name, hue in CA_CATEGORIES}

CA_RULES = """You are the Current Affairs editor of "The Last 24", preparing exam-relevant current affairs for UPSC / IAS / State PSC aspirants in India. You are given raw news headlines from verified publishers covering the last 24 hours.

Your job: select ONLY the genuinely EXAM-RELEVANT items and write them up the way a serious current-affairs resource (like GKToday / Vision IAS) would. IGNORE celebrity gossip, routine sports, entertainment, and anything with no exam value. KEEP: government schemes, policies, bills, Supreme Court / constitutional matters, economy & RBI, international relations & treaties, defence, science & space (ISRO/DRDO), environment & biodiversity, reports & indices & rankings, appointments & awards (persons in news), places in news, summits, art & culture/heritage.

For EACH selected item, produce:
- "title": a crisp, factual headline (not clickbait)
- "category": one of EXACTLY these ids: polity, economy, ir, environment, scitech, schemes, defence, reports, persons, places, culture
- "summary": 3-4 sentences of factual, exam-useful summary — what happened, the key specifics (names, numbers, dates, bodies involved)
- "exam_angle": 1-2 sentences on WHY this matters for the exam / which concept it connects to
- "gs_paper": the relevant General Studies paper as a short string, e.g. "GS Paper 2 (Polity)", "GS Paper 3 (Economy)", "GS Paper 1 (Geography)", "GS Paper 2 (IR)", "GS Paper 3 (Sci-Tech)", "GS Paper 3 (Environment)", "GS Paper 1 (Culture)"
- "key_facts": an array of 2-4 short bullet strings — the precise facts an aspirant should memorise (e.g. "Launched by: Ministry of...", "Budget: Rs X crore", "Article involved: 21")
- "source": the publisher name

Return ONLY valid JSON: {"items":[ {...}, {...} ]}. Aim for the 12-20 most exam-relevant items across categories. No commentary outside the JSON."""


def build_current_affairs(raw_headlines, call_claude, extract_json, write_page=True):
    """Curate exam-relevant current affairs from the collected headlines.
    `call_claude` and `extract_json` are passed in from build_edition to reuse
    the same API client + safe JSON parsing."""
    # The raw headlines string is large; send it directly — the model selects.
    user = ("Raw headlines from verified publishers (last 24h). Select the most "
            "exam-relevant and write them up:\n\n" + raw_headlines)
    try:
        data = extract_json(call_claude(CA_RULES, user, 8000), "current-affairs")
        items = data.get("items", []) if isinstance(data, dict) else []
    except Exception as exc:
        print(f"Current affairs curation failed: {exc}")
        items = []

    # Clean + validate
    clean = []
    seen = set()
    for it in items:
        title = (it.get("title") or "").strip()
        cat = (it.get("category") or "").strip()
        if not title or cat not in CA_NAMES:
            continue
        key = title.lower()[:60]
        if key in seen:
            continue
        seen.add(key)
        kf = it.get("key_facts") or []
        if isinstance(kf, str):
            kf = [kf]
        clean.append({
            "title": title,
            "category": cat,
            "category_name": CA_NAMES[cat],
            "summary": (it.get("summary") or "").strip(),
            "exam_angle": (it.get("exam_angle") or "").strip(),
            "gs_paper": (it.get("gs_paper") or "").strip(),
            "key_facts": [str(x).strip() for x in kf if str(x).strip()][:4],
            "source": (it.get("source") or "").strip(),
        })

    ca = {
        "date": NOW.strftime("%A, %d %B %Y"),
        "updated": NOW.strftime("%Y-%m-%d %H:%M"),
        "updated_label": NOW.strftime("%d %b %Y, %H:%M IST"),
        "items": clean,
        "categories": [{"id": c, "name": n} for c, n, h in CA_CATEGORIES
                       if any(x["category"] == c for x in clean)],
    }

    with open("current-affairs.js", "w", encoding="utf-8") as f:
        f.write("window.CA = " + json.dumps(ca, ensure_ascii=False) + ";")
    print(f"Current affairs: {len(clean)} exam-relevant items across "
          f"{len(ca['categories'])} categories.")

    if write_page:
        with open("current-affairs.html", "w", encoding="utf-8") as f:
            f.write(current_affairs_page())
    return ca


def current_affairs_page():
    """The dedicated Current Affairs page. Reads current-affairs.js (window.CA)
    and renders category-filtered, exam-framed cards. Brand-consistent with the
    rest of the site (dark masthead, mono accents, category hues)."""
    cat_chips = "".join(
        f'<button class="ca-chip" data-cat="{cid}">{name}</button>'
        for cid, name, hue in CA_CATEGORIES)
    hue_js = json.dumps(CA_HUES)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Current Affairs for UPSC & IAS — The Last 24</title>
<meta name="description" content="Daily exam-relevant current affairs for UPSC, IAS and State PSC aspirants — polity, economy, international relations, schemes, science & tech, environment and more. Updated through the day. Verified sources only.">
<link rel="canonical" href="{SITE_URL}/current-affairs.html">
<meta property="og:title" content="Current Affairs for UPSC & IAS — The Last 24">
<meta property="og:description" content="Daily exam-relevant current affairs for UPSC/IAS aspirants. Verified sources, updated through the day.">
<meta property="og:url" content="{SITE_URL}/current-affairs.html">
<link rel="icon" href="favicon.ico">
<style>
  :root{{
    --paper:#f6f6f4;--ink:#0d120d;--meta:#5d6b5d;--hairline:#e3e6e0;--green:#0E7B52;
    --green-bright:#3BCB8D;--display:'Georgia',serif;--body:system-ui,-apple-system,'Segoe UI',sans-serif;
    --mono:ui-monospace,'SF Mono',Menlo,monospace;
  }}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--paper);color:var(--ink);font-family:var(--body);line-height:1.6}}
  a{{color:inherit}}
  .masthead{{background:var(--ink);color:var(--paper);padding:20px 0}}
  .wrap{{max-width:920px;margin:0 auto;padding:0 20px}}
  .brand{{font-family:var(--display);font-weight:800;font-size:clamp(28px,4vw,34px);letter-spacing:-.02em;text-decoration:none;color:var(--paper);line-height:1}}
  .brand b{{color:var(--green-bright)}}
  .masthead .wrap{{display:flex;align-items:center;justify-content:space-between;gap:14px}}
  .brand-side{{display:flex;align-items:center;gap:18px;flex-wrap:wrap;justify-content:flex-end}}
  .brand-nav{{display:flex;align-items:center;gap:10px}}
  .m-link{{font-family:var(--mono);font-size:12px;color:var(--paper);text-decoration:none;border:1px solid rgba(255,255,255,.25);padding:7px 14px;border-radius:999px;transition:all .18s;white-space:nowrap}}
  .m-link:hover{{border-color:var(--green-bright);color:var(--green-bright)}}
  .brand-meta{{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:#929C8E;text-align:right;line-height:1.7}}
  .brand-meta .v{{color:var(--green-bright);font-weight:600}}
  .hero{{padding:34px 0 8px}}
  .hero h1{{font-family:var(--display);font-weight:800;font-size:clamp(28px,5vw,40px);line-height:1.1;margin:0 0 10px;letter-spacing:-.02em}}
  .hero p{{font-size:16px;color:var(--meta);max-width:640px;margin:0}}
  .updated{{font-family:var(--mono);font-size:12px;color:var(--meta);margin-top:14px}}
  .updated b{{color:var(--green)}}
  nav.cats{{position:sticky;top:0;background:var(--paper);border-bottom:1px solid var(--hairline);z-index:5}}
  .cats-row{{display:flex;gap:6px;overflow-x:auto;padding:12px 0;scrollbar-width:none}}
  .cats-row::-webkit-scrollbar{{display:none}}
  .ca-chip{{flex:0 0 auto;font-family:var(--mono);font-size:12px;padding:8px 14px;border:1px solid var(--hairline);
    background:#fff;border-radius:999px;cursor:pointer;white-space:nowrap;color:var(--ink)}}
  .ca-chip.active{{background:var(--ink);color:var(--paper);border-color:var(--ink)}}
  .items{{padding:24px 0 60px}}
  .ca-card{{background:#fff;border:1px solid var(--hairline);border-radius:14px;padding:22px 22px;margin-bottom:16px;border-left:4px solid var(--green)}}
  .ca-kick{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}}
  .ca-cat{{font-family:var(--mono);font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase}}
  .ca-gs{{font-family:var(--mono);font-size:11px;color:var(--meta);background:var(--paper);padding:3px 8px;border-radius:6px}}
  .ca-card h3{{font-family:var(--display);font-size:21px;line-height:1.25;margin:0 0 10px}}
  .ca-summary{{font-size:15.5px;margin:0 0 14px}}
  .ca-angle{{font-size:14.5px;background:var(--paper);border-radius:10px;padding:12px 14px;margin:0 0 14px}}
  .ca-angle b{{color:var(--green)}}
  .ca-facts{{margin:0 0 6px;padding:0;list-style:none}}
  .ca-facts li{{font-size:14px;padding:4px 0 4px 18px;position:relative}}
  .ca-facts li::before{{content:"▸";position:absolute;left:0;color:var(--green)}}
  .ca-src{{font-family:var(--mono);font-size:11px;color:var(--meta);margin-top:8px}}
  .empty{{text-align:center;color:var(--meta);padding:60px 0;font-family:var(--mono);font-size:13px}}
  footer{{border-top:1px solid var(--hairline);padding:30px 0;font-family:var(--mono);font-size:12px;color:var(--meta);text-align:center}}
  @media (max-width:600px){{
    .wrap{{padding:0 14px}}
    .ca-card{{padding:18px 16px}}
    .ca-card h3{{font-size:19px}}
    .hero h1{{font-size:26px}}
    .brand-meta{{display:none}}
    .masthead .wrap{{flex-wrap:wrap;gap:10px}}
    .brand-side{{width:100%;justify-content:flex-start}}
    .m-link{{font-size:11px;padding:6px 12px}}
  }}
</style>
</head>
<body>
<header class="masthead"><div class="wrap">
  <a class="brand" href="/">The Last <b>24</b></a>
  <div class="brand-side"><div class="brand-nav"><a class="m-link" href="/archive.html">Archive</a><a class="m-link" href="/">Home</a></div><div class="brand-meta"><span class="v">✓ Verified publishers only</span></div></div>
</div></header>

<div class="wrap hero">
  <h1>Current Affairs</h1>
  <p>Exam-relevant current affairs, curated from verified publishers and updated through the day. Polity, economy, international relations, schemes, science &amp; tech, environment and more — each with the exam angle and key facts.</p>
  <div class="updated" id="updated"></div>
</div>

<nav class="cats"><div class="wrap"><div class="cats-row" id="cats">
  <button class="ca-chip active" data-cat="all">All</button>
  {cat_chips}
</div></div></nav>

<div class="wrap items" id="items"></div>

<footer><div class="wrap">
  The Last 24 · Verified publishers only · <a href="/">Home</a> · <a href="/archive.html">Archive</a>
</div></footer>

<script src="current-affairs.js"></script>
<script>
  var HUES = {hue_js};
  var CA = window.CA || {{items:[],categories:[],updated_label:""}};
  var filter = 'all';

  function esc(s){{ return (s||'').replace(/[&<>"]/g,function(c){{return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c];}}); }}

  function render(){{
    var box = document.getElementById('items');
    var items = CA.items.filter(function(x){{ return filter==='all' || x.category===filter; }});
    if(!items.length){{ box.innerHTML = '<div class="empty">No current affairs in this category right now — check back after the next update.</div>'; return; }}
    box.innerHTML = items.map(function(x){{
      var hue = HUES[x.category] || '#0E7B52';
      var facts = (x.key_facts||[]).map(function(f){{ return '<li>'+esc(f)+'</li>'; }}).join('');
      return '<article class="ca-card" style="border-left-color:'+hue+'">'
        + '<div class="ca-kick"><span class="ca-cat" style="color:'+hue+'">'+esc(x.category_name)+'</span>'
        + (x.gs_paper?'<span class="ca-gs">'+esc(x.gs_paper)+'</span>':'')+'</div>'
        + '<h3>'+esc(x.title)+'</h3>'
        + (x.summary?'<p class="ca-summary">'+esc(x.summary)+'</p>':'')
        + (x.exam_angle?'<div class="ca-angle"><b>Why it matters for the exam:</b> '+esc(x.exam_angle)+'</div>':'')
        + (facts?'<ul class="ca-facts">'+facts+'</ul>':'')
        + (x.source?'<div class="ca-src">via '+esc(x.source)+' ✓</div>':'')
        + '</article>';
    }}).join('');
  }}

  function setFilter(c){{
    filter = c;
    [].forEach.call(document.querySelectorAll('.ca-chip'), function(b){{
      b.classList.toggle('active', b.getAttribute('data-cat')===c);
    }});
    render();
  }}

  document.getElementById('cats').addEventListener('click', function(e){{
    var b = e.target.closest('.ca-chip'); if(b) setFilter(b.getAttribute('data-cat'));
  }});

  var present = {{}};
  CA.items.forEach(function(x){{ present[x.category]=true; }});
  [].forEach.call(document.querySelectorAll('.ca-chip'), function(b){{
    var c = b.getAttribute('data-cat');
    if(c!=='all' && !present[c]) b.style.display='none';
  }});

  document.getElementById('updated').innerHTML = CA.updated_label
    ? 'Updated <b>'+esc(CA.updated_label)+'</b> · '+CA.items.length+' items today' : '';
  render();
</script>
</body>
</html>"""
