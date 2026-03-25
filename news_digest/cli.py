"""CLI entry point: setup, run, run --dry-run."""

import argparse
import logging
import sys
from pathlib import Path

from . import __version__

log = logging.getLogger("news_digest")


def main():
    parser = argparse.ArgumentParser(
        prog="news-digest",
        description="AI-powered personalized news digest for Telegram.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=Path("config.yaml"),
        help="Path to config file (default: config.yaml)",
    )

    sub = parser.add_subparsers(dest="command")

    # setup
    sub.add_parser("setup", help="Interactive setup wizard")

    # run
    run_parser = sub.add_parser("run", help="Fetch news and publish digest")
    run_parser.add_argument("--dry-run", action="store_true", help="Preview without sending to Telegram")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.command == "setup":
        from .onboarding import run_setup
        run_setup(args.config)

    elif args.command == "run":
        _run_digest(args.config, dry_run=args.dry_run)

    else:
        parser.print_help()
        sys.exit(1)


def _run_digest(config_path: Path, dry_run: bool = False):
    """Main digest pipeline."""
    from .config import load_config
    from .feeds import (
        fetch_feeds,
        filter_new,
        filter_recent,
        filter_relevant,
        load_published_titles,
        load_seen,
        save_published_titles,
        save_seen,
    )
    from .llm import render_fallback, select_news, write_digest
    from .publisher import send_telegram

    log.info("=== AI News Digest starting ===")

    cfg = load_config(config_path)
    log.info(f"Backend: {cfg.get('backend', 'api')}")

    # 1. Load seen URLs
    seen = load_seen(cfg["state_file"])
    log.info(f"Loaded {len(seen)} seen URLs")

    # 2. Fetch feeds
    all_items = fetch_feeds(cfg["feeds"])
    log.info(f"Fetched {len(all_items)} total items")

    # 3. Filter
    new_items = filter_new(all_items, seen)
    log.info(f"{len(new_items)} new items after dedup")

    recent = filter_recent(new_items, hours=cfg["lookback_hours"])
    log.info(f"{len(recent)} recent items")

    relevant = filter_relevant(recent, cfg.get("keywords", []))
    log.info(f"{len(relevant)} relevant items after keyword filter")

    if not relevant:
        log.info("No new relevant items, skipping digest")
        new_urls = {item["url"] for item in all_items}
        save_seen(seen | new_urls, cfg["state_file"], cfg["max_seen"])
        return

    # 4. Select top news (fast model) with semantic dedup
    published_titles = load_published_titles(cfg["state_file"])
    log.info(f"Loaded {len(published_titles)} published titles for dedup")
    log.info("Selecting top news...")
    selected = select_news(relevant, cfg, published_titles=published_titles)
    if not selected:
        log.error("Selection failed, no news selected")
        return
    log.info(f"Selected {len(selected)} news items")

    # 5. Write digest (quality model + style + humanizer)
    log.info("Writing digest...")
    digest = write_digest(selected, cfg)
    if not digest:
        log.warning("Writer failed, using fallback renderer")
        digest = render_fallback(selected)

    # 6. Output
    if dry_run:
        print("\n" + "=" * 50)
        print("  DRY RUN — Preview (not sent)")
        print("=" * 50 + "\n")
        print(digest)
        print(f"\n({len(digest)} chars)")
    else:
        log.info(f"Sending digest ({len(digest)} chars)")
        send_telegram(digest, cfg["telegram_bot_token"], cfg["telegram_channel"])
        log.info("Digest sent successfully")

    # 7. Save seen URLs + published titles
    new_urls = {item["url"] for item in all_items}
    save_seen(seen | new_urls, cfg["state_file"], cfg["max_seen"])
    new_titles = [item.get("title", "") for item in selected if item.get("title")]
    save_published_titles(new_titles, cfg["state_file"])
    log.info(f"Saved {len(seen | new_urls)} seen URLs, {len(new_titles)} new titles")

    log.info("=== AI News Digest done ===")


if __name__ == "__main__":
    main()
