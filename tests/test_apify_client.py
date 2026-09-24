import unittest
from unittest.mock import MagicMock, patch

from apify_client import build_search_url, fetch_marketplace_listings, get_last_run_cost_usd, parse_apify_listing

FAKE_TOKEN = "apify_api_SUPER-SECRET-TOKEN"


class TestBuildSearchUrl(unittest.TestCase):
    def test_builds_url_from_individual_fields_by_default(self):
        url = build_search_url({
            "location_id": "112128398804880",
            "category": "vehicles",
            "radius_km": 150,
            "days_since_listed": 1,
        })
        self.assertEqual(
            url,
            "https://www.facebook.com/marketplace/112128398804880/vehicles"
            "?daysSinceListed=1&radius=150&sortBy=creation_time_descend&exact=false",
        )

    def test_respects_overridden_sort_by_and_exact(self):
        url = build_search_url({
            "location_id": "1",
            "category": "vehicles",
            "sort_by": "price_ascend",
            "exact": True,
        })
        self.assertIn("sortBy=price_ascend", url)
        self.assertIn("exact=true", url)

    def test_custom_url_overrides_everything_else(self):
        custom = "https://www.facebook.com/marketplace/1/search?query=bmw&minPrice=1000"
        url = build_search_url({
            "custom_url": custom,
            "location_id": "should-be-ignored",
            "radius_km": 999,
        })
        self.assertEqual(url, custom)

    def test_empty_custom_url_falls_back_to_built_url(self):
        url = build_search_url({"custom_url": "", "location_id": "1"})
        self.assertTrue(url.startswith("https://www.facebook.com/marketplace/1/vehicles"))

    def test_query_builds_search_url_instead_of_category_page(self):
        url = build_search_url({
            "location_id": "112128398804880",
            "query": "Véhicules",
            "category_id": "546583916084032",
            "radius_km": 150,
            "days_since_listed": 1,
        })
        self.assertTrue(url.startswith("https://www.facebook.com/marketplace/112128398804880/search/?"))
        self.assertIn("query=V%C3%A9hicules", url)
        self.assertIn("category_id=546583916084032", url)
        self.assertIn("radius=150", url)
        self.assertIn("daysSinceListed=1", url)

    def test_query_without_category_id_still_works(self):
        url = build_search_url({"location_id": "1", "query": "voiture"})
        self.assertIn("query=voiture", url)
        self.assertNotIn("category_id", url)

    def test_no_query_uses_category_page_as_before(self):
        url = build_search_url({"location_id": "1", "query": ""})
        self.assertTrue(url.startswith("https://www.facebook.com/marketplace/1/vehicles"))


class TestParseApifyListingDetailsOn(unittest.TestCase):
    """Shape actually observed in our validated run (includeListingDetails=true)."""

    def test_maps_all_known_fields(self):
        raw = {
            "id": "123456",
            "itemUrl": "https://www.facebook.com/marketplace/item/123456/",
            "listingTitle": "Renault Clio 2",
            "listingPrice": {"amount": "800.00", "currency": "EUR"},
            "locationText": {"text": "Liege, WAL"},
            "description": {"text": "Bouwjaar: 2015\nKilometerstand: 180 000 km"},
            "primaryListingPhoto": {"photo_image_url": "https://example.com/photo.jpg"},
            "timestamp": "2026-09-23T18:00:00.000Z",
        }
        listing = parse_apify_listing(raw)

        self.assertEqual(listing.id, "123456")
        self.assertEqual(listing.title, "Renault Clio 2")
        self.assertEqual(listing.price, 800.0)
        self.assertEqual(listing.location, "Liege, WAL")
        self.assertEqual(listing.image_url, "https://example.com/photo.jpg")
        self.assertEqual(listing.listing_url, "https://www.facebook.com/marketplace/item/123456/")
        self.assertEqual(listing.posted_at, "2026-09-23T18:00:00.000Z")
        self.assertEqual(listing.year, 2015)
        self.assertEqual(listing.mileage, 180000)


class TestParseApifyListingDetailsOff(unittest.TestCase):
    """Shape documented in the Actor's own README for includeListingDetails=false:
    snake_case field names and no timestamp at all. Must still parse price/title/
    url/location correctly, and must never invent a posted_at date.
    """

    def test_maps_fallback_field_names(self):
        raw = {
            "id": "789",
            "listingUrl": "https://www.facebook.com/marketplace/item/789/",
            "marketplace_listing_title": "Golf",
            "listing_price": {"amount": "1500.00", "formatted_amount": "1 500 €"},
            "location": {"reverse_geocode": {"city": "Liege", "state": "WAL"}},
            "primary_listing_photo": {"image": {"uri": "https://example.com/p.jpg"}},
        }
        listing = parse_apify_listing(raw)

        self.assertEqual(listing.id, "789")
        self.assertEqual(listing.title, "Golf")
        self.assertEqual(listing.price, 1500.0)
        self.assertEqual(listing.location, "Liege, WAL")
        self.assertEqual(listing.image_url, "https://example.com/p.jpg")
        self.assertEqual(listing.listing_url, "https://www.facebook.com/marketplace/item/789/")
        # No "extra details" fetched => no timestamp field => never invented.
        self.assertIsNone(listing.posted_at)
        self.assertIsNone(listing.year)
        self.assertIsNone(listing.mileage)


class TestParseApifyListingEdgeCases(unittest.TestCase):
    def test_error_placeholder_item_is_skipped(self):
        raw = {"error": "no_items", "errorDescription": "Empty or private data"}
        self.assertIsNone(parse_apify_listing(raw))

    def test_item_without_id_is_skipped(self):
        raw = {"listingTitle": "No id here"}
        self.assertIsNone(parse_apify_listing(raw))


class TestApifyWarnsAboutIncompatibleQuerySearch(unittest.TestCase):
    """/search (used when search.query is set) doesn't work anonymously with
    the Apify Actor - using it together with scraper_provider=apify should be
    flagged loudly rather than silently returning nothing.
    """

    def test_warns_when_query_set_without_custom_url(self):
        import io
        from contextlib import redirect_stdout

        cfg = {
            "search": {"location_id": "1", "query": "Véhicules"},
            "apify": {"actor_id": "x"},
        }
        response = MagicMock(status_code=200)
        response.json.return_value = []
        response.raise_for_status.return_value = None

        buffer = io.StringIO()
        with patch("apify_client.requests.post", return_value=response), redirect_stdout(buffer):
            fetch_marketplace_listings(cfg, FAKE_TOKEN)

        self.assertIn("[WARN]", buffer.getvalue())
        self.assertIn("search.query", buffer.getvalue())

    def test_no_warning_when_query_not_set(self):
        import io
        from contextlib import redirect_stdout

        cfg = {
            "search": {"location_id": "1"},
            "apify": {"actor_id": "x"},
        }
        response = MagicMock(status_code=200)
        response.json.return_value = []
        response.raise_for_status.return_value = None

        buffer = io.StringIO()
        with patch("apify_client.requests.post", return_value=response), redirect_stdout(buffer):
            fetch_marketplace_listings(cfg, FAKE_TOKEN)

        self.assertNotIn("search.query", buffer.getvalue())


class TestResultsLimit(unittest.TestCase):
    """results_limit: null in config.json means "no cap" - fetch everything
    available, then filter in Python - per explicit user request.
    """

    BASE_CFG = {
        "search": {"location_id": "1", "category": "vehicles"},
    }

    def _run(self, results_limit):
        cfg = {**self.BASE_CFG, "apify": {"actor_id": "x", "results_limit": results_limit}}
        response = MagicMock(status_code=200)
        response.json.return_value = []
        response.raise_for_status.return_value = None
        with patch("apify_client.requests.post", return_value=response) as mock_post:
            fetch_marketplace_listings(cfg, FAKE_TOKEN)
        return mock_post.call_args.kwargs["json"]

    def test_no_resultslimit_sent_when_configured_as_null(self):
        payload = self._run(None)
        self.assertNotIn("resultsLimit", payload)

    def test_resultslimit_sent_when_configured_with_a_number(self):
        payload = self._run(15)
        self.assertEqual(payload["resultsLimit"], 15)

    def test_defaults_to_40_when_key_is_entirely_absent(self):
        cfg = {**self.BASE_CFG, "apify": {"actor_id": "x"}}  # no "results_limit" key at all
        response = MagicMock(status_code=200)
        response.json.return_value = []
        response.raise_for_status.return_value = None
        with patch("apify_client.requests.post", return_value=response) as mock_post:
            fetch_marketplace_listings(cfg, FAKE_TOKEN)
        self.assertEqual(mock_post.call_args.kwargs["json"]["resultsLimit"], 40)


class TestApifyTokenNeverInUrl(unittest.TestCase):
    """The Apify token must be sent via the Authorization header, never as a
    URL query parameter - so it can never leak into an exception message
    built from the request URL (e.g. a network timeout).
    """

    CFG = {
        "search": {"location_id": "1", "category": "vehicles"},
        "apify": {"actor_id": "apify/facebook-marketplace-scraper"},
    }

    def test_fetch_marketplace_listings_sends_token_via_header_only(self):
        response = MagicMock(status_code=200)
        response.json.return_value = []
        response.raise_for_status.return_value = None

        with patch("apify_client.requests.post", return_value=response) as mock_post:
            fetch_marketplace_listings(self.CFG, FAKE_TOKEN)

        called_url = mock_post.call_args.args[0]
        called_params = mock_post.call_args.kwargs.get("params", {})
        called_headers = mock_post.call_args.kwargs.get("headers", {})

        self.assertNotIn(FAKE_TOKEN, called_url)
        self.assertNotIn(FAKE_TOKEN, str(called_params))
        self.assertEqual(called_headers.get("Authorization"), f"Bearer {FAKE_TOKEN}")

    def test_get_last_run_cost_usd_sends_token_via_header_only(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"data": {"items": [{"usageTotalUsd": 0.1}]}}
        response.raise_for_status.return_value = None

        with patch("apify_client.requests.get", return_value=response) as mock_get:
            get_last_run_cost_usd(FAKE_TOKEN)

        called_url = mock_get.call_args.args[0]
        called_params = mock_get.call_args.kwargs.get("params", {})
        called_headers = mock_get.call_args.kwargs.get("headers", {})

        self.assertNotIn(FAKE_TOKEN, called_url)
        self.assertNotIn(FAKE_TOKEN, str(called_params))
        self.assertEqual(called_headers.get("Authorization"), f"Bearer {FAKE_TOKEN}")

    def test_token_never_appears_in_exception_message(self):
        """Simulates a network failure: the resulting exception must not
        embed the token, since the URL/params it's built from never contain it.
        """
        import requests

        with patch("apify_client.requests.post", side_effect=requests.ConnectionError("boom")):
            try:
                fetch_marketplace_listings(self.CFG, FAKE_TOKEN)
            except requests.ConnectionError as exc:
                self.assertNotIn(FAKE_TOKEN, str(exc))
            else:
                self.fail("Expected a ConnectionError to propagate")


if __name__ == "__main__":
    unittest.main()
