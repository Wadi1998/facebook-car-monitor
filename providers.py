"""Common interface over the different scraping backends (Apify, Bright Data,
...) so the rest of the program (filters, dedup, seen_listings.json, Telegram)
never needs to know which one produced a given CarListing.

Selecting a provider is a pure config.json setting (`scraper_provider`); no
code elsewhere changes when switching providers.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from models import CarListing


class MarketplaceScraper(ABC):
    """Any scraper provider must be able to fetch listings and (best-effort)
    report the cost of doing so. Cost may legitimately be unknown (None) -
    it must never be invented.
    """

    @abstractmethod
    def fetch_listings(self, config: dict) -> List[CarListing]:
        ...

    @abstractmethod
    def get_last_cost_usd(self) -> Optional[float]:
        ...


class ApifyScraper(MarketplaceScraper):
    """Delegates to apify_client.py, unchanged."""

    def __init__(self, api_token: str):
        self.api_token = api_token

    def fetch_listings(self, config: dict) -> List[CarListing]:
        from apify_client import fetch_marketplace_listings

        return fetch_marketplace_listings(config, self.api_token)

    def get_last_cost_usd(self) -> Optional[float]:
        from apify_client import get_last_run_cost_usd

        return get_last_run_cost_usd(self.api_token)


class BrightDataScraper(MarketplaceScraper):
    """Delegates to brightdata_client.py."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch_listings(self, config: dict) -> List[CarListing]:
        from brightdata_client import fetch_marketplace_listings

        return fetch_marketplace_listings(config, self.api_key)

    def get_last_cost_usd(self) -> Optional[float]:
        # Bright Data doesn't expose a per-run usage lookup the way Apify's
        # actor-runs API does. Rather than guess a cost from a hardcoded
        # per-record price, report it as unknown.
        return None


def get_scraper(config: dict, apify_token: str, brightdata_api_key: str) -> MarketplaceScraper:
    """Instantiate the scraper provider selected by config["scraper_provider"]
    (defaults to "apify" for backward compatibility with existing configs).
    """
    provider = config.get("scraper_provider", "apify")
    if provider == "apify":
        return ApifyScraper(apify_token)
    if provider == "brightdata":
        return BrightDataScraper(brightdata_api_key)
    raise ValueError(f"Unknown scraper_provider: {provider!r} (expected 'apify' or 'brightdata')")
