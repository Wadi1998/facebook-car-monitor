import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from models import CarListing
from notifier import format_message, format_posted_at, send_listing_notification

FAKE_TOKEN = "123456:SUPER-SECRET-TOKEN"


def make_listing(image_url="https://example.com/photo.jpg") -> CarListing:
    return CarListing(
        id="1",
        title="BMW 320d",
        price=2500,
        year=2015,
        mileage=180000,
        location="Liege",
        image_url=image_url,
        listing_url="https://facebook.com/marketplace/item/1",
        posted_at=None,
        raw_data={},
    )


class TestFormatMessage(unittest.TestCase):
    def test_includes_year_and_mileage_when_known(self):
        message = format_message(make_listing())
        self.assertIn("📅 2015", message)
        self.assertIn("🛣️ 180 000 km", message)

    def test_omits_year_and_mileage_when_unknown(self):
        listing = make_listing()
        listing.year = None
        listing.mileage = None
        message = format_message(listing)
        self.assertNotIn("📅", message)
        self.assertNotIn("🛣️", message)

    def test_includes_posted_date_when_known(self):
        listing = make_listing()
        listing.posted_at = "2026-09-23T18:32:31.000Z"
        message = format_message(listing)
        self.assertIn("🕒 Publiée le", message)

    def test_omits_posted_date_when_unknown(self):
        message = format_message(make_listing())  # posted_at=None by default
        self.assertNotIn("🕒", message)


class TestFormatPostedAt(unittest.TestCase):
    def test_parses_iso_timestamp(self):
        result = format_posted_at("2026-09-23T18:32:31.000Z")
        self.assertRegex(result, r"^\d{2}/\d{2}/\d{4} à \d{2}:\d{2}$")

    def test_none_when_missing(self):
        self.assertIsNone(format_posted_at(None))
        self.assertIsNone(format_posted_at(""))

    def test_none_when_unparseable(self):
        self.assertIsNone(format_posted_at("not a date"))


class TestSendListingNotification(unittest.TestCase):
    def test_bot_token_never_appears_in_logs_on_failure(self):
        mock_response = MagicMock(status_code=400)
        mock_response.json.return_value = {"description": "Bad Request: wrong file identifier"}

        buffer = io.StringIO()
        with patch("notifier.requests.post", return_value=mock_response), redirect_stdout(buffer):
            result = send_listing_notification(make_listing(), FAKE_TOKEN, "chat123")

        self.assertFalse(result)
        self.assertNotIn(FAKE_TOKEN, buffer.getvalue())

    def test_falls_back_to_text_message_when_photo_fails(self):
        photo_response = MagicMock(status_code=400)
        photo_response.json.return_value = {"description": "Bad Request"}
        text_response = MagicMock(status_code=200)

        with patch("notifier.requests.post", side_effect=[photo_response, text_response]) as mock_post:
            result = send_listing_notification(make_listing(), FAKE_TOKEN, "chat123")

        self.assertTrue(result)
        self.assertEqual(mock_post.call_count, 2)
        self.assertIn("sendPhoto", mock_post.call_args_list[0].args[0])
        self.assertIn("sendMessage", mock_post.call_args_list[1].args[0])

    def test_no_image_sends_text_message_directly(self):
        text_response = MagicMock(status_code=200)
        with patch("notifier.requests.post", return_value=text_response) as mock_post:
            result = send_listing_notification(make_listing(image_url=None), FAKE_TOKEN, "chat123")

        self.assertTrue(result)
        mock_post.assert_called_once()
        self.assertIn("sendMessage", mock_post.call_args.args[0])

    def test_network_error_does_not_raise_and_does_not_leak_token(self):
        import requests

        buffer = io.StringIO()
        with patch("notifier.requests.post", side_effect=requests.ConnectionError("boom")), redirect_stdout(buffer):
            result = send_listing_notification(make_listing(image_url=None), FAKE_TOKEN, "chat123")

        self.assertFalse(result)
        self.assertNotIn(FAKE_TOKEN, buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
