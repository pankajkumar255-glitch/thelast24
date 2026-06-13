DEPLOY — from this folder to a live web app + mobile app, click by click
Total time: ~30 minutes. Cost: Rs 0 to start (plus ~Rs 800/yr for a domain when ready).
Part 1 — Put it on GitHub (5 min)
Create a free account at github.com (skip if you have one).
Top-right "+" → New repository → name it (e.g. `the-last-24`) → set Public
(important: public repos get unlimited free automation minutes) → Create.
On the new repo page → "uploading an existing file" → drag in EVERYTHING from
this folder, including the hidden `.github` folder (on Mac press Cmd+Shift+.
to see hidden files; on Windows enable "Hidden items" in Explorer View).
Commit changes.
Part 2 — Add the two free API keys (5 min)
console.anthropic.com → sign up → API Keys → Create key → copy it.
Repo → Settings → Secrets and variables → Actions → New repository secret
→ Name: `ANTHROPIC\_API\_KEY`, Value: the key → Add.
pexels.com/api → Get started (free, no card) → copy the key.
Same screen → New repository secret → Name: `PEXELS\_API\_KEY` → Add.
Switch to the Variables tab → New repository variable →
Name: `SITE\_URL`, Value: your site URL (you'll have it after Part 3 —
come back and fill this, then re-run the workflow once).
Part 3 — Turn on hosting (5 min)
Repo → Settings → Pages → Source: "Deploy from a branch" →
Branch: `main`, folder `/ (root)` → Save.
Wait ~1 minute, refresh: your live URL appears
(https://YOURNAME.github.io/the-last-24/). Open it — you'll see the launch
edition immediately.
Custom domain (optional now, recommended soon): buy one (GoDaddy/Namecheap/
Cloudflare, ~Rs 800/yr) → Pages → Custom domain → follow the DNS prompt.
Then update SITE_URL (Part 2.5) and the example.com references in
index.html, robots.txt, llms.txt, and the contact-page emails.
Part 4 — First pipeline run: backfill the past week (5 min)
Repo → Actions tab → enable workflows if prompted.
Click "Publish edition" → Run workflow → set `backfill\_days` = `7` → Run.
Watch it go green (~3-5 min). The site now has the past week's stories from
verified publishers, real photos, and per-story article pages.
From now on it runs itself every hour. Glance at the Actions tab tomorrow to
confirm the schedule is ticking.
Part 5 — Newsletter + Search (10 min, can be later)
formspree.io (free) → New form → copy the endpoint URL → paste it into
`NEWSLETTER\_ENDPOINT` in index.html (one line near the bottom) → commit.
Signups arrive with email + preferences (e.g. "business,sports").
search.google.com/search-console → add your domain → submit `sitemap.xml`.
The mobile app — what you have and what to do
You already have an installable app. This build is a PWA (Progressive Web
App): manifest, app icons, offline support via a service worker.
Android: visiting the site in Chrome shows an "Add to Home screen" /
install prompt → installs with your icon, opens full-screen like a native
app, and shows the last cached edition even offline.
iPhone: Safari → Share → "Add to Home Screen" → same result.
Put an "Install our app" line in the site footer or social bios — that's the
honest, zero-cost app strategy used by most modern news products.
Play Store / App Store later (only when traction justifies it):
Wrap this exact site with Capacitor or a Trusted Web Activity (Bubblewrap)
— no rewrite needed.
Costs/overhead: Google Play $25 one-time + review; Apple $99/year + stricter
review (Apple often rejects thin web wrappers, so add app-only value like
push notifications first).
The sensible trigger: build store apps when you have returning daily readers
asking for notifications — not before. Push notifications via a free tier of
OneSignal can be added to the PWA itself on Android even without the stores.
Daily reality check (the one human task)
Spend 10 minutes a day skimming the latest edition. The pipeline cites and
links verified publishers and is instructed never to invent facts — but you
are the editor of record, and the "verified" brand is only as good as its
worst published error.
Later: cleaner article URLs (optional upgrade)
GitHub Pages serves files with their `.html` extension (e.g.
`/articles/story.html`) — which is perfectly fine and harmless for launch. The
homepage already reads as a clean `thelast24.in` (no `index.html` needed).
If, once you have traffic, you want extensionless article URLs like
`thelast24.in/articles/story`, the clean way is to move hosting to Cloudflare
Pages or Netlify (both free), which support this natively:
Connect the same GitHub repo to Cloudflare Pages / Netlify (a few clicks).
Re-point thelast24.in's DNS to them instead of GitHub.
No code changes needed — they strip `.html` automatically.
Do this only when clean URLs genuinely matter to you; it is not a launch blocker.
