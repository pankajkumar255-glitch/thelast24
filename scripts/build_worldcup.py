#!/usr/bin/env python3
"""
The Last 24 — World Cup 2026 module.

Pulls free, public-domain World Cup data from openfootball (no API key), computes
group standings, converts kickoff times to IST for Indian readers, and writes:
  - worldcup.js    (window.WORLDCUP: standings, recent scores, upcoming fixtures)
  - worldcup.html  (the World Cup section page: standings tables + scores + fixtures)

It also exposes helpers used elsewhere:
  - daily_scores_story()  -> a story dict for the Sports carousel (yesterday/today)
  - standings_payload()   -> structured standings for the Instagram story generator

Time handling: openfootball times look like "20:00 UTC-6". We parse the UTC
offset, convert to UTC, then to IST (UTC+5:30).

Toggle: set WORLDCUP_ENABLED=0 to disable after the tournament (default on).
"""
import os, json, re
import urllib.request
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(IST)
SITE_URL = os.environ.get("SITE_URL", "https://thelast24.in").rstrip("/")
ENABLED = os.environ.get("WORLDCUP_ENABLED", "1").strip() not in ("0", "false", "")

DATA_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
WC_HUE = "#16876B"   # World Cup accent (football green, harmonised with site)

# Indian-relevant / marquee teams to surface first in "what to watch".
MARQUEE = {"Brazil", "Argentina", "France", "England", "Spain", "Portugal",
           "Germany", "Netherlands", "Morocco", "USA", "Mexico", "Croatia"}


def _fetch():
    req = urllib.request.Request(DATA_URL, headers={"User-Agent": "thelast24-bot"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _to_ist(date_str, time_str):
    """'2026-06-18' + '20:00 UTC-6' -> datetime in IST. Returns None on failure."""
    try:
        m = re.match(r"(\d{1,2}):(\d{2})\s*UTC([+-]\d{1,2})", time_str or "")
        if not m:
            return None
        hh, mm, off = int(m.group(1)), int(m.group(2)), int(m.group(3))
        base = datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=hh, minute=mm, tzinfo=timezone(timedelta(hours=off)))
        return base.astimezone(IST)
    except Exception:
        return None


def _compute_standings(matches):
    """Build group standings from played matches. Returns {group: [rows]} where
    each row has team, P, W, D, L, GF, GA, GD, Pts — sorted by Pts, GD, GF."""
    groups = {}
    for m in matches:
        grp = m.get("group")
        if not grp or not grp.startswith("Group"):
            continue
        t1, t2 = m.get("team1"), m.get("team2")
        g = groups.setdefault(grp, {})
        for t in (t1, t2):
            g.setdefault(t, {"team": t, "P": 0, "W": 0, "D": 0, "L": 0,
                             "GF": 0, "GA": 0, "GD": 0, "Pts": 0})
        score = m.get("score", {})
        ft = score.get("ft") if isinstance(score, dict) else None
        if not ft or len(ft) != 2:
            continue  # not played yet
        a, b = ft
        ra, rb = g[t1], g[t2]
        ra["P"] += 1; rb["P"] += 1
        ra["GF"] += a; ra["GA"] += b
        rb["GF"] += b; rb["GA"] += a
        if a > b:
            ra["W"] += 1; ra["Pts"] += 3; rb["L"] += 1
        elif b > a:
            rb["W"] += 1; rb["Pts"] += 3; ra["L"] += 1
        else:
            ra["D"] += 1; rb["D"] += 1; ra["Pts"] += 1; rb["Pts"] += 1
    out = {}
    for grp, teams in groups.items():
        rows = list(teams.values())
        for r in rows:
            r["GD"] = r["GF"] - r["GA"]
        rows.sort(key=lambda r: (-r["Pts"], -r["GD"], -r["GF"], r["team"]))
        out[grp] = rows
    return dict(sorted(out.items()))


def _matches_view(matches):
    """Split matches into recent results (last 2 days), today, and upcoming
    (next 3 days), each with IST kickoff and a readable score line."""
    recent, today, upcoming = [], [], []
    today_d = NOW.date()
    for m in matches:
        ist = _to_ist(m.get("date", ""), m.get("time", ""))
        score = m.get("score", {})
        ft = score.get("ft") if isinstance(score, dict) else None
        item = {
            "team1": m.get("team1", ""), "team2": m.get("team2", ""),
            "group": m.get("group", ""), "ground": m.get("ground", ""),
            "ist": ist.strftime("%d %b, %I:%M %p IST") if ist else "",
            "ist_date": ist.strftime("%Y-%m-%d") if ist else m.get("date", ""),
            "played": bool(ft),
            "score": f"{ft[0]}-{ft[1]}" if ft else "",
        }
        if ft:
            d = ist.date() if ist else None
            if d and (today_d - d).days <= 2 and d <= today_d:
                recent.append(item)
        else:
            d = ist.date() if ist else None
            if d == today_d:
                today.append(item)
            elif d and 0 < (d - today_d).days <= 3:
                upcoming.append(item)
    recent.sort(key=lambda x: x["ist_date"], reverse=True)
    upcoming.sort(key=lambda x: x["ist_date"])
    return recent[:8], today, upcoming[:8]


def build_worldcup(write_page=True):
    """Main entry: fetch, compute, write worldcup.js + worldcup.html.
    Returns the payload dict (also used by callers). No-op if disabled."""
    if not ENABLED:
        print("World Cup module disabled (WORLDCUP_ENABLED=0).")
        return None
    try:
        data = _fetch()
    except Exception as exc:
        print(f"World Cup fetch failed ({exc}); skipping (existing files kept).")
        return None
    matches = data.get("matches", [])
    standings = _compute_standings(matches)
    recent, today, upcoming = _matches_view(matches)

    payload = {
        "updated_label": NOW.strftime("%d %b %Y, %H:%M IST"),
        "standings": standings,
        "recent": recent,
        "today": today,
        "upcoming": upcoming,
    }
    with open("worldcup.js", "w", encoding="utf-8") as f:
        f.write("window.WORLDCUP = " + json.dumps(payload, ensure_ascii=False) + ";")

    if write_page:
        _write_page(payload)
    print(f"World Cup: {len(standings)} groups, {len(recent)} recent, "
          f"{len(today)} today, {len(upcoming)} upcoming.")
    return payload


def daily_scores_story():
    """A story dict for the Sports carousel: yesterday/today's World Cup results
    plus the next fixtures, in the site's story shape. Returns None if no data."""
    if not ENABLED:
        return None
    try:
        data = _fetch()
    except Exception:
        return None
    recent, today, upcoming = _matches_view(data.get("matches", []))
    if not (recent or today or upcoming):
        return None
    lines = []
    for r in recent[:4]:
        lines.append(f"{r['team1']} {r['score']} {r['team2']}")
    facts = lines[:4]
    nxt = (today + upcoming)[:3]
    next_line = "; ".join(f"{u['team1']} v {u['team2']} ({u['ist']})" for u in nxt)
    headline = "World Cup 2026: latest scores and what's next"
    article = ("The latest from the FIFA World Cup 2026. Recent results: "
               + "; ".join(lines[:4]) + ". ")
    if next_line:
        article += f"Coming up (IST): {next_line}."
    return {
        "headline": headline,
        "time": NOW.strftime("%H:%M IST"),
        "hour": NOW.hour,
        "what": "Latest World Cup scores and upcoming fixtures, in IST.",
        "lens": "Track every matchday in your time zone.",
        "article": article,
        "key_facts": facts,
        "source": "openfootball",
        "url": f"{SITE_URL}/worldcup.html",
        "breaking": False,
        "image_subject": "FIFA World Cup 2026",
        "image_query": "FIFA World Cup 2026 football",
        "worldcup": True,
    }


def standings_payload():
    """Structured standings for the Instagram story generator. {group:[rows]}."""
    if not ENABLED:
        return {}
    try:
        return _compute_standings(_fetch().get("matches", []))
    except Exception:
        return {}


# ---- the World Cup page (masthead injected by the caller in build_edition) ---
def _write_page(payload):
    # Imported here to reuse the site's shared masthead + hue + SITE_URL.
    try:
        import build_edition as be
        mhead = be.masthead_html([("Trending", "/trending.html", False),
                                  ("Current Affairs", "/current-affairs.html", False),
                                  ("Archive", "/archive.html", False),
                                  ("Home", "/", False)],
                                 date_label=NOW.strftime("%A, %d %B %Y"))
        mcss = be.masthead_css()
    except Exception:
        mhead, mcss = "", ""
    page = WORLDCUP_PAGE.replace("/*MASTHEAD_CSS*/", mcss) \
                        .replace("<!--MASTHEAD-->", mhead) \
                        .replace("WC_HUE", WC_HUE) \
                        .replace("SITE_URL_REPLACE", SITE_URL)
    with open("worldcup.html", "w", encoding="utf-8") as f:
        f.write(page)


WORLDCUP_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-3154853937012742" crossorigin="anonymous"></script>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FIFA World Cup 2026 — Scores, Standings & Fixtures (IST) | The Last 24</title>
<meta name="description" content="FIFA World Cup 2026 live group standings, latest scores and upcoming fixtures in IST for Indian fans. Track every group, updated through the day.">
<link rel="canonical" href="SITE_URL_REPLACE/worldcup.html">
<link rel="icon" href="favicon.ico">
<style>
:root{--paper:#F7F6F2;--card:#FFFFFF;--ink:#0F140F;--ink-soft:#454B43;--meta:#767B71;--hairline:#E9EAE3;--dark:#0C110C;--green:#0C6E49;--green-bright:#27B97C;--wc:WC_HUE;
--display:-apple-system,BlinkMacSystemFont,'SF Pro Display','Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;
--body:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;--mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;--mw:980px}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--paper);color:var(--ink);font-family:var(--body);line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:980px;margin:0 auto;padding:0 20px}
/*MASTHEAD_CSS*/
a{color:inherit}
.hero{padding:32px 0 10px}
.hero h1{font-family:var(--display);font-weight:800;font-size:clamp(28px,5vw,42px);line-height:1.04;letter-spacing:-.02em;margin:0 0 10px}
.hero h1 span{color:var(--wc)}
.hero p{font-size:16px;color:var(--meta);max-width:640px}
.updated{font-family:var(--mono);font-size:12px;color:var(--meta);margin-top:12px}
.updated b{color:var(--wc)}
.tabs{display:flex;gap:8px;margin:26px 0 8px;flex-wrap:wrap}
.tab{font-family:var(--mono);font-size:12px;letter-spacing:.04em;text-transform:uppercase;padding:8px 14px;border:1px solid var(--hairline);border-radius:999px;background:#fff;cursor:pointer;color:var(--ink-soft)}
.tab.active{background:var(--wc);color:#fff;border-color:var(--wc)}
.panel{display:none;padding:18px 0 60px}
.panel.show{display:block}
.section-title{font-family:var(--display);font-weight:800;font-size:18px;margin:22px 0 12px;letter-spacing:-.01em}
/* scores */
.match{display:grid;grid-template-columns:1fr 64px 130px;align-items:center;gap:14px;background:#fff;border:1px solid var(--hairline);border-radius:12px;padding:14px 16px;margin-bottom:9px}
.match .teams{display:flex;flex-direction:column;gap:4px;font-size:15px;font-weight:600;min-width:0}
.match .teams span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.match .vs{font-family:var(--mono);font-size:11px;color:var(--meta);font-weight:400}
.match .sc{font-family:var(--display);font-weight:800;font-size:22px;color:var(--wc);text-align:center}
.match .meta{font-family:var(--mono);font-size:11px;color:var(--meta);text-align:right;line-height:1.4}
.match.up .sc{color:var(--meta);font-size:13px;font-family:var(--mono);font-weight:600}
/* standings table */
.grp{margin-bottom:26px}
.grp h3{font-family:var(--display);font-weight:800;font-size:15px;letter-spacing:.06em;text-transform:uppercase;margin:0 0 8px;color:var(--ink)}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--hairline);border-radius:12px;overflow:hidden;font-size:14px}
th,td{padding:9px 8px;text-align:center}
th{font-family:var(--mono);font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--meta);background:#FAFAF8;font-weight:600}
td.tm,th.tm{text-align:left;font-weight:600}
tr:not(:last-child) td{border-bottom:1px solid var(--hairline)}
tr.qual td{background:rgba(22,135,107,.06)}
tr.qual td.pos{box-shadow:inset 3px 0 0 var(--wc)}
.pos{font-family:var(--mono);color:var(--meta);font-size:12px}
td.pts{font-weight:800;color:var(--wc)}
.empty{text-align:center;color:var(--meta);padding:50px 0;font-family:var(--mono);font-size:13px}
.note{font-family:var(--mono);font-size:11px;color:var(--meta);margin-top:8px}
footer{border-top:1px solid var(--hairline);padding:28px 0;font-family:var(--mono);font-size:12px;color:var(--meta);text-align:center}
@media(max-width:600px){.wrap{padding:0 14px}.match{grid-template-columns:1fr 50px 92px;gap:8px;padding:12px 13px}.match .teams{font-size:13.5px}.match .sc{font-size:19px}.match .meta{font-size:9.5px}th,td{padding:7px 5px;font-size:12.5px}}
</style>
</head>
<body>
<!--MASTHEAD-->
<div class="wrap hero">
  <h1>FIFA <span>World Cup</span> 2026</h1>
  <p>Group standings, latest scores and upcoming fixtures — all kickoff times in IST, for Indian fans tracking the tournament.</p>
  <div class="updated" id="updated"></div>
  <div class="tabs">
    <button class="tab active" data-tab="standings">Standings</button>
    <button class="tab" data-tab="scores">Scores</button>
    <button class="tab" data-tab="fixtures">Fixtures</button>
  </div>
</div>
<div class="wrap">
  <div class="panel show" id="standings"></div>
  <div class="panel" id="scores"></div>
  <div class="panel" id="fixtures"></div>
</div>
<footer><div class="wrap">World Cup data via openfootball (public domain) · Times in IST · <a href="/">The Last 24</a></div></footer>
<script src="worldcup.js"></script>
<script>
var W=window.WORLDCUP||{standings:{},recent:[],today:[],upcoming:[]};
function esc(s){return (s||'').replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
document.getElementById('updated').innerHTML=W.updated_label?'Updated <b>'+esc(W.updated_label)+'</b>':'';

// Standings
(function(){
  var box=document.getElementById('standings'); var g=W.standings||{};
  var keys=Object.keys(g);
  if(!keys.length){box.innerHTML='<div class="empty">Standings will appear once group matches are played.</div>';return;}
  box.innerHTML=keys.map(function(grp){
    var rows=g[grp]||[];
    var trs=rows.map(function(r,i){
      var q=i<2?' class="qual"':'';
      return '<tr'+q+'><td class="pos">'+(i+1)+'</td><td class="tm">'+esc(r.team)+'</td>'
        +'<td>'+r.P+'</td><td>'+r.W+'</td><td>'+r.D+'</td><td>'+r.L+'</td>'
        +'<td>'+r.GF+'</td><td>'+r.GA+'</td><td>'+(r.GD>0?'+':'')+r.GD+'</td><td class="pts">'+r.Pts+'</td></tr>';
    }).join('');
    return '<div class="grp"><h3>'+esc(grp)+'</h3><table>'
      +'<tr><th class="pos">#</th><th class="tm">Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th></tr>'
      +trs+'</table></div>';
  }).join('')+'<div class="note">Top two of each group (shaded) advance. GD = goal difference.</div>';
})();

// Scores (recent + today)
(function(){
  var box=document.getElementById('scores');
  var played=(W.today||[]).filter(function(m){return m.played;}).concat(W.recent||[]);
  if(!played.length){box.innerHTML='<div class="empty">No recent results yet — check back after the next matchday.</div>';return;}
  box.innerHTML='<div class="section-title">Latest results</div>'+played.map(function(m){
    return '<div class="match"><div class="teams"><span>'+esc(m.team1)+'</span><span>'+esc(m.team2)+'</span></div>'
      +'<div class="sc">'+esc(m.score)+'</div>'
      +'<div class="meta">'+esc(m.group)+'<br>'+esc(m.ground)+'</div></div>';
  }).join('');
})();

// Fixtures (today unplayed + upcoming)
(function(){
  var box=document.getElementById('fixtures');
  var up=(W.today||[]).filter(function(m){return !m.played;}).concat(W.upcoming||[]);
  if(!up.length){box.innerHTML='<div class="empty">No upcoming fixtures in the next few days.</div>';return;}
  box.innerHTML='<div class="section-title">Coming up (IST)</div>'+up.map(function(m){
    return '<div class="match up"><div class="teams"><span>'+esc(m.team1)+'</span><span class="vs">vs</span><span>'+esc(m.team2)+'</span></div>'
      +'<div class="sc">'+esc(m.ist.split(',')[1]||m.ist)+'</div>'
      +'<div class="meta">'+esc(m.group)+'<br>'+esc(m.ground)+'</div></div>';
  }).join('');
})();

// Tabs
document.querySelectorAll('.tab').forEach(function(t){
  t.addEventListener('click',function(){
    document.querySelectorAll('.tab').forEach(function(x){x.classList.remove('active');});
    document.querySelectorAll('.panel').forEach(function(x){x.classList.remove('show');});
    t.classList.add('active');
    document.getElementById(t.dataset.tab).classList.add('show');
  });
});
</script>
</body>
</html>"""


if __name__ == "__main__":
    build_worldcup()
