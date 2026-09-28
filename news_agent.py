import os
import re
import json
import time
import html
import calendar
import pathlib
import datetime
from urllib.parse import quote, urljoin, urlparse
import requests
import feedparser
try:
    from googlenewsdecoder import new_decoderv1
except Exception:
    new_decoderv1 = None

def google_news_feed(query, hl="en-US", gl="US", ceid="US:en"):
    q = quote(f"{query} when:12h")
    return f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"

FEEDS = {
    "Film Industry": google_news_feed("film industry news"),
    "Business":       google_news_feed("business news"),
    "Tech":           google_news_feed("technology news"),
    "Gaming":         google_news_feed("gaming industry news"),
    "Local (India)":  google_news_feed("India news", hl="en-IN", gl="IN", ceid="IN:en"),
    "Finance":        google_news_feed("finance markets news"),
    "Health":         google_news_feed("health news"),
    "Politics":       google_news_feed("politics news"),
    "Wars/Conflict":  google_news_feed("war conflict news"),
    "AI News":        google_news_feed("Claude Anthropic OR OpenAI OR Google DeepMind new AI model"),
    "Automotive":     google_news_feed("new car launch Mahindra Thar OR Tata OR Maruti OR Hyundai"),
    "Russia":         google_news_feed("Russia news"),
    "China":          google_news_feed("China news"),
    "Japan":          google_news_feed("Japan news"),
    "USA":            google_news_feed("United States news"),
    "Brazil":         google_news_feed("Brazil news"),
}

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
SEEN_FILE = "seen_ids.json"
MAX_SEEN_STORED = 5000
HOURS_WINDOW = 12
EMBEDS_PER_MESSAGE = 5  # smaller batches = safely under Discord's size limit

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE
)
TWITTER_IMAGE_RE = re.compile(
    r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE
)
TAG_RE = re.compile(r"<[^>]+>")

def clean_text(raw):
    text = html.unescape(TAG_RE.sub(" ", raw or ""))
    return re.sub(r"\s+", " ", text).strip()

def load_seen():
    path = pathlib.Path(SEEN_FILE)
    if path.exists():
        with open(path) as f:
            return set(json.load(f))
    return set()

def save_seen(seen_list):
    trimmed = seen_list[-MAX_SEEN_STORED:]
    with open(SEEN_FILE, "w") as f:
        json.dump(trimmed, f)

def is_recent(entry, hours=HOURS_WINDOW):
    if getattr(entry, "published_parsed", None):
        published_dt = datetime.datetime.utcfromtimestamp(
            calendar.timegm(entry.published_parsed)
        )
        return (datetime.datetime.utcnow() - published_dt) <= datetime.timedelta(hours=hours)
    return True

DECODE_BUDGET = 40  # max Google links decoded per run (keeps Google from rate-limiting us)
_decoded_count = 0

def resolve_real_url(url):
    """Google News links are wrappers. Decode to the real publisher URL."""
    global _decoded_count
    if "news.google.com" not in url:
        return url
    if new_decoderv1 is None or _decoded_count >= DECODE_BUDGET:
        return None
    _decoded_count += 1
    try:
        result = new_decoderv1(url, interval=1)
        if result.get("status") and result.get("decoded_url"):
            return result["decoded_url"]
    except Exception:
        pass
    return None

def get_image(real_url, timeout=8):
    """Find the article's preview image. Returns a valid absolute URL or None."""
    if not real_url:
        return None
    try:
        resp = requests.get(real_url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        head = resp.text[:40000]
        match = OG_IMAGE_RE.search(head) or TWITTER_IMAGE_RE.search(head)
        if not match:
            # some sites write content= before property=
            alt = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', head, re.I)
            match = alt
        if match:
            img = urljoin(resp.url, html.unescape(match.group(1)))
            if img.startswith(("http://", "https://")) and len(img) < 1000:
                return img
    except Exception:
        pass
    return None

def favicon_for(url):
    """Publisher logo as a guaranteed fallback picture."""
    try:
        domain = urlparse(url).netloc
        if domain and "google.com" not in domain:
            return f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
    except Exception:
        pass
    return None

def scout(feed_name, feed_url):
    parsed = feedparser.parse(feed_url)
    items = []
    for entry in parsed.entries:
        if not is_recent(entry):
            continue
        link = entry.get("link", "")
        title = clean_text(entry.get("title", ""))
        summary = clean_text(entry.get("summary", ""))
        source, source_url = "", ""
        src = entry.get("source")
        if src and hasattr(src, "get"):
            source = src.get("title", "")
            source_url = src.get("href", "")
        if not summary or summary.lower().startswith(title.lower()[:40]):
            summary = f"Source: {source}" if source else ""
        items.append({
            "category": feed_name,
            "title": title,
            "summary": summary[:250],
            "link": link,
            "source_url": source_url,
            "uid": link or entry.get("id", "") or title,
        })
    return items

def build_embed(item, with_image=True):
    embed = {
        "title": item["title"][:250] or "News",
        "description": item["summary"],
        "url": item["link"],
        "footer": {"text": item["category"]},
        "color": 3447003,
    }
    if with_image:
        if "real_url" not in item:
            item["real_url"] = resolve_real_url(item["link"])
        real = item["real_url"]
        if real:
            embed["url"] = real
        if "img" not in item:
            item["img"] = get_image(real)
        if item["img"]:
            embed["image"] = {"url": item["img"]}
        else:
            logo = favicon_for(real or item.get("source_url", ""))
            if logo:
                embed["thumbnail"] = {"url": logo}
    return embed

def post_to_discord(embeds):
    """Send embeds; handle rate limits. Returns True on success."""
    for attempt in range(3):
        resp = requests.post(WEBHOOK_URL, json={"embeds": embeds}, timeout=20)
        if resp.status_code in (200, 204):
            return True
        if resp.status_code == 429:
            try:
                wait = float(resp.json().get("retry_after", 2))
            except Exception:
                wait = 2
            time.sleep(wait + 0.5)
            continue
        print(f"Discord rejected ({resp.status_code}): {resp.text[:200]}")
        return False
    return False

def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]

def publish(items):
    """Returns the list of uids that were actually delivered."""
    delivered = []
    for batch in chunked(items, EMBEDS_PER_MESSAGE):
        embeds = [build_embed(item) for item in batch]
        if post_to_discord(embeds):
            delivered.extend(item["uid"] for item in batch)
        else:
            # batch failed: retry one by one, then without image as last resort
            for item in batch:
                if post_to_discord([build_embed(item)]) or post_to_discord([build_embed(item, with_image=False)]):
                    delivered.append(item["uid"])
                time.sleep(0.5)
        time.sleep(1)
    return delivered

def main():
    seen_set = load_seen()
    seen_list = list(seen_set)

    all_items = []
    for name, url in FEEDS.items():
        all_items.extend(scout(name, url))

    # drop already-sent items AND duplicates inside this run
    new_items, batch_seen = [], set()
    for item in all_items:
        if item["uid"] in seen_set or item["uid"] in batch_seen:
            continue
        batch_seen.add(item["uid"])
        new_items.append(item)

    delivered = publish(new_items)

    # only remember what was truly delivered, so failures get retried next run
    seen_list.extend(delivered)
    save_seen(seen_list)

    print(f"Checked {len(all_items)} | new {len(new_items)} | delivered {len(delivered)} (last {HOURS_WINDOW}h).")

if __name__ == "__main__":
    main()
