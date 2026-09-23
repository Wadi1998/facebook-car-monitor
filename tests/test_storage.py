import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from models import CarListing
from storage import (
    dedupe_listings,
    is_seen,
    load_last_scan_at,
    load_seen,
    mark_seen,
    save_last_scan_at,
    save_seen,
)


def make_listing(listing_id: str) -> CarListing:
    return CarListing(
        id=listing_id,
        title="Test car",
        price=10000,
        year=2018,
        mileage=100000,
        location="Liege",
        image_url=None,
        listing_url=f"https://example.com/{listing_id}",
        posted_at=None,
        raw_data={},
    )


class TestDuplicateDetection(unittest.TestCase):
    def test_new_listing_is_not_seen(self):
        seen = {}
        listing = make_listing("123")
        self.assertFalse(is_seen(listing, seen))

    def test_marking_seen_prevents_future_duplicates(self):
        seen = {}
        listing = make_listing("123")
        mark_seen(listing, seen)
        self.assertTrue(is_seen(listing, seen))

    def test_repeated_scrape_of_same_listing_is_not_seen_twice(self):
        seen = {}
        listing = make_listing("123")

        # First cycle: new listing appears, gets marked as seen.
        self.assertFalse(is_seen(listing, seen))
        mark_seen(listing, seen)

        # Second cycle: scraper returns the same listing again.
        self.assertTrue(is_seen(listing, seen))

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seen_listings.json"
            seen = {}
            mark_seen(make_listing("123"), seen)
            save_seen(seen, path=path)

            loaded = load_seen(path=path)
            self.assertIn("123", loaded)
            self.assertEqual(loaded["123"]["url"], "https://example.com/123")

    def test_load_missing_file_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "does_not_exist.json"
            self.assertEqual(load_seen(path=path), {})


class TestBatchDeduplication(unittest.TestCase):
    """Apify can return the same listing id more than once within a single
    batch; dedupe_listings() must collapse those before anything else runs.
    """

    def test_duplicate_ids_collapse_to_one_entry(self):
        listings = [
            make_listing("123"),
            make_listing("456"),
            make_listing("123"),
            make_listing("789"),
            make_listing("456"),
        ]
        deduped = dedupe_listings(listings)
        self.assertEqual([l.id for l in deduped], ["123", "456", "789"])

    def test_no_duplicates_is_unchanged(self):
        listings = [make_listing("1"), make_listing("2"), make_listing("3")]
        self.assertEqual(dedupe_listings(listings), listings)

    def test_empty_list(self):
        self.assertEqual(dedupe_listings([]), [])


class TestLastScanCursor(unittest.TestCase):
    def test_returns_none_when_never_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "last_scan.json"
            self.assertIsNone(load_last_scan_at(path=path))

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "last_scan.json"
            save_last_scan_at("2026-09-23T21:00:00+00:00", path=path)
            self.assertEqual(load_last_scan_at(path=path), "2026-09-23T21:00:00+00:00")


class TestResilientWrites(unittest.TestCase):
    """A write failure (full disk, permissions, ...) must be logged clearly,
    never allowed to crash the cycle - the next cycle should still get a
    chance to run.
    """

    def test_save_seen_does_not_raise_on_write_failure(self):
        bad_path = Path("/this/path/does/not/exist/seen_listings.json")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            save_seen({"123": {"first_seen": "now", "url": "x"}}, path=bad_path)
        self.assertIn("[ERROR]", buffer.getvalue())

    def test_save_last_scan_at_does_not_raise_on_write_failure(self):
        bad_path = Path("/this/path/does/not/exist/last_scan.json")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            save_last_scan_at("2026-09-23T21:00:00+00:00", path=bad_path)
        self.assertIn("[ERROR]", buffer.getvalue())

    def test_save_seen_logs_and_swallows_generic_os_error(self):
        buffer = io.StringIO()
        with patch("storage.open", side_effect=OSError("disk full")), redirect_stdout(buffer):
            save_seen({}, path=Path("irrelevant.json"))
        self.assertIn("[ERROR]", buffer.getvalue())
        self.assertIn("disk full", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
