import os
import re
import requests
import feedparser

FEEDS = {
    "World":   "https://feeds.bbci.co.uk/news/world/rss.xml",
    "Tech":    "https://feeds.arstechnica.com/arstechnica/index",
    "Business": "https://feeds.bbci.co.uk/news/business/rss.xml",
}

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
MAX_ITEMS_PER_FEED = 3
FIGURE_PATTERN = re.compile(r"\d")

def scout(feed_name, feed_url):
    parsed = feedparser.parse(feed_url)
    items = []
    for entry in parsed.entries[:MAX_ITEMS_PER_FEED]:
        items.append({
            "category": feed_name,
            "title": entry.get("title", ""),
            "summary": entry.get("summary", ""),
            "link": entry.get("link", ""),
        })
    return items

def verify(items):
    seen_titles = set()
    verified = []
    for item in items:
        text = item["title"] + " " + item["summary"]
        has_figure = bool(FIGURE_PATTERN.search(text))
        if item["title"] in seen_titles:
            continue
        seen_titles.add(item["title"])
        if has_figure:
            verified.append(item)
    return verified

def publish(items):
    if not items:
        print("No items with figures found this run.")
        return
    for item in items:
        payload = {
            "embeds": [{
                "title": item["title"][:250],
                "description": item["summary"][:400],
                "url": item["link"],
                "footer": {"text": item["category"]},
                "color": 3447003,
            }]
        }
        resp = requests.post(WEBHOOK_URL, json=payload)
        if resp.status_code not in (200, 204):
            print(f"Failed to send: {resp.status_code} {resp.text}")

def main():
    all_items = []
    for name, url in FEEDS.items():
        all_items.extend(scout(name, url))
    verified_items = verify(all_items)
    publish(verified_items)
    print(f"Done. Sent {len(verified_items)} item(s).")

if __name__ == "__main__":
    main()
