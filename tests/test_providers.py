import unittest
from unittest.mock import MagicMock, patch

from providers import ApifyScraper, BrightDataScraper, get_scraper


class TestGetScraper(unittest.TestCase):
    def test_apify_provider_returns_apify_scraper(self):
        scraper = get_scraper({"scraper_provider": "apify"}, "apify-token", "bd-key")
        self.assertIsInstance(scraper, ApifyScraper)

    def test_missing_provider_defaults_to_apify(self):
        scraper = get_scraper({}, "apify-token", "bd-key")
        self.assertIsInstance(scraper, ApifyScraper)

    def test_brightdata_provider_returns_brightdata_scraper(self):
        scraper = get_scraper({"scraper_provider": "brightdata"}, "apify-token", "bd-key")
        self.assertIsInstance(scraper, BrightDataScraper)

    def test_unknown_provider_raises(self):
        with self.assertRaises(ValueError):
            get_scraper({"scraper_provider": "not-a-real-provider"}, "apify-token", "bd-key")


class TestProvidersReturnSameModel(unittest.TestCase):
    """The rest of the app (filters, dedup, seen_listings.json, Telegram) must
    never need to know which provider produced a CarListing: both providers
    must expose the exact same interface and return the same model, with the
    same fields populated for equivalent input data.
    """

    def test_apify_and_brightdata_scrapers_expose_the_same_interface(self):
        apify_scraper = ApifyScraper("token")
        brightdata_scraper = BrightDataScraper("key")

        for scraper in (apify_scraper, brightdata_scraper):
            self.assertTrue(hasattr(scraper, "fetch_listings"))
            self.assertTrue(hasattr(scraper, "get_last_cost_usd"))

    def test_both_providers_produce_equivalent_carlisting_for_equivalent_data(self):
        config = {
            "search": {"location_id": "1", "category": "vehicles"},
            "apify": {"actor_id": "apify/facebook-marketplace-scraper"},
            "brightdata": {},
        }

        apify_raw = {
            "id": "42",
            "itemUrl": "https://www.facebook.com/marketplace/item/42/",
            "listingTitle": "BMW 320d",
            "listingPrice": {"amount": "2500.00"},
            "locationText": {"text": "Liege"},
        }
        brightdata_raw = {
            "product_id": "42",
            "url": "https://www.facebook.com/marketplace/item/42/",
            "title": "BMW 320d",
            "final_price": 2500,
            "location": "Liege",
        }

        with patch("apify_client.requests.post") as mock_apify_post:
            mock_apify_post.return_value.json.return_value = [apify_raw]
            mock_apify_post.return_value.raise_for_status.return_value = None
            apify_listings = ApifyScraper("token").fetch_listings(config)

        # Bright Data's discovery endpoint responds synchronously with NDJSON
        # (one JSON object per line) - confirmed against a real validated call.
        import json

        bd_response = MagicMock(status_code=200)
        bd_response.text = json.dumps(brightdata_raw) + "\n"
        bd_response.raise_for_status.return_value = None

        with patch("brightdata_client.requests.post", return_value=bd_response):
            brightdata_listings = BrightDataScraper("key").fetch_listings(config)

        self.assertEqual(len(apify_listings), 1)
        self.assertEqual(len(brightdata_listings), 1)

        apify_listing = apify_listings[0]
        brightdata_listing = brightdata_listings[0]

        # Same model, same fields populated the same way - the rest of the
        # program can treat these interchangeably.
        self.assertEqual(type(apify_listing), type(brightdata_listing))
        self.assertEqual(apify_listing.id, brightdata_listing.id)
        self.assertEqual(apify_listing.title, brightdata_listing.title)
        self.assertEqual(apify_listing.price, brightdata_listing.price)
        self.assertEqual(apify_listing.location, brightdata_listing.location)
        self.assertEqual(apify_listing.listing_url, brightdata_listing.listing_url)


if __name__ == "__main__":
    unittest.main()
