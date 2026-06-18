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
_CREATE = """
mutation Create($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id } }
    ... on MutationError { message }
  }
}
"""


def _create_post(channel_id, text, image_urls=None):
    """Create one Buffer post. image_urls: list of public image URLs (carousel)."""
    inp = {
        "text": text,
        "channelId": channel_id,
        "schedulingType": "automatic",
        "mode": "addToQueue" if SCHEDULE != "now" else "share",
    }
    if image_urls:
        # Buffer's AssetInput: each entry specifies one of image/video/document/link.
        # For images: {"image": {"url": "..."}} — NOT {"type","url"}.
        inp["assets"] = [{"image": {"url": u}} for u in image_urls]
    data = _gql(_CREATE, {"input": inp})
    res = data.get("createPost", {})
    if res.get("message"):
        raise RuntimeError(f"createPost rejected: {res['message']}")
    return (res.get("post") or {}).get("id")


# ----------------------------------------------------------------- tweets ---
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

    pending = queue.get("pending", [])
    sent = 0
    for item in pending:
        key = item.get("key")
        if not key or key in done:
            continue
        try:
            pid = _create_post(X_CHANNEL, item["text"])
            done.add(key)
            sent += 1
            print(f"  ✓ tweet queued to Buffer ({key[:40]}) id={pid}")
            time.sleep(1)  # be gentle on rate limits
        except Exception as exc:
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
            pid = _create_post(IG_CHANNEL, caption, image_urls=slide_urls)
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
    print("Buffer publish complete.")


if __name__ == "__main__":
    import sys
    if "--list-channels" in sys.argv:
        list_channels()
    else:
        main()
