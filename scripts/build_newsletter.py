#!/usr/bin/env python3
"""
The Last 24 — weekly preference-based newsletter builder.

Runs every Sunday via GitHub Actions. Deterministic (no AI call, no
hallucination risk): it curates from the week's already-published editions.

Outputs one ready-to-send HTML email per category + one "everything" digest
into /newsletter. Connect to your email service in one of two ways:
  A) Manual (start here): paste the HTML into Beehiiv/Buttondown/MailerLite
     and send to the matching preference segment.
  B) API: add a send step using your provider's API once volumes justify it.
"""

import os, json, glob, html
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(IST)
WEEK_AGO = NOW - timedelta(days=7)
SITE_URL = os.environ.get("SITE_URL", "https://thelast24.in").rstrip("/")
HUES = {"national":"#0E7B52","world":"#1F5FA8","business":"#B07A1F",
        "tech":"#6A3FB5","sports":"#CE3D1D","entertainment":"#C2317E"}

def load_week():
    """Collect the week's stories per category, deduped, breaking-first."""
    cats = {}
    for path in sorted(glob.glob("editions/*.json")):
        stamp = os.path.basename(path)[:13]  # YYYY-MM-DD-HH
        try:
            when = datetime.strptime(stamp, "%Y-%m-%d-%H").replace(tzinfo=IST)
        except ValueError:
            continue
        if when < WEEK_AGO: continue
        with open(path, encoding="utf-8") as f:
            ed = json.load(f)
        for sec in ed.get("sections", []):
            bucket = cats.setdefault(sec["id"], {"name": sec["name"], "stories": {}})
            for st in sec.get("stories", []):
                key = st.get("slug") or st["headline"]
                if key not in bucket["stories"]:
                    bucket["stories"][key] = st
    for c in cats.values():
        ranked = sorted(c["stories"].values(), key=lambda s: (not s.get("breaking", False),))
        c["top"] = ranked[:6]
    return cats

def email_html(title, intro, blocks):
    e = html.escape
    items = ""
    for hue, st in blocks:
        link = f"{SITE_URL}/articles/{st['slug']}.html" if st.get("slug") else st.get("url", SITE_URL)
        items += f"""
        <div style="padding:18px 0;border-top:1px solid #E2E5DF">
          <p style="margin:0 0 6px;font-size:12px;color:#70756D;font-family:monospace">{e(st.get('time',''))}</p>
          <h3 style="margin:0 0 8px;font-size:19px;line-height:1.25;font-family:Georgia,serif">
            <a href="{link}" style="color:#171B17;text-decoration:none">{e(st['headline'])}</a></h3>
          <p style="margin:0 0 10px;font-size:15px;color:#3C423C;line-height:1.5">{e(st['what'])}</p>
          <p style="margin:0;font-size:14px;color:{hue};border-left:3px solid {hue};padding-left:10px;line-height:1.5">→ {e(st['lens'])}</p>
        </div>"""
    return f"""<!DOCTYPE html><html><body style="margin:0;background:#F6F7F4;padding:24px 12px">
<div style="max-width:580px;margin:0 auto;background:#fff;border-radius:14px;padding:28px;font-family:Georgia,serif">
  <p style="margin:0;font-size:11px;letter-spacing:2px;color:#70756D;font-family:monospace">THE LAST 24 — WEEKLY</p>
  <h1 style="margin:8px 0 4px;font-size:28px;color:#171B17">{e(title)}</h1>
  <p style="margin:0 0 18px;font-size:14px;color:#70756D">{e(intro)}</p>
  {items}
  <p style="margin-top:24px;padding-top:16px;border-top:2px solid #171B17;font-size:11px;color:#70756D;font-family:monospace;line-height:1.7">
    You chose these topics when you signed up. Every story links to the original reporting.<br>
    <a href="{SITE_URL}" style="color:#0E7B52">Read today's brief</a> · Reply to update preferences or unsubscribe.</p>
</div></body></html>"""

def main():
    cats = load_week()
    if not cats:
        print("No editions in the last 7 days — nothing to send."); return
    os.makedirs("newsletter", exist_ok=True)
    week = NOW.strftime("%Y-W%W")
    # per-preference digests
    for cid, c in cats.items():
        if not c["top"]: continue
        hue = HUES.get(cid, "#0E7B52")
        out = email_html(f"This week in {c['name']}",
                         f"The {len(c['top'])} stories that mattered, {WEEK_AGO.strftime('%d %b')}–{NOW.strftime('%d %b')}.",
                         [(hue, st) for st in c["top"]])
        with open(f"newsletter/{week}-{cid}.html", "w", encoding="utf-8") as f: f.write(out)
    # master digest (top 2 per category) for subscribers who picked everything
    blocks = [(HUES.get(cid, "#0E7B52"), st) for cid, c in cats.items() for st in c["top"][:2]]
    with open(f"newsletter/{week}-all.html", "w", encoding="utf-8") as f:
        f.write(email_html("The week, in one read",
                           f"Across every category, {WEEK_AGO.strftime('%d %b')}–{NOW.strftime('%d %b')}.", blocks))
    print(f"Wrote {len(cats)+1} newsletter files for {week}.")

if __name__ == "__main__":
    main()
