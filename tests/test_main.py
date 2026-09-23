import unittest
from unittest.mock import MagicMock, patch

import main
from models import CarListing

CFG = {
    "filters": {"min_price": 100, "max_price": 4000},
    "notifications": {"telegram": True},
    "monitoring": {"interval_minutes": 60},
}


def make_listing(listing_id: str, price=1000, posted_at=None) -> CarListing:
    return CarListing(
        id=listing_id,
        title="Test car",
        price=price,
        year=None,
        mileage=None,
        location="Liege",
        image_url=None,
        listing_url=f"https://example.com/{listing_id}",
        posted_at=posted_at,
        raw_data={},
    )


def make_fake_scraper(listings):
    """A stand-in MarketplaceScraper: main.py only ever calls fetch_listings()
    and get_last_cost_usd() on whatever providers.get_scraper() returns, so
    tests don't need to care whether that's Apify, Bright Data, or a fake.
    """
    scraper = MagicMock()
    scraper.fetch_listings.return_value = listings
    scraper.get_last_cost_usd.return_value = None
    return scraper


def run_cycle_with_mocks(listings, dry_run, seen=None, last_scan_at=None, send_result=True):
    """Run main.run_cycle() with every storage/network dependency mocked out,
    returning the mocks so callers can assert on them. `seen` defaults to a
    fresh dict; pass one in to inspect/pre-seed it.
    """
    if seen is None:
        seen = {}
    fake_scraper = make_fake_scraper(listings)
    with patch("main.get_scraper", return_value=fake_scraper), \
         patch("main.load_seen", return_value=seen), \
         patch("main.save_seen") as mock_save_seen, \
         patch("main.load_last_scan_at", return_value=last_scan_at), \
         patch("main.save_last_scan_at") as mock_save_last_scan_at, \
         patch("main.send_listing_notification", return_value=send_result) as mock_send:
        main.run_cycle(CFG, dry_run=dry_run)
    return {
        "seen": seen,
        "mock_save_seen": mock_save_seen,
        "mock_save_last_scan_at": mock_save_last_scan_at,
        "mock_send": mock_send,
        "fake_scraper": fake_scraper,
    }


class TestDryRunHasNoSideEffects(unittest.TestCase):
    """DRY_RUN=true must never touch seen_listings.json, last_scan.json, or
    Telegram, no matter what Apify returns.
    """

    def test_dry_run_does_not_save_or_notify(self):
        result = run_cycle_with_mocks([make_listing("1")], dry_run=True)

        result["mock_save_seen"].assert_not_called()
        result["mock_save_last_scan_at"].assert_not_called()
        result["mock_send"].assert_not_called()

    def test_real_run_saves_and_notifies(self):
        result = run_cycle_with_mocks([make_listing("1")], dry_run=False)

        result["mock_send"].assert_called_once()
        result["mock_save_seen"].assert_called_once()
        result["mock_save_last_scan_at"].assert_called_once()


class TestMarkSeenOnlyOnSuccessfulSend(unittest.TestCase):
    """A listing must only be recorded in seen_listings.json once Telegram has
    actually confirmed delivery - a failed send must not be marked seen (so
    the next scan retries it).
    """

    def test_failed_telegram_send_does_not_mark_as_seen(self):
        result = run_cycle_with_mocks([make_listing("1")], dry_run=False, send_result=False)

        result["mock_send"].assert_called_once()
        self.assertNotIn("1", result["seen"])

    def test_successful_telegram_send_marks_as_seen(self):
        result = run_cycle_with_mocks([make_listing("1")], dry_run=False, send_result=True)

        self.assertIn("1", result["seen"])


class TestBatchDeduplicationInRunCycle(unittest.TestCase):
    def test_duplicate_ids_in_same_batch_notify_once_each(self):
        listings = [
            make_listing("123"),
            make_listing("456"),
            make_listing("123"),
            make_listing("789"),
            make_listing("456"),
        ]
        result = run_cycle_with_mocks(listings, dry_run=False)

        self.assertEqual(result["mock_send"].call_count, 3)


class TestChronologicalNotificationOrder(unittest.TestCase):
    """New listings must be notified oldest-posted-first, so the Telegram
    chat reads like a timeline. Unknown dates go last.
    """

    # A cutoff far before any of these tests' fixed timestamps, so the
    # "since last scan" filter (tested separately below) never interferes
    # with what's being tested here: notification ordering.
    ANY_TIME_PASSES = "2000-01-01T00:00:00+00:00"

    def test_notifications_sent_oldest_first(self):
        listings = [
            make_listing("newest", posted_at="2026-09-23T20:00:00.000Z"),
            make_listing("oldest", posted_at="2026-09-23T10:00:00.000Z"),
            make_listing("middle", posted_at="2026-09-23T15:00:00.000Z"),
        ]
        result = run_cycle_with_mocks(listings, dry_run=False, last_scan_at=self.ANY_TIME_PASSES)

        notified_ids = [call.args[0].id for call in result["mock_send"].call_args_list]
        self.assertEqual(notified_ids, ["oldest", "middle", "newest"])

    def test_unknown_dates_are_sent_last(self):
        listings = [
            make_listing("unknown", posted_at=None),
            make_listing("known", posted_at="2026-09-23T10:00:00.000Z"),
        ]
        result = run_cycle_with_mocks(listings, dry_run=False, last_scan_at=self.ANY_TIME_PASSES)

        notified_ids = [call.args[0].id for call in result["mock_send"].call_args_list]
        self.assertEqual(notified_ids, ["known", "unknown"])


class TestSinceLastScanCutoff(unittest.TestCase):
    """Facebook's daysSinceListed filter only has day-level granularity, so a
    listing posted hours ago can still appear as "new to us" on the first
    scan that spots it. Only listings posted since our own last successful
    scan should ever be notified.
    """

    def test_listing_posted_before_last_scan_is_skipped(self):
        listings = [make_listing("old", posted_at="2026-09-23T09:00:00.000Z")]
        result = run_cycle_with_mocks(
            listings, dry_run=False, last_scan_at="2026-09-23T12:00:00+00:00"
        )

        result["mock_send"].assert_not_called()

    def test_listing_posted_after_last_scan_is_notified(self):
        listings = [make_listing("fresh", posted_at="2026-09-23T13:00:00.000Z")]
        result = run_cycle_with_mocks(
            listings, dry_run=False, last_scan_at="2026-09-23T12:00:00+00:00"
        )

        result["mock_send"].assert_called_once()

    def test_first_ever_scan_uses_now_minus_interval_as_cutoff(self):
        import main as main_module
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        too_old = (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        recent = (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        listings = [make_listing("too_old", posted_at=too_old), make_listing("recent", posted_at=recent)]

        # last_scan_at=None => no last_scan.json yet => fall back to
        # now - interval_minutes (60 in CFG), so only "recent" should pass.
        result = run_cycle_with_mocks(listings, dry_run=False, last_scan_at=None)

        notified_ids = [call.args[0].id for call in result["mock_send"].call_args_list]
        self.assertEqual(notified_ids, ["recent"])

    def test_unknown_posted_at_is_never_treated_as_stale(self):
        listings = [make_listing("unknown_date", posted_at=None)]
        result = run_cycle_with_mocks(
            listings, dry_run=False, last_scan_at="2026-09-23T12:00:00+00:00"
        )

        result["mock_send"].assert_called_once()


if __name__ == "__main__":
    unittest.main()
