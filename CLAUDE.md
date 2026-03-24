# AI News Digest — Claude Code Instructions

You are setting up a personalized AI news digest for a Telegram channel.

## First Run (Onboarding)

If `config.yaml` does not exist, run the onboarding flow below. This is a **conversation**, not a form — ask naturally, clarify, suggest, and adapt. Don't dump all questions at once.

### Onboarding Flow

**1. Welcome & Backend**

Introduce yourself. Explain what the tool does in 2-3 sentences. Then ask:
- Do they have a Claude Code Max/Team subscription (free, uses `claude` CLI) or prefer to use an Anthropic API key (pay per token)?
- If Claude Code: verify `claude` is in PATH with `which claude`
- If API: ask for the key, verify it works with a test call

**2. Telegram Setup**

Ask if they already have a Telegram bot and channel, or need to create them. Guide step by step:
- Create bot via @BotFather → /newbot → copy token
- Create channel (or use existing)
- Add bot as admin with "Post Messages" permission
- Verify by sending a test message to the channel via Bot API

If something fails — help debug (bot not admin, wrong channel ID, etc).

**3. Topics & Feeds**

Ask what topics they care about. Have a conversation — don't just list options. Examples:
- "What industry are you in?"
- "What do you want to stay on top of?"
- "Any specific blogs, subreddits, or newsletters you already follow?"

Available topic packs (in `news_digest/llm.py` → `FEED_SUGGESTIONS`):
AI/ML, AI tools, startups, product management, web development, cybersecurity, crypto, fintech, github trending, russian AI

Suggest feeds based on their answers. They can also add custom RSS/Atom URLs.

**4. Writing Style**

This is the most important step. Ask them to share 3-5 examples of their writing — posts, tweets, messages, anything that shows how they naturally communicate.

Be encouraging: "The digest will write in YOUR voice, not generic AI text. The more examples you share, the better it captures your style."

If they don't have examples ready, suggest:
- Copy a few recent Telegram/Twitter/LinkedIn posts
- Write a quick paragraph about any topic in their natural voice
- Share a message they sent to a friend about something they're excited about

Once you have samples, call `analyze_style()` from `news_digest/llm.py` to generate a style profile. Show them the result and ask if it captures their voice correctly.

**5. Preferences**

Ask casually (with sensible defaults):
- Language for the digest (en/ru)
- How many news items per digest (default 5-7)
- Selection model (haiku = fast + cheap, default)
- Writing model (sonnet = good quality default, opus = best but costs more)

**6. Save & Test**

Write `config.yaml` using `news_digest/config.py` → `save_config()`.
Run a dry-run: `python -m news_digest run --dry-run --config config.yaml`
Show them the result. Ask if they like the tone, length, format.
If not — adjust style_profile in config and re-run.

When happy, do a real run: `python -m news_digest run`

**7. Scheduling (optional)**

Ask if they want it to run automatically. Suggest:
- cron (Linux/Mac): `0 8 * * * cd /path && python -m news_digest run`
- launchd (Mac): create a plist
- They can always run manually whenever they want

## Existing Config

If `config.yaml` exists, the tool is already set up. Available commands:
- `python -m news_digest run` — fetch news and publish
- `python -m news_digest run --dry-run` — preview without sending
- Edit `config.yaml` to change feeds, style, models, etc.

## Key Files

| File | Purpose |
|------|---------|
| `config.yaml` | All settings (created during onboarding, gitignored) |
| `config.example.yaml` | Reference with all available options |
| `news_digest/llm.py` | LLM calls, FEED_SUGGESTIONS dict, HUMANIZER_RULES, analyze_style() |
| `news_digest/config.py` | save_config(), load_config(), validate() |
| `news_digest/feeds.py` | RSS fetching, dedup, filtering |
| `news_digest/publisher.py` | Telegram Bot API sending |
| `news_digest/cli.py` | CLI entry point (setup / run) |

## Style System

The digest avoids AI-sounding text via two mechanisms:
1. **User's style profile** — generated from their writing samples during onboarding
2. **Humanizer rules** — 12 anti-AI patterns from blader/humanizer (embedded in HUMANIZER_RULES constant)

Both are injected into the writing prompt. The result should read like a human wrote it.

## Config Schema

```yaml
backend: "api" | "claude-code"        # LLM backend
anthropic_api_key: "sk-ant-..."       # only for "api" backend
claude_code_path: "claude"            # only for "claude-code" backend
telegram_bot_token: "123456:ABC..."   # from @BotFather
telegram_channel: "@mychannel"        # channel ID
language: "en" | "ru"
digest_size: 7                        # news per digest
selector_model: "claude-haiku-4-5-20251001"
writer_model: "claude-sonnet-4-20250514"
lookback_hours: 48
feeds: {name: url, ...}              # RSS/Atom feeds
keywords: [...]                       # relevance filter (empty = keep all)
style_profile: "..."                  # auto-generated from samples
style_samples: [...]                  # user's writing examples
state_file: "~/.config/news-digest/seen.json"
max_seen: 1000
```
