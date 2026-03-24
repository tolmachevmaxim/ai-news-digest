"""Configuration loading and validation."""

import os
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")

DEFAULTS = {
    "backend": "api",  # "api" (Anthropic API key) or "claude-code" (Max subscription)
    "language": "en",
    "digest_size": 7,
    "lookback_hours": 48,
    "selector_model": "claude-haiku-4-5-20251001",
    "writer_model": "claude-sonnet-4-20250514",
    "claude_code_path": "claude",  # path to claude CLI binary
    "state_file": "~/.config/news-digest/seen.json",
    "max_seen": 1000,
    "keywords": [],
    "topics": [],
    "feeds": {},
    "style_profile": "",
    "style_samples": [],
}


def load_config(path: Path | None = None) -> dict:
    """Load config from YAML file, apply defaults."""
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found: {path}\n"
            "Run 'python -m news_digest setup' to create one."
        )
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}

    # Apply defaults
    for key, default in DEFAULTS.items():
        cfg.setdefault(key, default)

    # Env var overrides (useful for CI/secrets)
    if os.environ.get("ANTHROPIC_API_KEY"):
        cfg["anthropic_api_key"] = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        cfg["telegram_bot_token"] = os.environ["TELEGRAM_BOT_TOKEN"]

    # Expand ~ in paths
    cfg["state_file"] = str(Path(cfg["state_file"]).expanduser())

    validate(cfg)
    return cfg


def validate(cfg: dict):
    """Check required fields."""
    backend = cfg.get("backend", "api")

    # API backend requires API key; claude-code does not
    if backend == "api":
        api_key = cfg.get("anthropic_api_key", "")
        if not api_key or api_key.startswith("sk-ant-..."):
            raise ValueError(
                "Missing anthropic_api_key for 'api' backend.\n"
                "Run 'python -m news_digest setup' or edit config.yaml."
            )

    missing = []
    for key in ("telegram_bot_token", "telegram_channel"):
        if not cfg.get(key) or cfg[key] in ("123456:ABC-DEF...",):
            missing.append(key)
    if missing:
        raise ValueError(
            f"Missing required config: {', '.join(missing)}\n"
            "Run 'python -m news_digest setup' or edit config.yaml."
        )
    if not cfg.get("feeds"):
        raise ValueError("No feeds configured. Add RSS/Atom feeds to config.yaml.")


def save_config(cfg: dict, path: Path | None = None):
    """Save config to YAML file."""
    path = path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
