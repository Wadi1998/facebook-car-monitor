import unittest

from filters import parse_mileage, parse_price, parse_year, passes_filters
from models import CarListing


class TestParsePrice(unittest.TestCase):
    def test_plain_number(self):
        self.assertEqual(parse_price(15000), 15000.0)

    def test_formatted_with_currency_and_spaces(self):
        self.assertEqual(parse_price("15 000 €"), 15000.0)

    def test_formatted_with_dots(self):
        self.assertEqual(parse_price("15.000"), 15000.0)

    def test_formatted_with_commas(self):
        self.assertEqual(parse_price("15,000"), 15000.0)

    def test_none_when_not_parseable(self):
        self.assertIsNone(parse_price(""))
        self.assertIsNone(parse_price(None))
        self.assertIsNone(parse_price("prix sur demande"))


class TestParseMileage(unittest.TestCase):
    def test_dot_separated_km(self):
        self.assertEqual(parse_mileage("150.000 km"), 150000)

    def test_space_separated_km(self):
        self.assertEqual(parse_mileage("150 000 km"), 150000)

    def test_no_space_before_km(self):
        self.assertEqual(parse_mileage("79.000km"), 79000)

    def test_embedded_in_sentence(self):
        self.assertEqual(parse_mileage("Kilométrage : 286 182 km"), 286182)

    def test_none_when_missing(self):
        self.assertIsNone(parse_mileage("Aucune information"))
        self.assertIsNone(parse_mileage(None))


class TestParseYear(unittest.TestCase):
    def test_year_in_title(self):
        self.assertEqual(parse_year("Volkswagen Tiguan 2019"), 2019)

    def test_year_in_sentence(self):
        self.assertEqual(parse_year("Bouwjaar: 2005, super auto"), 2005)

    def test_none_when_missing(self):
        self.assertIsNone(parse_year("Golf en bon état"))
        self.assertIsNone(parse_year(None))

    def test_ignores_implausible_numbers(self):
        # A phone number or price should not be mistaken for a year.
        self.assertIsNone(parse_year("Prix 34999, tel 0491233381"))


def make_listing(**overrides) -> CarListing:
    base = dict(
        id="1",
        title="Test car",
        price=10000,
        year=2018,
        mileage=100000,
        location="Liege",
        image_url=None,
        listing_url="https://example.com",
        posted_at=None,
        raw_data={},
    )
    base.update(overrides)
    return CarListing(**base)


class TestPassesFilters(unittest.TestCase):
    """Price is the only business filter (min_price=100, max_price=4000 in the
    real config.json). Year/mileage must never block a listing.
    """

    def setUp(self):
        self.filter_config = {
            "min_price": 100,
            "max_price": 4000,
        }

    def test_price_below_minimum_is_rejected(self):
        listing = make_listing(price=50)
        self.assertFalse(passes_filters(listing, self.filter_config))

    def test_price_equal_to_minimum_is_accepted(self):
        listing = make_listing(price=100)
        self.assertTrue(passes_filters(listing, self.filter_config))

    def test_price_between_min_and_max_is_accepted(self):
        listing = make_listing(price=2500)
        self.assertTrue(passes_filters(listing, self.filter_config))

    def test_price_equal_to_maximum_is_accepted(self):
        listing = make_listing(price=4000)
        self.assertTrue(passes_filters(listing, self.filter_config))

    def test_price_above_maximum_is_rejected(self):
        listing = make_listing(price=4500)
        self.assertFalse(passes_filters(listing, self.filter_config))

    def test_missing_price_is_rejected(self):
        listing = make_listing(price=None)
        self.assertFalse(passes_filters(listing, self.filter_config))

    def test_unparseable_price_is_rejected(self):
        # Simulates what apify_client does when parse_price() can't make
        # sense of the raw value: it stores None rather than guessing.
        unparseable_price = parse_price("prix sur demande")
        listing = make_listing(price=unparseable_price)
        self.assertFalse(passes_filters(listing, self.filter_config))

    def test_listing_without_year_is_accepted(self):
        listing = make_listing(price=1000, year=None)
        self.assertTrue(passes_filters(listing, self.filter_config))

    def test_listing_without_mileage_is_accepted(self):
        listing = make_listing(price=1000, mileage=None)
        self.assertTrue(passes_filters(listing, self.filter_config))


if __name__ == "__main__":
    unittest.main()
