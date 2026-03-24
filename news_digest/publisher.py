"""Telegram publishing via Bot API (httpx, no extra deps)."""

import logging

import httpx

log = logging.getLogger("news_digest")

API_BASE = "https://api.telegram.org/bot{token}"
MAX_MSG_LEN = 4000


def send_telegram(text: str, token: str, channel: str):
    """Send digest to Telegram channel. Splits long messages."""
    base = API_BASE.format(token=token)
    chunks = _split_html(text, MAX_MSG_LEN) if len(text) > MAX_MSG_LEN else [text]

    for chunk in chunks:
        resp = httpx.post(
            f"{base}/sendMessage",
            json={
                "chat_id": channel,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            error = resp.json().get("description", resp.text[:200])
            log.error(f"Telegram error: {error}")
            raise RuntimeError(f"Telegram API error: {error}")

    log.info(f"Sent to {channel} ({len(chunks)} message(s))")


def _split_html(text: str, max_len: int) -> list[str]:
    """Split text into chunks at newline boundaries."""
    chunks = []
    buf = ""
    for line in text.split("\n"):
        if len(buf) + len(line) + 1 > max_len:
            if buf:
                chunks.append(buf)
            buf = line[:max_len]
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf:
        chunks.append(buf)
    return chunks
