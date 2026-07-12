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
Toggle: set BRACKET_ENABLED=0 to drop the knockout bracket tab once the
tournament is over — it's a short-lived feature (roughly one week, through
the final) and this makes it a one-line switch to turn off later without
touching layout code.
"""
import os, json, re
import urllib.request
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(IST)
SITE_URL = os.environ.get("SITE_URL", "https://thelast24.in").rstrip("/")
ENABLED = os.environ.get("WORLDCUP_ENABLED", "1").strip() not in ("0", "false", "")
BRACKET_ENABLED = os.environ.get("BRACKET_ENABLED", "1").strip() not in ("0", "false", "")

DATA_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
WC_HUE = "#16876B"   # World Cup accent (football green, harmonised with site)

# Knockout rounds in bracket order. openfootball tags these matches with a
# "round" field (not "group"); the Semi-final/Final entries reference earlier
# matches by number as placeholder teams, e.g. "W97" (winner of match 97) or
# "L101" (loser of match 101) — resolved to real team names as each round
# completes (see _resolve_token / _compute_bracket below).
KNOCKOUT_ORDER = ["Round of 32", "Round of 16", "Quarter-final", "Semi-final", "Final"]
THIRD_PLACE_ROUND = "Match for third place"

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
        t1, t2 = m.get("team1", ""), m.get("team2", "")
        # Plain-language result: who beat whom, or a draw.
        result = ""
        if ft:
            try:
                g1, g2 = int(ft[0]), int(ft[1])
                if g1 > g2:
                    result = f"{t1} beat {t2} {g1}-{g2}"
                elif g2 > g1:
                    result = f"{t2} beat {t1} {g2}-{g1}"
                else:
                    result = f"{t1} drew with {t2} {g1}-{g1}"
            except (ValueError, TypeError):
                result = ""
        item = {
            "team1": t1, "team2": t2,
            "group": m.get("group", ""), "ground": m.get("ground", ""),
            "ist": ist.strftime("%d %b %Y, %I:%M %p IST") if ist else "",
            "ist_date": ist.strftime("%Y-%m-%d") if ist else m.get("date", ""),
            "ist_sort": ist.strftime("%Y-%m-%d %H:%M") if ist else (m.get("date", "") + " 00:00"),
            "date_label": ist.strftime("%a, %d %b %Y") if ist else m.get("date", ""),
            "played": bool(ft),
            "score": f"{ft[0]}-{ft[1]}" if ft else "",
            "result": result,
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
    # Sort results newest-first by full timestamp (date + time), so readers see
    # the most recent result first and can tell exactly when each happened.
    recent.sort(key=lambda x: x["ist_sort"], reverse=True)
    upcoming.sort(key=lambda x: x["ist_sort"])
    return recent[:8], today, upcoming[:8]


def _scorers_str(goals):
    """Compact scorer list for a bracket card, e.g. 'Havertz 54\\', Kane 75\\'/86\\''
    — groups repeated scorers, flags penalties/own goals. '' if no goals."""
    by_name, order = {}, []
    for g in goals or []:
        nm = (g.get("name") or "").strip()
        if not nm:
            continue
        mn = str(g.get("minute", "")).strip()
        tag = " (pen)" if g.get("penalty") else (" (og)" if g.get("owngoal") else "")
        mark = (f"{mn}'{tag}" if mn else tag.strip())
        by_name.setdefault(nm, [])
        if mark:
            by_name[nm].append(mark)
        if nm not in order:
            order.append(nm)
    return ", ".join(f"{nm} {'/'.join(by_name[nm])}".strip() for nm in order)


def _ko_result(m):
    """Winner/loser + score summary for a knockout match, accounting for
    extra time and penalties. Returns None if not played / not yet decided."""
    score = m.get("score", {}) or {}
    ft = score.get("ft")
    if not ft or len(ft) != 2:
        return None
    et, pk = score.get("et"), score.get("p")
    t1, t2 = m.get("team1"), m.get("team2")
    g1, g2 = ft
    f1, f2 = (et[0], et[1]) if et else (g1, g2)
    if pk and len(pk) == 2:
        winner, loser = (t1, t2) if pk[0] > pk[1] else (t2, t1)
    elif f1 > f2:
        winner, loser = t1, t2
    elif f2 > f1:
        winner, loser = t2, t1
    else:
        return None  # shouldn't happen in a knockout match without penalties
    return {
        "winner": winner, "loser": loser,
        "score": f"{g1}-{g2}",
        "et": f"{et[0]}-{et[1]} AET" if et and len(et) == 2 else "",
        "pens": f"{pk[0]}-{pk[1]} on pens" if pk and len(pk) == 2 else "",
    }


def _is_placeholder_name(s):
    """True for an unresolved token ('W97') or an already-composed but still
    undecided label ('Winner: Spain v Belgium') — i.e. not a real team name."""
    s = str(s or "")
    return bool(re.match(r"^[WL]\d+$", s)) or s.startswith(("Winner:", "Loser:", "Winner of", "Loser of"))


def _round_label(src, by_num):
    """'Semi-final 1' / 'Semi-final 2' when a round has multiple matches,
    else just the round name — used as a stable fallback placeholder when
    we can't show real team names without nesting two rounds deep."""
    rname = src.get("round", "that match")
    siblings = sorted(n for n, mm in by_num.items() if mm.get("round") == rname)
    if len(siblings) > 1:
        return f"{rname} {siblings.index(src['num']) + 1}"
    return rname


def _resolve_token(token, by_num):
    """'W97' -> real team name once match 97 is decided. If undecided, use
    that match's own team names IF they're already real ('Winner: Spain v
    Belgium'); if those are themselves still placeholders (two rounds deep,
    e.g. the Final referencing an undecided Semi-final), fall back to a
    round label ('Winner of Semi-final 1') instead of compounding a nested
    'Winner: Winner: A v B v C' string. Real team names pass through
    unchanged."""
    if not token or not re.match(r"^[WL]\d+$", str(token)):
        return token
    kind, num = token[0], int(token[1:])
    src = by_num.get(num)
    if not src:
        return token
    res = _ko_result(src)
    if res:
        return res["winner"] if kind == "W" else res["loser"]
    label = "Winner" if kind == "W" else "Loser"
    t1, t2 = src.get("team1"), src.get("team2")
    if t1 and t2 and not _is_placeholder_name(t1) and not _is_placeholder_name(t2):
        return f"{label}: {t1} v {t2}"
    return f"{label} of {_round_label(src, by_num)}"


def _compute_bracket(matches):
    """Single-elimination bracket: Round of 32 -> ... -> Final, with the
    third-place match alongside. Returns {rounds:[{name, matches:[...]}],
    third_place: {...} | None}, or None if there's no knockout data yet.
    Placeholder teams like 'W97'/'L101' are resolved to real team names (or a
    friendly 'Winner: A v B' label) round by round, since later rounds can
    only be resolved once the rounds that feed them are."""
    by_num = {m["num"]: dict(m) for m in matches if m.get("round") and m.get("num") is not None}
    if not by_num:
        return None
    by_round = {}
    for num in sorted(by_num):
        m = by_num[num]
        by_round.setdefault(m.get("round"), []).append(m)

    def build_card(m):
        # Patch team1/team2 in place with resolved names so later rounds
        # (which reference this match's winner/loser) see real names too.
        t1 = _resolve_token(m.get("team1"), by_num)
        t2 = _resolve_token(m.get("team2"), by_num)
        m["team1"], m["team2"] = t1, t2
        ist = _to_ist(m.get("date", ""), m.get("time", ""))
        result = _ko_result(m)
        return {
            "num": m["num"], "team1": t1, "team2": t2,
            "ground": m.get("ground", ""),
            "ist": ist.strftime("%d %b, %I:%M %p IST") if ist else "",
            "ist_sort": ist.strftime("%Y-%m-%d %H:%M") if ist else "",
            "played": bool(result),
            "winner": result["winner"] if result else "",
            "score": result["score"] if result else "",
            "et": result["et"] if result else "",
            "pens": result["pens"] if result else "",
            "scorers1": _scorers_str(m.get("goals1")),
            "scorers2": _scorers_str(m.get("goals2")),
        }

    rounds = []
    for rname in KNOCKOUT_ORDER:
        ms = by_round.get(rname, [])
        if not ms:
            continue
        rounds.append({"name": rname,
                        "matches": [build_card(m) for m in sorted(ms, key=lambda x: x["num"])]})
    if not rounds:
        return None

    third_ms = by_round.get(THIRD_PLACE_ROUND, [])
    third = build_card(third_ms[0]) if third_ms else None
    return {"rounds": rounds, "third_place": third}


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

    bracket = None
    if BRACKET_ENABLED:
        try:
            bracket = _compute_bracket(matches)
        except Exception as exc:
            print(f"Knockout bracket build failed ({exc}); omitting bracket tab.")

    payload = {
        "updated_label": NOW.strftime("%d %b %Y, %H:%M IST"),
        "standings": standings,
        "recent": recent,
        "today": today,
        "upcoming": upcoming,
        "bracket": bracket,
    }
    with open("worldcup.js", "w", encoding="utf-8") as f:
        f.write("window.WORLDCUP = " + json.dumps(payload, ensure_ascii=False) + ";")

    if write_page:
        _write_page(payload)
    br_note = f", bracket: {len(bracket['rounds'])} rounds" if bracket else ""
    print(f"World Cup: {len(standings)} groups, {len(recent)} recent, "
          f"{len(today)} today, {len(upcoming)} upcoming{br_note}.")
    return payload


def _match_report_line(m):
    """Build a detailed one-match report paragraph: scoreline, goalscorers with
    minutes, half-time score and venue."""
    score = m.get("score", {})
    ft = score.get("ft") if isinstance(score, dict) else None
    ht = score.get("ht") if isinstance(score, dict) else None
    sc = f"{ft[0]}-{ft[1]}" if ft and len(ft) == 2 else "v"
    line = f"{m['team1']} {sc} {m['team2']}"
    grp = m.get("group", "")
    if grp:
        line += f" ({grp})"
    scorers = []
    for who, glist in ((m['team1'], m.get('goals1') or []),
                       (m['team2'], m.get('goals2') or [])):
        for g in glist:
            nm = g.get("name", "").strip()
            mn = g.get("minute", "")
            if nm:
                scorers.append(f"{nm} {mn}'" if mn else nm)
    detail = []
    if scorers:
        detail.append("Scorers: " + ", ".join(scorers) + ".")
    if ht and len(ht) == 2:
        detail.append(f"Half-time: {ht[0]}-{ht[1]}.")
    if m.get("ground"):
        detail.append(f"Venue: {m['ground']}.")
    if detail:
        line += ". " + " ".join(detail)
    return line


def daily_scores_story():
    """A richly detailed story dict for the Sports carousel: a proper match report
    of recent World Cup results (with goalscorers) plus upcoming fixtures, well
    paragraphed. Returns None if no data."""
    if not ENABLED:
        return None
    try:
        data = _fetch()
    except Exception:
        return None
    matches = data.get("matches", [])
    # attach raw goal data to the recent view by matching teams+date
    recent, today, upcoming = _matches_view(matches)
    # build a lookup so we can enrich recent items with goals
    raw_by_key = {(m.get("team1"), m.get("team2"), m.get("date")): m for m in matches}
    if not (recent or today or upcoming):
        return None

    # Detailed per-match report lines (with scorers) for the key facts + article.
    detailed = []
    for r in recent[:5]:
        raw = raw_by_key.get((r["team1"], r["team2"], r.get("ist_date")))
        if not raw:
            # fall back: find by teams only
            raw = next((m for m in matches if m.get("team1") == r["team1"]
                        and m.get("team2") == r["team2"] and m.get("score")), None)
        detailed.append(_match_report_line(raw) if raw else
                        f"{r['team1']} {r['score']} {r['team2']}")

    facts = [f"{r['team1']} {r['score']} {r['team2']}" for r in recent[:4]]

    # Well-paragraphed editorial article — each match is its OWN paragraph.
    paras = []
    if detailed:
        paras.append("The FIFA World Cup 2026 group stage continued with another "
                     "full matchday. Here are the latest results in full:")
        # Each match report as a separate paragraph (blank-line separated).
        paras.extend(detailed)
    nxt = (today + upcoming)[:4]
    if nxt:
        paras.append("Coming up next (all times IST):")
        for u in nxt:
            paras.append(f"{u['team1']} v {u['team2']} — {u['ist']}"
                         + (f" ({u['group']})" if u.get("group") else ""))
    paras.append("Full group standings, scorers and the complete fixture list are "
                 "on our FIFA World Cup 2026 page, updated through the day.")
    article = "\n\n".join(paras)

    headline = "FIFA World Cup 2026: latest scores and full results"
    return {
        "headline": headline,
        "time": NOW.strftime("%H:%M IST"),
        "hour": NOW.hour,
        "what": ("The latest FIFA World Cup 2026 results in full — scorelines, "
                 "goalscorers and what's coming up next, all in IST."),
        "lens": "Every matchday, tracked in your time zone.",
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
/* knockout bracket — flowchart of rounds, left to right */
.bracket{display:flex;gap:22px;overflow-x:auto;padding:8px 2px 20px;-webkit-overflow-scrolling:touch}
.b-round{flex:0 0 220px;min-width:200px}
.b-round h4{font-family:var(--mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--wc);margin:0 0 10px;text-align:center}
.b-round.b-third h4{color:var(--meta)}
.b-col{display:flex;flex-direction:column;justify-content:space-around;height:100%}
.b-match{background:#fff;border:1px solid var(--hairline);border-radius:12px;padding:12px 14px;margin:7px 0;position:relative}
.b-match.b-played{border-color:rgba(22,135,107,.35)}
.b-round:not(:last-child):not(.b-third) .b-match::after{content:"";position:absolute;top:50%;right:-22px;width:20px;height:1px;background:var(--hairline)}
.b-team{display:flex;justify-content:space-between;align-items:baseline;gap:8px;font-size:13.5px;font-weight:600;padding:3px 0;color:var(--ink-soft)}
.b-team.b-win{color:var(--ink);font-weight:800}
.b-team.b-win .b-tm::before{content:'●';color:var(--wc);font-size:7px;margin-right:6px;vertical-align:middle}
.b-team .b-tm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.b-team .b-sr{font-family:var(--mono);font-size:9px;color:var(--meta);text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:104px}
.b-sc{text-align:center;font-family:var(--display);font-weight:800;font-size:16px;color:var(--wc);padding:3px 0;border-top:1px dashed var(--hairline);border-bottom:1px dashed var(--hairline);margin:5px 0}
.b-sc.b-tbd{font-family:var(--mono);font-weight:600;font-size:10px;color:var(--meta);letter-spacing:.03em;text-transform:none}
.b-et,.b-pen{display:block;font-family:var(--mono);font-size:9px;color:var(--meta);font-weight:500;margin-top:1px}
.b-meta{font-family:var(--mono);font-size:9.5px;color:var(--meta);text-align:center;margin-top:5px}
.b-round.b-final .b-match{border-color:var(--wc);box-shadow:0 4px 14px rgba(22,135,107,.12)}
@media(max-width:600px){.b-round{flex:0 0 172px;min-width:158px}.b-team{font-size:12px}.b-team .b-sr{max-width:76px}}
.panel{display:none;padding:18px 0 60px}
.panel.show{display:block}
.section-title{font-family:var(--display);font-weight:800;font-size:18px;margin:22px 0 12px;letter-spacing:-.01em}
/* scores */
.date-head{font-family:var(--mono);font-size:12px;font-weight:700;color:var(--wc);text-transform:uppercase;letter-spacing:.04em;margin:18px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--hairline)}
.date-head:first-child{margin-top:4px}
.match .result{font-family:var(--display);font-weight:700;font-size:12px;color:var(--ink);margin-bottom:3px}
.match .when{color:var(--meta)}
.match{display:grid;grid-template-columns:1fr 64px 150px;align-items:center;gap:14px;background:#fff;border:1px solid var(--hairline);border-radius:12px;padding:14px 16px;margin-bottom:9px}
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
    <button class="tab active" data-tab="bracket">Knockout</button>
    <button class="tab" data-tab="standings">Standings</button>
    <button class="tab" data-tab="scores">Scores</button>
    <button class="tab" data-tab="fixtures">Fixtures</button>
  </div>
</div>
<div class="wrap">
  <div class="panel show" id="bracket"></div>
  <div class="panel" id="standings"></div>
  <div class="panel" id="scores"></div>
  <div class="panel" id="fixtures"></div>
</div>
<footer><div class="wrap">FIFA World Cup 2026 data via openfootball (public domain) · Times in IST · <a href="/">The Last 24</a><br><span class="f-social"><a href="https://www.linkedin.com/company/the-last-24/" target="_blank" rel="noopener">LinkedIn</a> · <a href="https://www.instagram.com/thelast24in/" target="_blank" rel="noopener">Instagram</a> · <a href="https://x.com/Thelast24IN" target="_blank" rel="noopener">X</a></span></div></footer>
<script src="worldcup.js"></script>
<script>
var W=window.WORLDCUP||{standings:{},recent:[],today:[],upcoming:[]};
function esc(s){return (s||'').replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
document.getElementById('updated').innerHTML=W.updated_label?'Updated <b>'+esc(W.updated_label)+'</b>':'';

// Knockout bracket — flowchart of rounds with winners, scores, goal scorers
(function(){
  var box=document.getElementById('bracket'); var B=W.bracket;
  if(!box) return;
  if(!B || !B.rounds || !B.rounds.length){
    box.innerHTML='<div class="empty">The knockout bracket will appear once Round of 32 fixtures are set.</div>';
    return;
  }
  function card(m){
    var w1=m.played && m.winner===m.team1, w2=m.played && m.winner===m.team2;
    var sc=m.played
      ? '<div class="b-sc">'+esc(m.score)+(m.et?'<span class="b-et">'+esc(m.et)+'</span>':'')+(m.pens?'<span class="b-pen">'+esc(m.pens)+'</span>':'')+'</div>'
      : '<div class="b-sc b-tbd">'+esc(m.ist?m.ist.split(',')[0]:'TBD')+'</div>';
    return '<div class="b-match'+(m.played?' b-played':'')+'">'
      +'<div class="b-team'+(w1?' b-win':'')+'"><span class="b-tm">'+esc(m.team1)+'</span>'+(m.scorers1?'<span class="b-sr">'+esc(m.scorers1)+'</span>':'')+'</div>'
      +sc
      +'<div class="b-team'+(w2?' b-win':'')+'"><span class="b-tm">'+esc(m.team2)+'</span>'+(m.scorers2?'<span class="b-sr">'+esc(m.scorers2)+'</span>':'')+'</div>'
      +(m.ground?'<div class="b-meta">'+esc(m.ground)+'</div>':'')
      +'</div>';
  }
  var maxCount=B.rounds[0].matches.length;
  var html='<div class="bracket">'+B.rounds.map(function(r,i){
    var isFinal=(i===B.rounds.length-1);
    return '<div class="b-round'+(isFinal?' b-final':'')+'"><h4>'+esc(r.name)+'</h4>'
      +'<div class="b-col" style="min-height:'+(maxCount*88)+'px">'+r.matches.map(card).join('')+'</div></div>';
  }).join('');
  if(B.third_place){
    html+='<div class="b-round b-third"><h4>3rd place</h4><div class="b-col">'+card(B.third_place)+'</div></div>';
  }
  html+='</div>';
  box.innerHTML=html+'<div class="note">Placeholder match-ups (e.g. "Winner: Team A v Team B") update automatically once the earlier round is decided. Times shown are kickoff, IST.</div>';
})();

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

// Scores (recent + today) — grouped by date, newest first, with who beat whom
(function(){
  var box=document.getElementById('scores');
  var played=(W.today||[]).filter(function(m){return m.played;}).concat(W.recent||[]);
  if(!played.length){box.innerHTML='<div class="empty">No recent results yet — check back after the next matchday.</div>';return;}
  // sort newest first by full timestamp
  played.sort(function(a,b){return (b.ist_sort||'').localeCompare(a.ist_sort||'');});
  // group by date label
  var groups=[], byDate={};
  played.forEach(function(m){
    var d=m.date_label||'';
    if(!byDate[d]){byDate[d]=[]; groups.push(d);}
    byDate[d].push(m);
  });
  box.innerHTML='<div class="section-title">Latest results</div>'+groups.map(function(d){
    return '<div class="date-head">'+esc(d)+'</div>'+byDate[d].map(function(m){
      var res=m.result?('<div class="result">'+esc(m.result)+'</div>'):'';
      return '<div class="match"><div class="teams"><span>'+esc(m.team1)+'</span><span>'+esc(m.team2)+'</span></div>'
        +'<div class="sc">'+esc(m.score)+'</div>'
        +'<div class="meta">'+res+'<span class="when">'+esc(m.ist)+'</span><br>'+esc(m.group)+' · '+esc(m.ground)+'</div></div>';
    }).join('');
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
