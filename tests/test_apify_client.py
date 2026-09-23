import unittest

from apify_client import build_search_url, parse_apify_listing


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


if __name__ == "__main__":
    unittest.main()
