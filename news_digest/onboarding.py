"""Interactive onboarding — AI-guided setup that learns your style."""

import shutil
import sys

from .config import save_config
from .llm import FEED_SUGGESTIONS, analyze_style


def run_setup(config_path=None):
    """Interactive setup wizard."""
    from .config import DEFAULT_CONFIG_PATH

    config_path = config_path or DEFAULT_CONFIG_PATH
    cfg = {}

    print("\n" + "=" * 50)
    print("  AI News Digest — Setup")
    print("=" * 50)

    # Step 1: Backend choice
    print("\n--- Step 1: LLM Backend ---")
    print("  1) Anthropic API key (pay per token)")
    print("  2) Claude Code CLI  (free with Max/Team subscription)")
    choice = _ask("Choose [1/2]", default="1")

    if choice == "2":
        cfg["backend"] = "claude-code"
        # Find claude binary
        claude_path = shutil.which("claude")
        if claude_path:
            print(f"  Found Claude Code at: {claude_path}")
            cfg["claude_code_path"] = claude_path
        else:
            print("  'claude' not found in PATH.")
            cfg["claude_code_path"] = _ask("Path to claude binary")
        # Verify
        try:
            from .llm import _call_claude_code
            result = _call_claude_code("Say 'ok'", "claude-haiku-4-5-20251001", cfg, timeout=30)
            print(f"  Claude Code verified: {result[:20]}")
        except Exception as e:
            print(f"  Claude Code error: {e}")
            print("  Make sure Claude Code is installed: npm install -g @anthropic-ai/claude-code")
            sys.exit(1)
    else:
        cfg["backend"] = "api"
        print("\nGet your API key at https://console.anthropic.com/settings/keys")
        api_key = _ask("API key", secret=True)
        cfg["anthropic_api_key"] = api_key
        # Verify
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                messages=[{"role": "user", "content": "Say 'ok'"}],
            )
            print("  API key verified")
        except Exception as e:
            print(f"  API key error: {e}")
            sys.exit(1)

    # Step 2: Telegram
    print("\n--- Step 2: Telegram ---")
    print("  You need a Telegram bot + a channel. Here's how:\n")
    print("  1. Open Telegram, search for @BotFather")
    print("  2. Send /newbot, pick a name and username")
    print("  3. Copy the bot token (looks like 123456:ABC-DEF...)")
    print()
    cfg["telegram_bot_token"] = _ask("Bot token", secret=True)

    print()
    print("  4. Create a Telegram channel (or use an existing one)")
    print("  5. Go to channel settings -> Administrators -> Add the bot as admin")
    print("     (it needs 'Post Messages' permission)")
    print()
    cfg["telegram_channel"] = _ask("Channel (e.g. @mychannel or -100123456)")

    # Verify by sending a test message
    print("\n  Verifying bot + channel...")
    try:
        import httpx
        resp = httpx.post(
            f"https://api.telegram.org/bot{cfg['telegram_bot_token']}/sendMessage",
            json={
                "chat_id": cfg["telegram_channel"],
                "text": "AI News Digest connected. Setup in progress...",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            print("  Test message sent to channel")
        else:
            error = resp.json().get("description", resp.text[:200])
            print(f"  Warning: {error}")
            print("  Common fixes:")
            print("    - Make sure the bot is added as admin to the channel")
            print("    - For public channels use @username, for private use the numeric ID")
            proceed = _ask("Continue anyway? (y/n)", default="y")
            if proceed.lower() != "y":
                sys.exit(1)
    except Exception as e:
        print(f"  Could not verify: {e}")
        print("  You can fix this later in config.yaml and test with --dry-run")

    # Step 3: Language
    print("\n--- Step 3: Language ---")
    cfg["language"] = _ask("Digest language (en/ru)", default="en")

    # Step 4: Topics & Feeds
    print("\n--- Step 4: Topics & Feeds ---")
    available = ", ".join(FEED_SUGGESTIONS.keys())
    print(f"Available topic packs: {available}")
    print("Or add custom RSS feeds later in config.yaml.")
    topics_input = _ask("Your topics (comma-separated)", default="AI/ML")
    topics = [t.strip() for t in topics_input.split(",")]
    cfg["topics"] = topics

    # Collect feeds from selected topics
    feeds = {}
    for topic in topics:
        matched = FEED_SUGGESTIONS.get(topic)
        if not matched:
            for key, val in FEED_SUGGESTIONS.items():
                if key.lower() == topic.lower():
                    matched = val
                    break
        if matched:
            print(f"\n  Feeds for '{topic}':")
            for name, url in matched.items():
                print(f"    + {name}")
            feeds.update(matched)
        else:
            print(f"  No preset feeds for '{topic}' — add custom feeds in config.yaml")

    if not feeds:
        print("\n  No feeds selected. Adding defaults (AI/ML)...")
        feeds = FEED_SUGGESTIONS.get("AI/ML", {})

    cfg["feeds"] = feeds

    # Step 5: Keywords
    print("\n--- Step 5: Keywords ---")
    print("Keywords filter out irrelevant items from general feeds.")
    print("Leave empty to keep all items.")
    kw_input = _ask("Keywords (comma-separated, or empty)", default="")
    cfg["keywords"] = [k.strip() for k in kw_input.split(",") if k.strip()] if kw_input else []

    # Step 6: Writing Style
    print("\n--- Step 6: Your Writing Style ---")
    print("Paste 3-5 examples of YOUR writing (posts, tweets, messages).")
    print("This teaches the digest to write in YOUR voice, not generic AI text.")
    print("Each example: type/paste text, then press Enter twice (empty line) to finish.\n")

    samples = []
    for i in range(5):
        print(f"  Example {i + 1} (empty line to finish, 'skip' to stop collecting):")
        lines = []
        while True:
            line = input("  > ")
            if line.strip().lower() == "skip":
                break
            if line == "" and lines:
                break
            if line:
                lines.append(line)
        if not lines or (len(lines) == 1 and lines[0].lower() == "skip"):
            break
        samples.append("\n".join(lines))
        print(f"  Saved example {i + 1} ({len(samples[-1])} chars)\n")

    cfg["style_samples"] = samples

    if samples:
        print("  Analyzing your style...")
        try:
            profile = analyze_style(samples, cfg)
            cfg["style_profile"] = profile
            print("\n  Style profile:\n")
            for line in profile.split("\n"):
                print(f"    {line}")
        except Exception as e:
            print(f"  Style analysis failed: {e}")
            cfg["style_profile"] = ""
    else:
        print("  No samples provided. Digest will use neutral style + humanizer rules.")
        cfg["style_profile"] = ""

    # Step 7: Preferences
    print("\n--- Step 7: Preferences ---")
    cfg["digest_size"] = int(_ask("News per digest", default="7"))
    cfg["selector_model"] = _ask("Selection model", default="claude-haiku-4-5-20251001")
    cfg["writer_model"] = _ask("Writing model", default="claude-sonnet-4-20250514")
    cfg["lookback_hours"] = 48
    cfg["state_file"] = "~/.config/news-digest/seen.json"
    cfg["max_seen"] = 1000

    # Save
    save_config(cfg, config_path)
    print(f"\n Config saved to {config_path}")
    print("\n Next steps:")
    print(f"   Preview:  python -m news_digest run --dry-run")
    print(f"   Publish:  python -m news_digest run")
    print(f"   Edit:     open {config_path}")
    print()


def _ask(label: str, default: str = "", secret: bool = False) -> str:
    """Prompt user for input."""
    suffix = f" [{default}]" if default else ""
    try:
        if secret:
            import getpass
            value = getpass.getpass(f"  {label}{suffix}: ")
        else:
            value = input(f"  {label}{suffix}: ")
    except (EOFError, KeyboardInterrupt):
        print("\n  Setup cancelled.")
        sys.exit(0)
    return value.strip() or default
