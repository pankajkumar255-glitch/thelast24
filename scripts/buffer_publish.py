#!/usr/bin/env python3
"""
The Last 24 — Buffer publisher.

Pushes content into your Buffer queue via Buffer's GraphQL API, so Buffer posts
it to X/Twitter and Instagram for you. No n8n required. Buffer is an approved
X partner, so this sidesteps the X OAuth / pay-per-use issues, and posts to
Instagram Professional accounts automatically.

It reads the SAME files the pipeline already produces:
  - tweets/queue.json          -> pending tweets  -> Buffer (X channel)
  - social/instagram/<date>/manifest.json -> carousels -> Buffer (Instagram channel)

Posts already sent are tracked in:
  - tweets/posted.json         (so tweets are never double-posted)
  - social/instagram/<date>/buffer-posted.json

ENV (set as GitHub repo secrets/vars):
  BUFFER_API_KEY        required — personal key from Buffer Settings -> API
  BUFFER_X_CHANNEL_ID   required for tweets — your X channel id in Buffer
  BUFFER_IG_CHANNEL_ID  required for carousels — your Instagram channel id
  SITE_URL              your site (default https://thelast24.in) — to build
                        public image URLs for Instagram slides
  BUFFER_SCHEDULE       optional: "queue" (default, add to Buffer's queue) or
                        "now" (publish immediately)

Run after the edition + social builds:
  python scripts/buffer_publish.py
"""
import os, json, glob, time
import urllib.request
import urllib.error

BUFFER_API = "https://api.buffer.com"
API_KEY = os.environ.get("BUFFER_API_KEY", "").strip()
X_CHANNEL = os.environ.get("BUFFER_X_CHANNEL_ID", "").strip()
IG_CHANNEL = os.environ.get("BUFFER_IG_CHANNEL_ID", "").strip()
LINKEDIN_CHANNEL = os.environ.get("BUFFER_LINKEDIN_CHANNEL_ID", "").strip()
# LinkedIn = professional audience: only these sections make sense there.
LINKEDIN_SECTIONS = ["ai", "tech", "world"]
SITE_URL = os.environ.get("SITE_URL", "https://thelast24.in").rstrip("/")
SCHEDULE = os.environ.get("BUFFER_SCHEDULE", "queue").strip().lower()


def _gql(query, variables=None):
    """Minimal GraphQL POST to Buffer with the personal API key as a bearer."""
    if not API_KEY:
        raise RuntimeError("BUFFER_API_KEY is not set.")
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib.request.Request(
        BUFFER_API, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {API_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise RuntimeError(f"Buffer HTTP {e.code}: {detail}")
    if data.get("errors"):
        raise RuntimeError(f"Buffer GraphQL error: {data['errors']}")
    return data.get("data", {})


# createPost mutation. mode=addToQueue puts it in your Buffer queue; for
# immediate posting we use customScheduled with a near-now time isn't needed —
# Buffer supports an immediate mode via mode=share on some plans; addToQueue is
# the safe universal default.
def _morning_slot(index):
    """ISO timestamp for the Nth post: starting at BUFFER_MORNING_START IST
    (default 08:00) the next morning, spaced BUFFER_SPACING_MIN apart (default
    60 min), so posts drip out like a morning brief."""
    from datetime import datetime, timedelta, timezone
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    start_hour = int(os.environ.get("BUFFER_MORNING_START", "8"))
    spacing = int(os.environ.get("BUFFER_SPACING_MIN", "60"))
    base = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    if base <= now:
        base = base + timedelta(days=1)
    slot = base + timedelta(minutes=spacing * index)
    return slot.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


_CREATE = """
mutation Create($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id } }
    ... on MutationError { message }
  }
}
"""


def _create_post(channel_id, text, image_urls=None, instagram=False, slot_index=0,
                 document_url=None, document_title=None, document_thumbnail=None):
    """Create one Buffer post. image_urls: list of public image URLs (carousel).
    document_url: a public PDF URL (LinkedIn document/carousel post) — requires
    document_title and document_thumbnail. instagram=True attaches the required
    Instagram metadata. slot_index spaces morning-scheduled posts 1 hour apart."""
    inp = {
        "text": text,
        "channelId": channel_id,
    }
    if SCHEDULE == "now":
        inp["schedulingType"] = "automatic"
        inp["mode"] = "share"
    elif SCHEDULE == "morning":
        inp["schedulingType"] = "customScheduled"
        inp["dueAt"] = _morning_slot(slot_index)
    else:
        inp["schedulingType"] = "automatic"
        inp["mode"] = "addToQueue"
    if document_url:
        # Buffer AssetInput for a PDF document — title + thumbnailUrl are REQUIRED.
        inp["assets"] = [{"document": {
            "url": document_url,
            "title": document_title or "The Last 24",
            "thumbnailUrl": document_thumbnail or "",
        }}]
    elif image_urls:
        # Buffer's AssetInput: each entry specifies one of image/video/document/link.
        # For images: {"image": {"url": "..."}} — NOT {"type","url"}.
        inp["assets"] = [{"image": {"url": u}} for u in image_urls]
    if instagram:
        # Instagram requires a post type. A multi-image carousel is a feed "post";
        # a single vertical image can be published as a "story" (media only —
        # Buffer/Instagram API can't auto-add tappable link stickers).
        ig_type = "story" if instagram == "story" else "post"
        if ig_type == "story":
            inp["metadata"] = {"instagram": {"type": "story"}}
        else:
            inp["metadata"] = {"instagram": {"type": "post", "shouldShareToFeed": True}}
    data = _gql(_CREATE, {"input": inp})
    res = data.get("createPost", {})
    if res.get("message"):
        raise RuntimeError(f"createPost rejected: {res['message']}")
    return (res.get("post") or {}).get("id")


# ----------------------------------------------------------------- tweets ---
def _section_cover_urls():
    """Map section name -> public URL of its Instagram cover slide (slide-01),
    used as a ready-made branded image for tweets that lack their own photo."""
    out = {}
    manifests = sorted(glob.glob("social/instagram/*/manifest.json"))
    if not manifests:
        return out
    try:
        manifest = json.load(open(manifests[-1], encoding="utf-8"))
    except Exception:
        return out
    for sec in manifest.get("sections", []):
        slides = sec.get("slides", [])
        if slides:
            out[sec.get("name", "")] = f"{SITE_URL}/{slides[0]}"
    return out


def publish_tweets():
    if not X_CHANNEL:
        print("No BUFFER_X_CHANNEL_ID set — skipping tweets.")
        return
    qpath = "tweets/queue.json"
    if not os.path.exists(qpath):
        print("No tweets/queue.json — nothing to post.")
        return
    with open(qpath, encoding="utf-8") as f:
        queue = json.load(f)

    posted_path = "tweets/posted.json"
    posted = {"keys": []}
    if os.path.exists(posted_path):
        try:
            posted = json.load(open(posted_path, encoding="utf-8"))
        except Exception:
            pass
    done = set(posted.get("keys", []))

    # Map section name -> its Instagram cover slide URL (a ready-made branded
    # card), used as the tweet image when a story has no photo of its own.
    covers = _section_cover_urls()

    pending = queue.get("pending", [])
    if not pending:
        print("Tweet queue has no pending items — run a fresh edition to generate tweets.")
    new_count = sum(1 for it in pending if it.get("key") and it.get("key") not in done)
    if pending and new_count == 0:
        print(f"All {len(pending)} queued tweets already posted (nothing new).")
    sent = 0
    for item in pending:
        key = item.get("key")
        if not key or key in done:
            continue
        text = item["text"]
        # LINK-PREVIEW BEHAVIOUR: if the tweet contains its article link (it
        # normally does), DON'T attach an uploaded image — X will auto-generate
        # a rich link-preview card from the article page's Open Graph image and
        # title, which is more clickable and "Twitter-native" than a bare photo.
        # Only attach an image as a fallback when the tweet has NO link.
        has_link = "http://" in text or "https://" in text
        if has_link:
            imgs = None
        else:
            img = (item.get("image") or "").strip()
            if not img:
                img = covers.get(item.get("section", ""), "")
            imgs = [img] if img else None
        try:
            pid = _create_post(X_CHANNEL, text, image_urls=imgs, slot_index=sent)
            done.add(key)
            sent += 1
            tag = "link preview" if has_link else ("with image" if imgs else "text only")
            print(f"  ✓ tweet queued to Buffer ({tag}) ({key[:40]}) id={pid}")
            time.sleep(1)
        except Exception as exc:
            # Most failures are image-fetch errors (404/expired URL). A tweet
            # never NEEDS an image — retry text-only so it still goes out.
            if imgs:
                try:
                    pid = _create_post(X_CHANNEL, text, image_urls=None,
                                       slot_index=sent)
                    done.add(key)
                    sent += 1
                    print(f"  ✓ tweet queued to Buffer (text only, image skipped) "
                          f"({key[:40]}) id={pid}")
                    time.sleep(1)
                    continue
                except Exception as exc2:
                    print(f"  ✗ tweet failed even text-only ({key[:40]}): {exc2}")
            else:
                print(f"  ✗ tweet failed ({key[:40]}): {exc}")

    posted["keys"] = list(done)
    with open(posted_path, "w", encoding="utf-8") as f:
        json.dump(posted, f, ensure_ascii=False, indent=2)
    print(f"Tweets pushed to Buffer: {sent}.")


# -------------------------------------------------------------- carousels ---
def publish_carousels():
    if not IG_CHANNEL:
        print("No BUFFER_IG_CHANNEL_ID set — skipping carousels.")
        return
    # Most recent manifest only (today's carousels).
    manifests = sorted(glob.glob("social/instagram/*/manifest.json"))
    if not manifests:
        print("No Instagram manifests — nothing to post.")
        return
    mpath = manifests[-1]
    base = os.path.dirname(mpath)
    date_dir = os.path.basename(base)
    with open(mpath, encoding="utf-8") as f:
        manifest = json.load(f)

    posted_path = os.path.join(base, "buffer-posted.json")
    done = set()
    if os.path.exists(posted_path):
        try:
            done = set(json.load(open(posted_path, encoding="utf-8")).get("sections", []))
        except Exception:
            pass

    sent = 0
    for sec in manifest.get("sections", []):
        sid = sec["id"]
        if sid in done:
            continue
        # Build PUBLIC urls for each slide (GitHub Pages serves the repo).
        # slide paths look like social/instagram/<date>/<section>/slide-01.png
        slide_urls = [f"{SITE_URL}/{p}" for p in sec.get("slides", [])]
        if not slide_urls:
            continue
        # caption
        caption = ""
        cf = sec.get("caption_file")
        if cf and os.path.exists(cf):
            caption = open(cf, encoding="utf-8").read().strip()
        try:
            pid = _create_post(IG_CHANNEL, caption, image_urls=slide_urls, instagram=True, slot_index=sent)
            done.add(sid)
            sent += 1
            print(f"  ✓ carousel '{sec['name']}' queued to Buffer "
                  f"({len(slide_urls)} slides) id={pid}")
            time.sleep(1)
        except Exception as exc:
            print(f"  ✗ carousel '{sec['name']}' failed: {exc}")

    with open(posted_path, "w", encoding="utf-8") as f:
        json.dump({"sections": list(done)}, f, ensure_ascii=False, indent=2)
    print(f"Carousels pushed to Buffer: {sent} (from {date_dir}).")


# ----------------------------------------------------------------- stories ---
def publish_stories():
    """Push the day's Instagram STORY images (from manifest['stories']) to Buffer
    as individual Instagram stories. Buffer auto-posts story MEDIA; it cannot
    auto-add tappable link stickers (Instagram API limit), so these are
    media-only with an in-bio call to action baked into the image. Each story
    image is posted as a SEPARATE story (Buffer requires one media per story)."""
    if not IG_CHANNEL:
        print("No BUFFER_IG_CHANNEL_ID set — skipping stories.")
        return
    manifests = sorted(glob.glob("social/instagram/*/manifest.json"))
    if not manifests:
        print("No manifests — nothing to post to stories.")
        return
    mpath = manifests[-1]
    base = os.path.dirname(mpath)
    date_dir = os.path.basename(base)
    with open(mpath, encoding="utf-8") as f:
        manifest = json.load(f)
    stories = manifest.get("stories", [])
    if not stories:
        print("No story images in manifest — skipping stories.")
        return

    posted_path = os.path.join(base, "buffer-stories-posted.json")
    done = set()
    if os.path.exists(posted_path):
        try:
            done = set(json.load(open(posted_path, encoding="utf-8")).get("stories", []))
        except Exception:
            pass

    sent = 0
    for i, story in enumerate(stories):
        img_path = story.get("image", "")
        if not img_path or img_path in done:
            continue
        url = f"{SITE_URL}/{img_path}"
        try:
            # No caption text on stories; the headline is rendered into the image.
            pid = _create_post(IG_CHANNEL, "", image_urls=[url],
                               instagram="story", slot_index=sent)
            done.add(img_path)
            sent += 1
            print(f"  ✓ story {i+1} queued to Buffer ({story.get('headline','')[:40]}) id={pid}")
            time.sleep(1)
        except Exception as exc:
            print(f"  ✗ story {i+1} failed: {exc}")

    with open(posted_path, "w", encoding="utf-8") as f:
        json.dump({"stories": list(done)}, f, ensure_ascii=False, indent=2)
    print(f"Stories pushed to Buffer: {sent} (from {date_dir}).")


# --------------------------------------------------------------- linkedin ---
def publish_linkedin():
    """Post up to 3 carousels to LinkedIn — only the professional-fit sections
    (AI, Technology, World news). Uses the same carousel images + caption."""
    if not LINKEDIN_CHANNEL:
        print("No BUFFER_LINKEDIN_CHANNEL_ID set — skipping LinkedIn.")
        return
    manifests = sorted(glob.glob("social/instagram/*/manifest.json"))
    if not manifests:
        print("No manifests — nothing to post to LinkedIn.")
        return
    mpath = manifests[-1]
    base = os.path.dirname(mpath)
    date_dir = os.path.basename(base)
    with open(mpath, encoding="utf-8") as f:
        manifest = json.load(f)

    posted_path = os.path.join(base, "linkedin-posted.json")
    done = set()
    if os.path.exists(posted_path):
        try:
            done = set(json.load(open(posted_path, encoding="utf-8")).get("sections", []))
        except Exception:
            pass

    # Keep only LinkedIn-appropriate sections, in priority order, capped at 3.
    secs = {s["id"]: s for s in manifest.get("sections", [])}
    ordered = [secs[sid] for sid in LINKEDIN_SECTIONS if sid in secs]

    sent = 0
    for sec in ordered:
        if sent >= 3:
            break
        sid = sec["id"]
        if sid in done:
            continue
        slide_urls = [f"{SITE_URL}/{p}" for p in sec.get("slides", [])]
        if not slide_urls:
            continue
        # Prefer the LinkedIn-specific caption; fall back to the IG one.
        caption = ""
        cf = sec.get("linkedin_caption_file") or sec.get("caption_file")
        if cf and os.path.exists(cf):
            caption = open(cf, encoding="utf-8").read().strip()
        # Prefer posting the PDF document (LinkedIn renders PDF carousels well);
        # fall back to the slide images if no PDF.
        li_pdf = sec.get("linkedin_pdf") or sec.get("pdf")
        try:
            if li_pdf and os.path.exists(li_pdf):
                doc_url = f"{SITE_URL}/{li_pdf}"
                # Use the first slide PNG as the document thumbnail.
                slides_li = sec.get("slides", [])
                thumb = f"{SITE_URL}/{slides_li[0]}" if slides_li else ""
                pid = _create_post(LINKEDIN_CHANNEL, caption, document_url=doc_url,
                                   document_title=f"The Last 24 — {sec['name']}",
                                   document_thumbnail=thumb, slot_index=sent)
            else:
                pid = _create_post(LINKEDIN_CHANNEL, caption, image_urls=slide_urls,
                                   slot_index=sent)
            done.add(sid)
            sent += 1
            print(f"  ✓ LinkedIn '{sec['name']}' queued to Buffer id={pid}")
            time.sleep(1)
        except Exception as exc:
            print(f"  ✗ LinkedIn '{sec['name']}' failed: {exc}")

    with open(posted_path, "w", encoding="utf-8") as f:
        json.dump({"sections": list(done)}, f, ensure_ascii=False, indent=2)
    print(f"LinkedIn posts pushed to Buffer: {sent} (from {date_dir}).")


def list_channels():
    """Print connected Buffer channels + their IDs. Tries a few schema shapes
    since Buffer's GraphQL field nesting can vary. Run: python scripts/buffer_publish.py --list-channels"""
    if not API_KEY:
        print("Set BUFFER_API_KEY first:  export BUFFER_API_KEY=your_key")
        return
    queries = [
        # shape 1: organizations -> channels (flat)
        "query { account { organizations { id name channels { id service name } } } }",
        # shape 2: channels at account level
        "query { account { channels { id service name } } }",
        # shape 3: top-level channels
        "query { channels { id service name } }",
        # shape 4: currentUser
        "query { currentUser { organizations { id channels { id service name } } } }",
    ]
    for q in queries:
        try:
            data = _gql(q)
        except Exception as exc:
            continue
        # walk the result for anything that looks like a channel list
        found = []
        def walk(obj):
            if isinstance(obj, dict):
                if "service" in obj and "id" in obj:
                    found.append(obj)
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)
        walk(data)
        if found:
            print("\nConnected Buffer channels:\n")
            for c in found:
                svc = (c.get("service") or "?").lower()
                hint = ""
                if svc in ("twitter", "x"):
                    hint = "  <-- BUFFER_X_CHANNEL_ID"
                elif svc == "instagram":
                    hint = "  <-- BUFFER_IG_CHANNEL_ID"
                print(f"  {svc:12} {c.get('name','')!r:28} id = {c['id']}{hint}")
            print("\nCopy the IDs above into your GitHub repo secrets.")
            return
    print("Could not auto-discover channels with the known query shapes.\n"
          "Open Buffer's API explorer (developers.buffer.com) and use the\n"
          "documented 'list channels' query, then read the id + service fields.")


def main():
    if not API_KEY:
        print("BUFFER_API_KEY not set — skipping Buffer publish (no error).")
        return
    print("Pushing to Buffer...")
    publish_tweets()
    publish_carousels()
    publish_stories()
    publish_linkedin()
    print("Buffer publish complete.")


if __name__ == "__main__":
    import sys
    if "--list-channels" in sys.argv:
        list_channels()
    else:
        main()
