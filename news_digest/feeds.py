"""RSS/Atom feed fetching, deduplication, and filtering."""

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

import feedparser
import httpx

log = logging.getLogger("news_digest")

USER_AGENT = "AINewsDigest/0.1 (github.com/mtolmachev/ai-news-digest)"
FETCH_TIMEOUT = 15


def fetch_feeds(feeds: dict[str, str]) -> list[dict]:
    """Fetch all configured RSS/Atom feeds. Returns list of items."""
    items = []
    client = httpx.Client(
        timeout=FETCH_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    for name, url in feeds.items():
        try:
            resp = client.get(url)
            if resp.status_code != 200:
                log.warning(f"{name}: HTTP {resp.status_code}")
                continue
            feed = feedparser.parse(resp.text)
            for entry in feed.entries[:10]:
                item = {
                    "source": name,
                    "title": entry.get("title", "").strip(),
                    "url": entry.get("link", ""),
                    "summary": _clean_html(
                        entry.get("summary", entry.get("description", ""))
                    ),
                    "published": _parse_date(entry),
                }
                if item["title"] and item["url"]:
                    items.append(item)
            log.info(f"{name}: {len(feed.entries)} entries")
        except Exception as e:
            log.warning(f"{name}: {e}")
    client.close()
    return items


def filter_new(items: list[dict], seen: set) -> list[dict]:
    """Remove already-seen URLs."""
    return [item for item in items if item["url"] not in seen]


def filter_recent(items: list[dict], hours: int = 48) -> list[dict]:
    """Keep only items from the last N hours."""
    cutoff = datetime.now() - timedelta(hours=hours)
    result = []
    for item in items:
        if not item["published"]:
            result.append(item)
            continue
        try:
            pub = datetime.fromisoformat(item["published"].replace("Z", "+00:00"))
            if pub.replace(tzinfo=None) > cutoff:
                result.append(item)
        except (ValueError, TypeError):
            result.append(item)
    return result


def filter_relevant(items: list[dict], keywords: list[str]) -> list[dict]:
    """Keep only items matching keywords. If no keywords, keep all."""
    if not keywords:
        return items
    kw_lower = [k.lower() for k in keywords]
    return [
        item
        for item in items
        if any(
            kw in f"{item['title']} {item['summary']}".lower() for kw in kw_lower
        )
    ]


# --- State (seen URLs) ---


def load_seen(state_file: str) -> set:
    """Load seen URLs from state file."""
    path = Path(state_file)
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text())
        return set(data.get("urls", []))
    except (json.JSONDecodeError, KeyError):
        return set()


def save_seen(seen: set, state_file: str, max_seen: int = 1000):
    """Save seen URLs to state file."""
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    urls = sorted(seen)[-max_seen:]
    path.write_text(
        json.dumps(
            {"urls": urls, "updated": datetime.now().isoformat()},
            ensure_ascii=False,
        )
    )


# --- Helpers ---


def _clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]


def _parse_date(entry) -> str:
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                return datetime(*parsed[:6]).isoformat()
            except (TypeError, ValueError):
                pass
    return ""
