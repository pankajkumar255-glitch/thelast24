# The Last 24 — Automated Media House: Setup & Operations

A fully automated daily news brief for India across six categories — National,
World, Business & Markets, Technology, Sports, Entertainment. Publishes itself
every hour from verified publishers only, generates SEO article pages, captures newsletter signups with
preferences, and builds weekly preference-based digests. No servers, no
database. Running cost ≈ a few dollars/month of Claude API usage.

## What's in this folder

| File | What it is |
|---|---|
| `index.html` | Homepage — animated, category-coloured, renders from data.js. Includes email capture + 2 ad slots. |
| `data.js` | Current edition (sample placeholder until first auto-run). |
| `engine.html` / `ENGINE_PROMPT.md` | Manual fallback engine (paste headlines → edition + socials). |
| `scripts/build_edition.py` | The 3-hourly auto-publisher: RSS → Claude → data.js + article pages + sitemap + archive. |
| `scripts/build_newsletter.py` | Weekly: builds one ready-to-send HTML digest per preference category (deterministic — no AI, no hallucination risk). |
| `.github/workflows/daily-brief.yml` | Runs the publisher every 3 hours. |
| `.github/workflows/weekly-newsletter.yml` | Runs the digest builder every Sunday 8 AM IST. |
| `about.html`, `contact.html`, `privacy.html` | Trust pages (founder credit, corrections inbox, privacy policy) — required for AdSense/Search Console. Replace support@thelast24.in address before launch. |
| `robots.txt`, `llms.txt` | SEO + GEO (generative engine optimization) files. |
| `articles/`, `editions/`, `newsletter/`, `sitemap.xml` | Created automatically on first run. |

## One-time setup (≈30 minutes)

1. Push this entire folder (including hidden `.github/`) to a GitHub repo.
2. Get a Claude API key from console.anthropic.com.
   Repo → Settings → Secrets and variables → Actions → **New secret**:
   `ANTHROPIC_API_KEY` = your key.
3. Real photos on stories: get a free API key at pexels.com/api (2 minutes,
   no payment ever). Add it as a second secret: `PEXELS_API_KEY`. The pipeline
   fetches a commercially-licensed photo per story and credits the
   photographer; stories without a good match get generative art instead.
4. Same page → **Variables** tab → `SITE_URL` = your live URL.
   Also replace `https://thelast24.in` in index.html, robots.txt, llms.txt.
4. Enable hosting: Settings → Pages → deploy from main (or import to Vercel).
   Point your domain at it.
5. **Populate the site now:** Actions tab → "Publish edition" → Run workflow,
   and set `backfill_days` to `7`. In a few minutes the site fills with the
   past week's stories from verified publishers. Hourly runs take over from there.
6. Email capture: create a free Formspree form (or Buttondown/MailerLite),
   paste its endpoint into `NEWSLETTER_ENDPOINT` in index.html. Signups arrive
   with a `preferences` field (e.g. "business,sports") — create matching
   segments/tags in your email tool.
7. Submit `sitemap.xml` in Google Search Console (free) — this is what gets
   article pages indexed fast.

## How it runs (no people involved — almost)

- **Every hour**: fresh headlines are pulled from Google News RSS and filtered
  through a verified-publisher allowlist (PTI, Reuters, The Hindu, ET, Mint,
  ESPNcricinfo and ~30 more — edit TRUSTED_PUBLISHERS in the script). Claude
  writes the brief + a crisp structured summary per story (What happened / The
  context / Why it matters / What's next), each citing the publisher by name
  with a "Read the full story" link to the original source. Pages, sitemap and
  archive update automatically; the site redeploys itself.
- **Day-one pre-population**: run the "Publish edition" workflow manually once
  with `backfill_days = 7` — it pulls the past week's stories from trusted
  publishers so the site launches full, then hourly runs keep it fresh.
- **Every Sunday 8 AM IST**: the week's archive is curated into per-category
  digest emails in `/newsletter`. Send each to its matching preference segment
  (manual paste at first; wire your email provider's API later).
- **The "almost"**: spend 10 minutes a day spot-checking output. An automated
  news site lives or dies on never publishing a wrong fact. The prompts forbid
  invented details, but you are the editor of record.

## Revenue model (built in, activate when ready)

- **Ad slots**: 3 placeholders exist — homepage mid, homepage footer, and
  article mid. Each is marked `<!-- AD SLOT -->` in the code; paste an AdSense
  or ad-network snippet there. Reality check: AdSense approval needs an
  established site (typically 2–3+ months of consistent publishing, real
  traffic, About/Contact/Privacy pages — add those before applying).
- **Newsletter sponsorships**: the better early revenue. A sponsor line in the
  weekly digest sells on audience quality, not raw traffic.
- **Later**: category sponsorships ("Business brief presented by …"), affiliate
  slots in relevant categories.

## SEO / GEO checklist (already wired)

- Per-article pages with unique titles, meta descriptions, canonical URLs,
  OpenGraph tags, and NewsArticle JSON-LD structured data
- Auto-generated sitemap.xml, robots.txt, llms.txt (for AI engines)
- Fast static pages, mobile-first, accessible focus states, reduced-motion support
- Email capture is a slide-in, NOT a full-screen popup — Google penalizes
  intrusive interstitials on mobile
- Cookie consent banner included (newsletter prompt waits for the cookie choice
  so overlays never stack). Note: if you enable AdSense with EU/UK traffic,
  Google requires a certified consent platform — this banner covers launch and
  India-first traffic; upgrade when you go global
- Every article links its original source (`isBasedOn` in structured data) —
  this transparency is also your best defence as an aggregator

## Honest operating notes

- **Images**: stories use free commercially-licensed Pexels photos (credited)
  with generative art as fallback. Do NOT swap in publishers' news photos even
  with credit — attribution is not a license. Scraped press photos mean DMCA
  takedowns, AdSense rejection, and legal exposure for you as publisher.
- **Scaled AI content**: Google penalizes mass-produced thin content. Your
  protection: short grounded briefs (not fake 1500-word articles), original
  "why it matters" analysis, linked sources, and a real niche audience. If
  traffic is the goal, the newsletter and social distribution will matter far
  more than SEO in year one.
- **Costs**: 24 runs/day × one Claude call — still cheap (roughly $5–15/month
  depending on story volume). Keep the repo PUBLIC: GitHub Actions minutes are
  unlimited for public repos; a private repo's 2,000 free minutes/month would
  run out on an hourly schedule.
- Tune categories by editing `SECTION_QUERIES` in scripts/build_edition.py —
  new sections appear on the site automatically.
