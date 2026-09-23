"""Entry point: polls Facebook Marketplace via Apify, filters results, detects
new listings, and sends Telegram notifications, forever, on a fixed interval.
"""

import sys
import time
from datetime import datetime, timedelta, timezone

# Listing titles/messages contain emoji; on Windows, stdout can default to a
# legacy code page (cp1252) that can't encode them, crashing the whole
# program. Force UTF-8 output so `python main.py` never dies on a title.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import config
from filters import passes_filters
from notifier import format_posted_at, send_listing_notification
from providers import get_scraper
from storage import (
    dedupe_listings,
    is_seen,
    load_last_scan_at,
    load_seen,
    mark_seen,
    save_last_scan_at,
    save_seen,
)


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")


def _posted_after(posted_at, cutoff_iso: str) -> bool:
    """True if posted_at is at/after cutoff_iso. If posted_at is unknown, we
    never assume it's stale - it's kept (matches the "never invent a value"
    rule used everywhere else in this project).
    """
    if not posted_at:
        return True
    try:
        posted_dt = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
        cutoff_dt = datetime.fromisoformat(cutoff_iso)
    except ValueError:
        return True
    return posted_dt >= cutoff_dt


def run_cycle(cfg: dict, dry_run: bool) -> None:
    start_time = time.perf_counter()
    scan_started_at = datetime.now(timezone.utc)
    log("Starting scan...")

    scraper = get_scraper(cfg, config.APIFY_API_TOKEN, config.BRIGHTDATA_API_KEY)
    listings = scraper.fetch_listings(cfg)
    cost_usd = scraper.get_last_cost_usd()
    cost_note = f" (cost: ${cost_usd:.3f})" if cost_usd is not None else ""
    log(f"Scraper returned {len(listings)} listings{cost_note}")

    # Apify can return the same listing id more than once within a single
    # batch (observed in practice); collapse those before filtering so a
    # duplicated listing never results in more than one notification.
    before_dedupe = len(listings)
    listings = dedupe_listings(listings)
    duplicates_removed = before_dedupe - len(listings)
    if duplicates_removed:
        log(f"{duplicates_removed} duplicate listings removed from this batch")

    filtered = [l for l in listings if passes_filters(l, cfg["filters"])]
    log(f"{len(filtered)} listings passed price filter")

    seen = load_seen()
    new_listings = [l for l in filtered if not is_seen(l, seen)]
    already_seen_count = len(filtered) - len(new_listings)
    if already_seen_count:
        log(f"{already_seen_count} listings already seen, skipped")

    # Facebook's own daysSinceListed filter only has day-level granularity
    # (e.g. "last 24h"), so a listing posted many hours ago can still show up
    # as "new to us" on the very first scan that spots it. To avoid notifying
    # about stale-but-unseen listings, only keep ones posted since our own
    # last successful (non-dry-run) scan. On the very first ever scan (no
    # recorded cutoff), fall back to "now minus one monitoring interval"
    # rather than dumping the whole day's backlog.
    last_scan_at = load_last_scan_at()
    if last_scan_at is None:
        interval_minutes = cfg.get("monitoring", {}).get("interval_minutes", 60)
        last_scan_at = (scan_started_at - timedelta(minutes=interval_minutes)).isoformat()
        log(f"No previous scan recorded; using cutoff now-{interval_minutes}min instead of the full daysSinceListed window")

    before_cutoff = len(new_listings)
    new_listings = [l for l in new_listings if _posted_after(l.posted_at, last_scan_at)]
    stale_skipped = before_cutoff - len(new_listings)
    if stale_skipped:
        log(f"{stale_skipped} listings skipped: posted before the last scan")

    log(f"{len(new_listings)} new listings detected")

    # Chronological order (oldest posted first), so notifications read like a
    # timeline. Listings with an unknown posting date (shouldn't happen with
    # include_listing_details=true, but never assume) are sent last.
    new_listings = sorted(new_listings, key=lambda l: (l.posted_at is None, l.posted_at or ""))

    sent_count = 0
    for listing in new_listings:
        if dry_run:
            # DRY_RUN must have zero side effects: no Telegram, no write to
            # seen_listings.json (no mark_seen call here).
            print("[DRY RUN]")
            print(f"🚗 {listing.title}")
            print(f"{listing.price:,.0f} €".replace(",", " ") if listing.price is not None else "Prix inconnu")
            if listing.year is not None:
                print(f"📅 {listing.year}")
            if listing.mileage is not None:
                print(f"🛣️ {listing.mileage:,} km".replace(",", " "))
            posted_at_text = format_posted_at(listing.posted_at)
            if posted_at_text is not None:
                print(f"🕒 Publiée le {posted_at_text}")
            print(listing.listing_url)
            print()  # blank line between listings for readability
            continue

        if not cfg.get("notifications", {}).get("telegram", True):
            # Telegram disabled in config: nothing was actually delivered, so
            # don't mark as seen either - only a successful send does that.
            continue

        if send_listing_notification(listing, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID):
            sent_count += 1
            mark_seen(listing, seen)
        else:
            log(f"[ERROR] Telegram send failed for listing {listing.id}, will retry next scan")

    if not dry_run:
        if sent_count:
            log(f"{sent_count} Telegram notifications sent")
        save_seen(seen)
        save_last_scan_at(scan_started_at.isoformat())

    duration = time.perf_counter() - start_time
    log(f"Scan finished in {duration:.1f}s")


def main() -> None:
    cfg = config.load_config()
    dry_run = config.is_dry_run()
    if dry_run:
        log("DRY_RUN is enabled: no Telegram notifications will be sent")
    provider = cfg.get("scraper_provider", "apify")
    if provider == "apify" and not cfg.get("apify", {}).get("include_listing_details", True):
        log(
            "include_listing_details is disabled (cost saving): the Actor won't "
            "return a posting timestamp, so recency is only enforced by Facebook's "
            "own daysSinceListed filter, not double-checked in Python"
        )

    interval_minutes = cfg.get("monitoring", {}).get("interval_minutes", 10)

    while True:
        try:
            run_cycle(cfg, dry_run)
        except Exception as exc:  # noqa: BLE001 - one bad cycle must not kill the loop
            log(f"[ERROR] Scan failed: {exc}")

        time.sleep(interval_minutes * 60)


if __name__ == "__main__":
    main()
