 import os
import re
import json
import time
import calendar
import pathlib
import datetime
from urllib.parse import quote
import requests
import feedparser

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
EMBEDS_PER_MESSAGE = 10

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NewsAgentBot/1.0)"}
OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE
)

def load_seen():
    path = pathlib.Path(SEEN_FILE)
    if path.exists():
        with open(path) as f:
            return set(json.load(f))
    return set()

def save_seen(seen_set):
    trimmed = list(seen_set)[-MAX_SEEN_STORED:]
    with open(SEEN_FILE, "w") as f:
        json.dump(trimmed, f)

def is_recent(entry, hours=HOURS_WINDOW):
    if getattr(entry, "published_parsed", None):
        published_dt = datetime.datetime.utcfromtimestamp(
            calendar.timegm(entry.published_parsed)
        )
        return (datetime.datetime.utcnow() - published_dt) <= datetime.timedelta(hours=hours)
    return True

def get_og_image(url, timeout=4):
    if not url:
        return None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        match = OG_IMAGE_RE.search(resp.text[:20000])
        if match:
            return match.group(1)
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
        items.append({
            "category": feed_name,
            "title": entry.get("title", ""),
            "summary": entry.get("summary", "")[:300],
            "link": link,
            "uid": link or entry.get("id", "") or entry.get("title", ""),
        })
    return items

def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]

def publish(items):
    if not items:
        print("No new items this run.")
        return
    for batch in chunked(items, EMBEDS_PER_MESSAGE):
        embeds = []
        for item in batch:
            embed = {
                "title": item["title"][:250],
                "description": item["summary"],
                "url": item["link"],
                "footer": {"text": item["category"]},
                "color": 3447003,
            }
            image_url = get_og_image(item["link"])
            if image_url:
                embed["image"] = {"url": image_url}
            embeds.append(embed)

        resp = requests.post(WEBHOOK_URL, json={"embeds": embeds})
        if resp.status_code not in (200, 204):
            print(f"Failed to send batch: {resp.status_code} {resp.text}")
        time.sleep(1)

def main():
    seen = load_seen()
    all_items = []
    for name, url in FEEDS.items():
        all_items.extend(scout(name, url))

    new_items = [item for item in all_items if item["uid"] not in seen]
    publish(new_items)

    for item in new_items:
        seen.add(item["uid"])
    save_seen(seen)

    print(f"Done. Sent {len(new_items)} new item(s) out of {len(all_items)} checked (last {HOURS_WINDOW}h).")

if __name__ == "__main__":
    main()
