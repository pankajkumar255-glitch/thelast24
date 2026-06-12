# DEPLOY — from this folder to a live web app + mobile app, click by click

Total time: ~30 minutes. Cost: Rs 0 to start (plus ~Rs 800/yr for a domain when ready).

## Part 1 — Put it on GitHub (5 min)

1. Create a free account at github.com (skip if you have one).
2. Top-right "+" → **New repository** → name it (e.g. `the-last-24`) → set **Public**
   (important: public repos get unlimited free automation minutes) → Create.
3. On the new repo page → "uploading an existing file" → drag in EVERYTHING from
   this folder, including the hidden `.github` folder (on Mac press Cmd+Shift+.
   to see hidden files; on Windows enable "Hidden items" in Explorer View).
4. Commit changes.

## Part 2 — Add the two free API keys (5 min)

1. console.anthropic.com → sign up → API Keys → Create key → copy it.
2. Repo → Settings → Secrets and variables → Actions → **New repository secret**
   → Name: `ANTHROPIC_API_KEY`, Value: the key → Add.
3. pexels.com/api → Get started (free, no card) → copy the key.
4. Same screen → New repository secret → Name: `PEXELS_API_KEY` → Add.
5. Switch to the **Variables** tab → New repository variable →
   Name: `SITE_URL`, Value: your site URL (you'll have it after Part 3 —
   come back and fill this, then re-run the workflow once).

## Part 3 — Turn on hosting (5 min)

1. Repo → Settings → **Pages** → Source: "Deploy from a branch" →
   Branch: `main`, folder `/ (root)` → Save.
2. Wait ~1 minute, refresh: your live URL appears
   (https://YOURNAME.github.io/the-last-24/). Open it — you'll see the launch
   edition immediately.
3. Custom domain (optional now, recommended soon): buy one (GoDaddy/Namecheap/
   Cloudflare, ~Rs 800/yr) → Pages → Custom domain → follow the DNS prompt.
   Then update SITE_URL (Part 2.5) and the example.com references in
   index.html, robots.txt, llms.txt, and the contact-page emails.

## Part 4 — First pipeline run: backfill the past week (5 min)

1. Repo → **Actions** tab → enable workflows if prompted.
2. Click "Publish edition" → **Run workflow** → set `backfill_days` = `7` → Run.
3. Watch it go green (~3-5 min). The site now has the past week's stories from
   verified publishers, real photos, and per-story article pages.
4. From now on it runs itself every hour. Glance at the Actions tab tomorrow to
   confirm the schedule is ticking.

## Part 5 — Newsletter + Search (10 min, can be later)

1. formspree.io (free) → New form → copy the endpoint URL → paste it into
   `NEWSLETTER_ENDPOINT` in index.html (one line near the bottom) → commit.
   Signups arrive with email + preferences (e.g. "business,sports").
2. search.google.com/search-console → add your domain → submit `sitemap.xml`.

## The mobile app — what you have and what to do

**You already have an installable app.** This build is a PWA (Progressive Web
App): manifest, app icons, offline support via a service worker.

- **Android**: visiting the site in Chrome shows an "Add to Home screen" /
  install prompt → installs with your icon, opens full-screen like a native
  app, and shows the last cached edition even offline.
- **iPhone**: Safari → Share → "Add to Home Screen" → same result.
- Put an "Install our app" line in the site footer or social bios — that's the
  honest, zero-cost app strategy used by most modern news products.

**Play Store / App Store later (only when traction justifies it):**
- Wrap this exact site with **Capacitor** or a Trusted Web Activity (Bubblewrap)
  — no rewrite needed.
- Costs/overhead: Google Play $25 one-time + review; Apple $99/year + stricter
  review (Apple often rejects thin web wrappers, so add app-only value like
  push notifications first).
- The sensible trigger: build store apps when you have returning daily readers
  asking for notifications — not before. Push notifications via a free tier of
  OneSignal can be added to the PWA itself on Android even without the stores.

## Daily reality check (the one human task)

Spend 10 minutes a day skimming the latest edition. The pipeline cites and
links verified publishers and is instructed never to invent facts — but you
are the editor of record, and the "verified" brand is only as good as its
worst published error.
