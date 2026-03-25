"""LLM calls: news selection (fast model) + digest writing (quality model + style + humanizer).

Supports two backends:
- "api": Anthropic Python SDK (requires API key)
- "claude-code": Claude Code CLI (requires Max/Team subscription, no API key needed)
"""

import json
import logging
import os
import re
import shutil
import subprocess
from html import escape

log = logging.getLogger("news_digest")

# --- Humanizer rules (condensed from blader/humanizer, based on Wikipedia's "Signs of AI writing") ---

HUMANIZER_RULES = """
ANTI-AI WRITING RULES (apply to every sentence):

1. NO significance inflation: remove "pivotal", "groundbreaking", "testament", "vital role",
   "marks a shift", "evolving landscape", "setting the stage". Just state what happened.

2. NO -ing analyses: remove "highlighting...", "underscoring...", "showcasing...",
   "reflecting...", "emphasizing...". Use short direct sentences instead.

3. NO promotional language: remove "vibrant", "stunning", "breathtaking", "nestled",
   "in the heart of", "boasts", "renowned". Use plain descriptions.

4. NO vague attributions: remove "experts say", "industry observers note",
   "some critics argue". Name the source or drop the claim.

5. NO AI vocabulary: avoid "Additionally", "crucial", "delve", "foster", "garner",
   "interplay", "intricate", "landscape" (abstract), "tapestry", "underscore", "enhance".

6. NO copula avoidance: use "is/are/has" instead of "serves as", "stands as",
   "represents", "boasts", "features", "offers".

7. NO rule of three: don't force ideas into groups of three.
   "innovation, inspiration, and industry insights" → just say what matters.

8. NO negative parallelisms: avoid "Not only X, but Y", "It's not just X, it's Y".

9. NO em dash overuse: use commas or periods. One em dash per post max.

10. NO sycophantic tone: remove "Great question!", "Excellent point!",
    "I hope this helps!", "Let me know if..."

11. NO generic conclusions: remove "The future looks bright", "Exciting times ahead",
    "This is just the beginning".

12. ADD SOUL: vary sentence length, have opinions, acknowledge uncertainty,
    be specific about reactions. "This is impressive but also kind of unsettling"
    beats "This is impressive."
"""

# --- Feed topic suggestions ---

FEED_SUGGESTIONS = {
    "AI/ML": {
        "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "Ars Technica AI": "https://arstechnica.com/ai/feed/",
        "HN AI 100+": "https://hnrss.org/frontpage?q=AI&points=100",
        "Reddit ML": "https://www.reddit.com/r/MachineLearning/hot/.rss",
        "Reddit LocalLLaMA": "https://www.reddit.com/r/LocalLLaMA/hot/.rss",
        "Simon Willison": "https://simonwillison.net/atom/everything/",
        "The Rundown AI": "https://rss.beehiiv.com/feeds/2R3C6Bt5wj.xml",
        "Hugging Face": "https://huggingface.co/blog/feed.xml",
        "Google DeepMind": "https://deepmind.google/blog/rss.xml",
        "Import AI": "https://importai.substack.com/feed",
    },
    "AI tools": {
        "Claude Code releases": "https://github.com/anthropics/claude-code/releases.atom",
        "Codex releases": "https://github.com/openai/codex/releases.atom",
        "Gemini CLI releases": "https://github.com/google-gemini/gemini-cli/releases.atom",
        "MCP servers": "https://github.com/modelcontextprotocol/servers/releases.atom",
        "Anthropic News": "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
        "OpenAI News": "https://openai.com/news/rss.xml",
    },
    "startups": {
        "TechCrunch Startups": "https://techcrunch.com/category/startups/feed/",
        "Y Combinator Blog": "https://www.ycombinator.com/blog/rss/",
        "HN Best": "https://hnrss.org/best?points=200",
    },
    "product management": {
        "Lenny's Newsletter": "https://www.lennysnewsletter.com/feed",
        "Product Hunt": "https://www.producthunt.com/feed",
        "Mind the Product": "https://www.mindtheproduct.com/feed/",
    },
    "web development": {
        "CSS Tricks": "https://css-tricks.com/feed/",
        "Smashing Magazine": "https://www.smashingmagazine.com/feed/",
        "JavaScript Weekly": "https://javascriptweekly.com/rss/",
        "GitHub Blog": "https://github.blog/feed/",
    },
    "cybersecurity": {
        "Krebs on Security": "https://krebsonsecurity.com/feed/",
        "The Hacker News": "https://feeds.feedburner.com/TheHackersNews",
        "Schneier on Security": "https://www.schneier.com/feed/atom/",
    },
    "crypto": {
        "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "The Block": "https://www.theblock.co/rss.xml",
    },
    "fintech": {
        "Finextra": "https://www.finextra.com/rss/headlines.aspx",
        "TechCrunch Fintech": "https://techcrunch.com/category/fintech/feed/",
    },
    "github trending": {
        "GH Trending Python": "https://mshibanami.github.io/GitHubTrendingRSS/daily/python.xml",
        "GH Trending All": "https://mshibanami.github.io/GitHubTrendingRSS/daily/all.xml",
        "GH Trending JS": "https://mshibanami.github.io/GitHubTrendingRSS/daily/javascript.xml",
        "GH Trending TS": "https://mshibanami.github.io/GitHubTrendingRSS/daily/typescript.xml",
        "GH Trending Rust": "https://mshibanami.github.io/GitHubTrendingRSS/daily/rust.xml",
    },
    "russian AI": {
        "Habr ML": "https://habr.com/ru/rss/hubs/machine_learning/articles/all/",
        "Habr AI": "https://habr.com/ru/rss/hubs/artificial_intelligence/articles/all/",
    },
}


# --- LLM Backend Abstraction ---


def _call_llm(prompt: str, model: str, cfg: dict, max_tokens: int = 4096, timeout: int = 180) -> str:
    """Call LLM via configured backend. Returns raw text output."""
    backend = cfg.get("backend", "api")

    if backend == "claude-code":
        return _call_claude_code(prompt, model, cfg, timeout)
    else:
        return _call_api(prompt, model, cfg, max_tokens)


def _call_api(prompt: str, model: str, cfg: dict, max_tokens: int = 4096) -> str:
    """Call Anthropic Messages API directly."""
    import anthropic

    client = anthropic.Anthropic(api_key=cfg["anthropic_api_key"])
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def _call_claude_code(prompt: str, model: str, cfg: dict, timeout: int = 180) -> str:
    """Call Claude Code CLI (uses Max/Team subscription, no API key)."""
    claude_path = cfg.get("claude_code_path", "claude")

    # Resolve path: check if it's in PATH or use as-is
    resolved = shutil.which(claude_path) or claude_path

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env["LANG"] = "en_US.UTF-8"

    result = subprocess.run(
        [resolved, "-p", "-",
         "--output-format", "text",
         "--max-turns", "3",
         "--model", model,
         "--permission-mode", "plan",
         "--allowedTools", ""],
        input=prompt.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        env=env,
    )
    output = result.stdout.decode("utf-8").strip()
    if result.returncode != 0 or not output:
        stderr = result.stderr.decode("utf-8")[:300]
        raise RuntimeError(f"Claude Code failed (rc={result.returncode}): {stderr}")
    return output


def select_news(items: list[dict], cfg: dict, published_titles: list[str] | None = None) -> list[dict]:
    """Use fast model to select top news items. Returns structured JSON."""
    if not items:
        return []

    max_items = min(len(items), 30)
    items_json = json.dumps(items[:max_items], ensure_ascii=False, indent=2)
    digest_size = cfg.get("digest_size", 7)
    lang = cfg.get("language", "en")

    lang_instruction = (
        "Write titles in Russian (keep technical terms in English: LLM, MCP, RAG)."
        if lang == "ru"
        else "Write titles in English."
    )

    dedup_block = ""
    if published_titles:
        titles_text = "\n".join(published_titles[-50:])
        dedup_block = f"""
DEDUPLICATION — these topics were already covered in recent digests. Do NOT select them again (even if the URL is different):
{titles_text}
"""

    prompt = f"""You are a news editor. From the list below, select the {digest_size} most important items.
{dedup_block}
Return ONLY a JSON array. Each element:
{{
  "title": "headline — {lang_instruction}",
  "url": "REQUIRED — exact url from input data, copy verbatim",
  "source": "source name from input data",
  "summary": "2-3 sentences: what happened, context, details",
  "takeaway": "1-2 sentences: how to apply this / what it means for the market",
  "category": "releases" | "companies" | "community" | "research",
  "priority": "red" | "yellow" | "white"
}}

Priority criteria:
- red: actionable NOW (new tool, feature) OR major market shift (big release, deal, breakthrough)
- yellow: useful to know, may help in work/projects
- white: interesting fact, trend, FYI

Rules:
- STRICTLY {digest_size} items, no more. Better 5 strong than 7 mediocre.
- For GitHub repos: include stars in title if mentioned, note famous authors
- url is REQUIRED — take from input, never invent
- Output ONLY JSON array, no markdown, no explanations

News:
{items_json}"""

    try:
        output = _call_llm(prompt, cfg.get("selector_model", "claude-haiku-4-5-20251001"), cfg)

        # Parse JSON
        cleaned = re.sub(r"^```json\s*", "", output)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            m = re.search(r"\[.*\]", output, re.DOTALL)
            if m:
                parsed = json.loads(m.group(0))
            else:
                log.error(f"Failed to parse selector JSON: {output[:300]}")
                return []

        if not isinstance(parsed, list):
            return []

        return [item for item in parsed if isinstance(item, dict) and item.get("title") and item.get("url")]

    except Exception as e:
        log.error(f"Selector failed: {e}")
        return []


def write_digest(selected: list[dict], cfg: dict) -> str:
    """Use quality model to write the final digest post in user's style."""
    if not selected:
        return ""

    lang = cfg.get("language", "en")
    style_profile = cfg.get("style_profile", "")
    style_samples = cfg.get("style_samples", [])

    # Build style context
    style_block = ""
    if style_profile:
        style_block += f"\nYOUR STYLE PROFILE:\n{style_profile}\n"
    if style_samples:
        samples_text = "\n---\n".join(style_samples[:5])
        style_block += f"\nSAMPLE POSTS (match this voice):\n{samples_text}\n"

    lang_instructions = {
        "ru": "Write in conversational Russian. Tech terms stay in English (LLM, MCP, API).",
        "en": "Write in clear, conversational English. No corporate speak.",
    }

    news_json = json.dumps(selected, ensure_ascii=False, indent=2)

    prompt = f"""You are writing a news digest for a Telegram channel.

LANGUAGE: {lang_instructions.get(lang, lang_instructions['en'])}

{style_block}

{HUMANIZER_RULES}

FORMAT (Telegram HTML):
- Header: <b>AI Digest</b>
- Sections: <b>Releases & Tools</b>, <b>Company News</b>, <b>Community</b>, <b>Research</b>
- Show only sections that have news
- Priority markers: use a fire emoji for must-read items (1-3 per digest max), bullet for regular
- Each news item:
  [marker] <b>Title</b>
  2-3 sentences: what happened. Conversational, clear.
  <i>How to apply / what it means.</i> <a href="url">[Source]</a>
- Footer: total count | channel name
- Sort within sections: most important first.

CRITICAL:
- Output ONLY ready Telegram HTML. No markdown, no ```, no explanations.
- Use ONLY tags: <b>, <i>, <a href="url">. No <p>, <br>, <div>.
- Line breaks are regular \\n (not <br>).
- URLs must be EXACT from input data, never invent.

Selected news (JSON). Write the post:

{news_json}"""

    try:
        output = _call_llm(prompt, cfg.get("writer_model", "claude-sonnet-4-20250514"), cfg)

        # Strip code fences
        cleaned = output
        fence_match = re.search(r"```(?:html)?\s*\n(.*?)\n\s*```", cleaned, re.DOTALL)
        if fence_match:
            cleaned = fence_match.group(1)
        else:
            cleaned = re.sub(r"^```(?:html)?\s*\n?", "", cleaned)
            cleaned = re.sub(r"\n?\s*```\s*$", "", cleaned)

        result_text = cleaned.strip()
        if len(result_text) < 100:
            log.error(f"Writer returned too short ({len(result_text)} chars): {result_text[:100]}")
            return ""
        return result_text

    except Exception as e:
        log.error(f"Writer failed: {e}")
        return ""


def render_fallback(selected: list[dict]) -> str:
    """Deterministic fallback renderer (no LLM)."""
    priority_marker = {"red": "\U0001f525", "yellow": "\u2022", "white": "\u2022"}

    categories = {
        "releases": ("Releases & Tools", []),
        "companies": ("Company News", []),
        "community": ("Community", []),
        "research": ("Research", []),
    }

    for item in selected:
        cat = item.get("category", "community")
        if cat not in categories:
            cat = "community"
        categories[cat][1].append(item)

    prio_order = {"red": 0, "yellow": 1, "white": 2}
    for _, items in categories.values():
        items.sort(key=lambda x: prio_order.get(x.get("priority", "white"), 2))

    lines = ["<b>AI Digest</b>\n"]
    for cat_key in ("releases", "companies", "community", "research"):
        label, items = categories[cat_key]
        if not items:
            continue
        lines.append(f"<b>{label}</b>\n")
        for item in items:
            marker = priority_marker.get(item.get("priority", "white"), "\u2022")
            title = escape(item["title"][:120])
            url = item["url"]
            source = escape(item.get("source", "?")[:30])
            summary = escape(item.get("summary", "")[:300])
            takeaway = escape(item.get("takeaway", "")[:200])
            lines.append(f"{marker} <b>{title}</b>")
            if summary:
                lines.append(summary)
            if takeaway:
                lines.append(f'<i>{takeaway}</i> <a href="{url}">[{source}]</a>\n')
            else:
                lines.append(f'<a href="{url}">[{source}]</a>\n')

    lines.append(f"{len(selected)} news")
    return "\n".join(lines)


def analyze_style(samples: list[str], cfg: dict) -> str:
    """Analyze user's writing samples and generate a style profile."""
    samples_text = "\n\n---\n\n".join(samples)

    prompt = f"""Analyze these writing samples and create a concise style profile.
The profile will be used as instructions for an AI to write in this person's voice.

Focus on:
- Language register (formal/casual/mixed)
- Sentence structure patterns (long flowing vs short punchy, etc.)
- Vocabulary preferences (specific words/phrases they use often)
- Tone (direct/cautious, opinionated/neutral, humorous/serious)
- Formatting habits (emojis, bold, lists vs prose)
- What they NEVER do (patterns absent from their writing)

Output a concise style profile (10-15 lines max). Write it as instructions:
"Use X", "Avoid Y", "Prefer Z".

Writing samples:

{samples_text}"""

    return _call_llm(prompt, "claude-sonnet-4-20250514", cfg, max_tokens=1024)
