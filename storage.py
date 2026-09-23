"""Tracks which listings have already been seen/notified, persisted to a JSON
file so restarts never re-send a notification for the same listing.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from models import CarListing

BASE_DIR = Path(__file__).resolve().parent
SEEN_LISTINGS_PATH = BASE_DIR / "seen_listings.json"
LAST_SCAN_PATH = BASE_DIR / "last_scan.json"


def load_seen(path: Path = SEEN_LISTINGS_PATH) -> Dict[str, dict]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[ERROR] Failed to read {path}, starting with empty state: {exc}")
        return {}


def save_seen(seen: Dict[str, dict], path: Path = SEEN_LISTINGS_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)


def is_seen(listing: CarListing, seen: Dict[str, dict]) -> bool:
    return listing.id in seen


def mark_seen(listing: CarListing, seen: Dict[str, dict]) -> None:
    seen[listing.id] = {
        "first_seen": datetime.now(timezone.utc).isoformat(),
        "url": listing.listing_url,
    }


def load_last_scan_at(path: Path = LAST_SCAN_PATH) -> Optional[str]:
    """Return the ISO timestamp of the last successful (non-dry-run) scan, or
    None if there hasn't been one yet.
    """
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("last_scan_at")
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[ERROR] Failed to read {path}: {exc}")
        return None


def save_last_scan_at(timestamp_iso: str, path: Path = LAST_SCAN_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"last_scan_at": timestamp_iso}, f, indent=2)


def dedupe_listings(listings: List[CarListing]) -> List[CarListing]:
    """Collapse listings sharing the same id down to a single entry, keeping
    the first occurrence and its original order. Apify can return the same
    listing id more than once within a single batch; without this, the same
    listing could be notified about more than once in a single scan.
    """
    deduped = []
    seen_ids = set()
    for listing in listings:
        if listing.id in seen_ids:
            continue
        seen_ids.add(listing.id)
        deduped.append(listing)
    return deduped
