"""Talks to the Bright Data Facebook Marketplace Scraper API and turns raw
records into CarListing objects.

Mirrors apify_client.py's shape and behavior (same "never invent a value"
rule, same reliance on filters.py for price/year/mileage parsing) so both
providers are interchangeable behind providers.py. Reuses
apify_client.build_search_url() rather than duplicating URL-building logic:
Bright Data's discovery endpoint accepts the exact same Facebook Marketplace
category URL already validated for Apify.

Validated against a real (small, paid) call on 2026-09-23:
  POST /datasets/v3/scrape?dataset_id=gd_lvt9iwuh6fbcwmx1a&type=discover_new&discover_by=url
  body: {"input": [{"url": <marketplace category URL>, "country": "BE"}], "limit_per_input": N}
This returned real Belgian listings (near Liège) synchronously, as NDJSON
(one JSON object per line) rather than a JSON array - the response is parsed
accordingly below. For larger jobs Bright Data's own docs say discovery can
fall back to an async snapshot (a lone {"snapshot_id": ...} object with no
listing fields); that case is polled via progress/snapshot, same as any other
Bright Data async job, so a big `results_limit` doesn't leave us stuck.
"""

import json
import time
from typing import List, Optional

import requests

from filters import parse_mileage, parse_price, parse_year
from models import CarListing

BRIGHTDATA_API_BASE = "https://api.brightdata.com"
MARKETPLACE_DATASET_ID = "gd_lvt9iwuh6fbcwmx1a"


def fetch_marketplace_listings(config: dict, api_key: str) -> List[CarListing]:
    """Run Bright Data Marketplace discovery request(s) for our configured
    Facebook Marketplace URL(s), and return the merged results as CarListing
    objects.

    When search.query is set (see apify_client.build_discovery_urls()), this
    queries BOTH the category page and the keyword search and merges the
    results, since they don't return identical listing sets. The caller
    (main.py) already deduplicates the returned list by id, so any overlap
    between the two URLs is harmless.

    Raises requests.RequestException / RuntimeError on API failures; callers
    are expected to catch these per monitoring cycle so one failed run does
    not stop the program (same contract as apify_client.fetch_marketplace_listings).
    """
    from apify_client import build_discovery_urls  # reuse the already-validated URL builder(s)

    search_config = config["search"]
    brightdata_config = config.get("brightdata", {})
    urls = build_discovery_urls(search_config)

    listings = []
    for url in urls:
        listings.extend(_fetch_listings_for_url(url, brightdata_config, api_key))
    return listings


def _fetch_listings_for_url(search_url: str, brightdata_config: dict, api_key: str) -> List[CarListing]:
    """Run a single Bright Data discovery request against one Marketplace URL."""
    dataset_id = brightdata_config.get("dataset_id", MARKETPLACE_DATASET_ID)
    country = brightdata_config.get("country", "BE")
    timeout = brightdata_config.get("timeout_seconds", 180)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    payload = {"input": [{"url": search_url, "country": country}]}
    results_limit = brightdata_config.get("results_limit")
    if results_limit is not None:
        payload["limit_per_input"] = results_limit

    response = requests.post(
        f"{BRIGHTDATA_API_BASE}/datasets/v3/scrape",
        params={
            "dataset_id": dataset_id,
            "notify": "false",
            "include_errors": "true",
            "type": "discover_new",
            "discover_by": "url",
        },
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    raw_items = _parse_records(response.text)

    # Large discovery jobs can fall back to Bright Data's async snapshot flow
    # (a single {"snapshot_id": ...} object instead of listing records).
    if len(raw_items) == 1 and "snapshot_id" in raw_items[0] and "product_id" not in raw_items[0]:
        snapshot_id = raw_items[0]["snapshot_id"]
        _wait_for_snapshot(snapshot_id, headers, brightdata_config, timeout)
        raw_items = _download_snapshot(snapshot_id, headers, timeout)

    listings = []
    for raw in raw_items:
        listing = parse_brightdata_listing(raw)
        if listing is not None:
            listings.append(listing)
    return listings


def _parse_records(response_text: str) -> List[dict]:
    """Bright Data's sync discovery response is NDJSON (one JSON object per
    line) - confirmed against a real call - rather than a wrapped JSON array,
    but a plain JSON array or single object is also accepted for robustness.
    """
    text = response_text.strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
        raise RuntimeError(f"Unexpected Bright Data response shape: {type(parsed)}")
    except json.JSONDecodeError:
        pass

    # The whole body isn't a single valid JSON value: it's multiple
    # concatenated JSON objects (NDJSON), one per line.
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _wait_for_snapshot(snapshot_id: str, headers: dict, brightdata_config: dict, timeout: int) -> None:
    """Poll job progress until it's ready, fails, or we exceed the configured
    poll timeout. Raises RuntimeError if the job doesn't finish successfully.
    """
    poll_interval = brightdata_config.get("poll_interval_seconds", 5)
    max_wait = brightdata_config.get("max_poll_seconds", timeout)
    deadline = time.monotonic() + max_wait

    while True:
        response = requests.get(
            f"{BRIGHTDATA_API_BASE}/datasets/v3/progress/{snapshot_id}",
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        status = response.json().get("status")

        if status == "ready":
            return
        if status in ("failed", "canceled"):
            raise RuntimeError(f"Bright Data job {snapshot_id} ended with status={status!r}")
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Bright Data job {snapshot_id} did not finish within {max_wait}s (status={status!r})")

        time.sleep(poll_interval)


def _download_snapshot(snapshot_id: str, headers: dict, timeout: int) -> List[dict]:
    response = requests.get(
        f"{BRIGHTDATA_API_BASE}/datasets/v3/snapshot/{snapshot_id}",
        params={"format": "json"},
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    raw_items = response.json()

    if not isinstance(raw_items, list):
        raise RuntimeError(f"Unexpected Bright Data snapshot response shape: {type(raw_items)}")
    return raw_items


def parse_brightdata_listing(raw: dict) -> Optional[CarListing]:
    """Convert one raw record from Bright Data's Facebook Marketplace
    discovery/collect endpoints into a CarListing.

    Documented + observed output fields: url, title, initial_price,
    final_price, currency, product_id, condition, description, location,
    country_code, images[], car_miles, transmission, is_sold, listing_date.
    Never invents a value that isn't present.
    """
    product_id = raw.get("product_id")
    if not product_id:
        print(f"[WARN] Skipping Bright Data item with no product_id: {raw}")
        return None

    title = raw.get("title")

    price = None
    final_price = raw.get("final_price")
    if final_price is not None:
        # Bright Data's final_price is already a plain number (e.g. 35995),
        # not a human-formatted string, but parse_price() handles both cases
        # safely (a bare int/float is returned as-is).
        price = parse_price(final_price)

    description_text = raw.get("description") or ""
    search_text = " ".join(filter(None, [title, description_text]))
    year = parse_year(search_text)

    # car_miles is a real structured field (when Facebook/the seller exposes
    # it) - prefer it over guessing from free text, but never invent it if
    # it's null/absent.
    mileage = raw.get("car_miles")
    if mileage is None:
        mileage = parse_mileage(search_text)

    images = raw.get("images") or []
    image_url = images[0] if images else None

    listing_url = raw.get("url")
    posted_at = raw.get("listing_date")

    _warn_unrecognized_fields(raw, title, price, listing_url)

    return CarListing(
        id=str(product_id),
        title=title,
        price=price,
        year=year,
        mileage=mileage,
        location=raw.get("location"),
        image_url=image_url,
        listing_url=listing_url,
        posted_at=posted_at,
        raw_data=raw,
    )


def _warn_unrecognized_fields(raw, title, price, listing_url) -> None:
    if title is None:
        print(f"[WARN] Listing {raw.get('product_id')}: no title field recognized")
    if price is None:
        print(f"[WARN] Listing {raw.get('product_id')}: could not parse price, listing will be rejected")
    if listing_url is None:
        print(f"[WARN] Listing {raw.get('product_id')}: no listing URL found")
