"""Loads configuration from config.json and environment variables (.env)."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

load_dotenv(BASE_DIR / ".env")


def load_config() -> dict:
    """Load config.json from disk. Raises if missing or invalid."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_env(name: str, default: str = None, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def is_dry_run() -> bool:
    return get_env("DRY_RUN", "true").strip().lower() in ("1", "true", "yes")


def is_run_once() -> bool:
    """True if the program should execute exactly one monitoring cycle and
    exit, instead of looping forever. Set explicitly via RUN_ONCE=true, or
    implied automatically by GITHUB_ACTIONS (set by GitHub Actions itself on
    every run) so a workflow doesn't need to remember to set RUN_ONCE too.
    """
    explicit = get_env("RUN_ONCE", "false").strip().lower() in ("1", "true", "yes")
    return explicit or bool(get_env("GITHUB_ACTIONS"))


# Convenience accessors for secrets used across the app.
APIFY_API_TOKEN = get_env("APIFY_API_TOKEN")
TELEGRAM_BOT_TOKEN = get_env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = get_env("TELEGRAM_CHAT_ID")
BRIGHTDATA_API_KEY = get_env("BRIGHTDATA_API_KEY")
