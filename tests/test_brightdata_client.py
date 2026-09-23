import unittest
from unittest.mock import MagicMock, patch

from brightdata_client import (
    _download_snapshot,
    _parse_records,
    _wait_for_snapshot,
    fetch_marketplace_listings,
    parse_brightdata_listing,
)


class TestParseBrightdataListing(unittest.TestCase):
    """Shape observed from a real validated call against Bright Data's
    Facebook Marketplace discovery endpoint (dataset gd_lvt9iwuh6fbcwmx1a,
    type=discover_new&discover_by=url) on 2026-09-23.
    """

    def test_maps_all_known_fields(self):
        raw = {
            "url": "https://www.facebook.com/marketplace/item/1417126663932989",
            "title": "Chevrolet Kalos",
            "initial_price": 1000,
            "final_price": 1000,
            "currency": "EUR",
            "product_id": "1417126663932989",
            "condition": "PC_USED_FAIR",
            "description": "Chevrolet Kalos de 2006 a vendre, elle a 163000 km",
            "location": "Seraing, WAL",
            "country_code": "BE",
            "images": ["https://example.com/photo1.jpg", "https://example.com/photo2.jpg"],
            "car_miles": None,
            "transmission": None,
            "is_sold": False,
            "listing_date": "2026-09-23T21:14:39.000Z",
        }
        listing = parse_brightdata_listing(raw)

        self.assertEqual(listing.id, "1417126663932989")
        self.assertEqual(listing.title, "Chevrolet Kalos")
        self.assertEqual(listing.price, 1000.0)
        self.assertEqual(listing.location, "Seraing, WAL")
        self.assertEqual(listing.image_url, "https://example.com/photo1.jpg")
        self.assertEqual(
            listing.listing_url, "https://www.facebook.com/marketplace/item/1417126663932989"
        )
        self.assertEqual(listing.posted_at, "2026-09-23T21:14:39.000Z")
        self.assertEqual(listing.year, 2006)
        # car_miles was null in this record, so mileage falls back to the
        # text parser, which finds "163000 km" in the description.
        self.assertEqual(listing.mileage, 163000)

    def test_car_miles_field_is_preferred_over_text_parsing(self):
        raw = {
            "product_id": "1",
            "title": "Some car",
            "final_price": 5000,
            "car_miles": 88000,
            "description": "mentions 12345 km somewhere else entirely",
        }
        listing = parse_brightdata_listing(raw)
        self.assertEqual(listing.mileage, 88000)

    def test_missing_product_id_is_skipped(self):
        raw = {"title": "No id here", "final_price": 1000}
        self.assertIsNone(parse_brightdata_listing(raw))

    def test_missing_price_is_kept_but_price_is_none(self):
        raw = {"product_id": "123", "title": "No price mentioned"}
        listing = parse_brightdata_listing(raw)
        self.assertIsNotNone(listing)
        self.assertIsNone(listing.price)

    def test_missing_images_gives_no_image_url(self):
        raw = {"product_id": "123", "title": "Car", "final_price": 500, "images": []}
        listing = parse_brightdata_listing(raw)
        self.assertIsNone(listing.image_url)

    def test_never_invents_year_or_mileage(self):
        raw = {"product_id": "123", "title": "Golf", "final_price": 800, "description": "Bon état"}
        listing = parse_brightdata_listing(raw)
        self.assertIsNone(listing.year)
        self.assertIsNone(listing.mileage)


class TestParseRecords(unittest.TestCase):
    """Bright Data's sync discovery response is NDJSON (one JSON object per
    line) - confirmed against a real call, NOT a wrapped JSON array.
    """

    def test_parses_ndjson_lines(self):
        text = '{"product_id": "1"}\n{"product_id": "2"}\n'
        records = _parse_records(text)
        self.assertEqual(records, [{"product_id": "1"}, {"product_id": "2"}])

    def test_parses_plain_json_array_as_fallback(self):
        text = '[{"product_id": "1"}, {"product_id": "2"}]'
        records = _parse_records(text)
        self.assertEqual(records, [{"product_id": "1"}, {"product_id": "2"}])

    def test_parses_single_json_object_as_fallback(self):
        text = '{"snapshot_id": "sd_abc"}'
        records = _parse_records(text)
        self.assertEqual(records, [{"snapshot_id": "sd_abc"}])

    def test_empty_response_is_empty_list(self):
        self.assertEqual(_parse_records(""), [])
        self.assertEqual(_parse_records("   "), [])


class TestWaitForSnapshot(unittest.TestCase):
    """Fallback path for large discovery jobs that don't complete
    synchronously (Bright Data returns a lone snapshot_id instead of records).
    """

    def test_returns_when_status_ready(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"status": "ready"}
        response.raise_for_status.return_value = None

        with patch("brightdata_client.requests.get", return_value=response):
            _wait_for_snapshot("snap_abc", {}, {}, 30)  # should not raise

    def test_raises_when_job_failed(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"status": "failed"}
        response.raise_for_status.return_value = None

        with patch("brightdata_client.requests.get", return_value=response):
            with self.assertRaises(RuntimeError):
                _wait_for_snapshot("snap_abc", {}, {}, 30)

    def test_polls_until_ready(self):
        running = MagicMock(status_code=200)
        running.json.return_value = {"status": "running"}
        running.raise_for_status.return_value = None
        ready = MagicMock(status_code=200)
        ready.json.return_value = {"status": "ready"}
        ready.raise_for_status.return_value = None

        with patch("brightdata_client.requests.get", side_effect=[running, ready]), \
             patch("brightdata_client.time.sleep"):
            _wait_for_snapshot("snap_abc", {}, {"poll_interval_seconds": 0.01}, 30)  # should not raise


class TestDownloadSnapshot(unittest.TestCase):
    def test_returns_list_of_records(self):
        response = MagicMock(status_code=200)
        response.json.return_value = [{"product_id": "1"}]
        response.raise_for_status.return_value = None

        with patch("brightdata_client.requests.get", return_value=response):
            items = _download_snapshot("snap_abc", {}, 30)

        self.assertEqual(items, [{"product_id": "1"}])

    def test_raises_on_unexpected_shape(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"unexpected": "object"}
        response.raise_for_status.return_value = None

        with patch("brightdata_client.requests.get", return_value=response):
            with self.assertRaises(RuntimeError):
                _download_snapshot("snap_abc", {}, 30)


class TestFetchMarketplaceListingsEndToEnd(unittest.TestCase):
    def _config(self, **brightdata_overrides):
        return {
            "search": {"location_id": "112128398804880", "category": "vehicles"},
            "brightdata": {"poll_interval_seconds": 0.01, **brightdata_overrides},
        }

    def test_sync_ndjson_response_returns_carlistings(self):
        response = MagicMock(status_code=200)
        response.text = (
            '{"product_id": "1", "title": "Golf", "final_price": 1500, "url": "https://x/1"}\n'
            '{"product_id": "2", "title": "Clio", "final_price": 900, "url": "https://x/2"}\n'
        )
        response.raise_for_status.return_value = None

        with patch("brightdata_client.requests.post", return_value=response) as mock_post:
            listings = fetch_marketplace_listings(self._config(), "fake-api-key")

        self.assertEqual(len(listings), 2)
        self.assertEqual({l.id for l in listings}, {"1", "2"})
        # Confirms the discovery-specific query params are sent.
        sent_params = mock_post.call_args.kwargs["params"]
        self.assertEqual(sent_params["type"], "discover_new")
        self.assertEqual(sent_params["discover_by"], "url")

    def test_falls_back_to_async_snapshot_when_only_snapshot_id_is_returned(self):
        sync_response = MagicMock(status_code=200)
        sync_response.text = '{"snapshot_id": "snap_abc"}'
        sync_response.raise_for_status.return_value = None

        progress_response = MagicMock(status_code=200)
        progress_response.json.return_value = {"status": "ready"}
        progress_response.raise_for_status.return_value = None

        snapshot_response = MagicMock(status_code=200)
        snapshot_response.json.return_value = [
            {"product_id": "1", "title": "Golf", "final_price": 1500, "url": "https://x/1"}
        ]
        snapshot_response.raise_for_status.return_value = None

        with patch("brightdata_client.requests.post", return_value=sync_response), \
             patch("brightdata_client.requests.get", side_effect=[progress_response, snapshot_response]):
            listings = fetch_marketplace_listings(self._config(), "fake-api-key")

        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0].id, "1")

    def test_sends_limit_per_input_when_results_limit_configured(self):
        response = MagicMock(status_code=200)
        response.text = ""
        response.raise_for_status.return_value = None

        with patch("brightdata_client.requests.post", return_value=response) as mock_post:
            fetch_marketplace_listings(self._config(results_limit=15), "fake-api-key")

        sent_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload["limit_per_input"], 15)

    def test_sends_country_from_config(self):
        response = MagicMock(status_code=200)
        response.text = ""
        response.raise_for_status.return_value = None

        with patch("brightdata_client.requests.post", return_value=response) as mock_post:
            fetch_marketplace_listings(self._config(country="BE"), "fake-api-key")

        sent_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload["input"][0]["country"], "BE")


if __name__ == "__main__":
    unittest.main()
