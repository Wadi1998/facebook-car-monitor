"""Talks to the Apify REST API to run the Facebook Marketplace Actor and turns
raw dataset items into CarListing objects.

This module deliberately knows nothing about price/year/mileage *filtering*
(see filters.py for that) - it only maps the Actor's raw output shape to our
own CarListing model, extracting year/mileage from free text on a best-effort
basis and never inventing values that aren't present.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

import requests

from filters import parse_mileage, parse_price, parse_year
from models import CarListing

APIFY_API_BASE = "https://api.apify.com/v2"


def _actor_rest_id(actor_id: str) -> str:
    """Apify's REST API expects "owner~actor-name" instead of "owner/actor-name"."""
    return actor_id.replace("/", "~")


def _auth_headers(api_token: str) -> dict:
    """Apify accepts the token either as a `?token=` URL query param or as an
    `Authorization: Bearer` header - Apify's own docs recommend the header,
    since URLs (unlike headers) tend to end up in logs, browser history, and
    exception messages. Using the header keeps the token out of every URL
    this module builds, and therefore out of any error message derived from
    that URL (e.g. a network timeout exception).
    """
    return {"Authorization": f"Bearer {api_token}"}


def build_search_url(search_config: dict) -> str:
    """Build a Facebook Marketplace category URL for the configured location.

    Uses the category *browse* page (e.g. /marketplace/<id>/vehicles) rather
    than the /search endpoint, because /search requires a logged-in session
    and returns no results anonymously (verified manually against the Actor).

    If search_config["custom_url"] is set, it's used as-is instead of being
    built from the other fields below - this is the escape hatch for trying
    things (keywords, a different category, extra Facebook query params like
    minPrice/maxPrice) without touching any code. Everything else in this
    function only kicks in when custom_url is absent/empty.
    """
    custom_url = search_config.get("custom_url")
    if custom_url:
        return custom_url

    location_id = search_config["location_id"]
    category = search_config.get("category", "vehicles")
    radius_km = search_config.get("radius_km", 150)
    days_since_listed = search_config.get("days_since_listed", 1)
    sort_by = search_config.get("sort_by", "creation_time_descend")
    exact = search_config.get("exact", False)

    return (
        f"https://www.facebook.com/marketplace/{location_id}/{category}"
        f"?daysSinceListed={days_since_listed}"
        f"&radius={radius_km}"
        f"&sortBy={sort_by}"
        f"&exact={'true' if exact else 'false'}"
    )


def fetch_marketplace_listings(config: dict, api_token: str) -> List[CarListing]:
    """Run the configured Apify Actor and return the results as CarListing objects.

    Raises requests.RequestException / RuntimeError on API failures; callers
    are expected to catch these per monitoring cycle so one failed run does
    not stop the program.
    """
    apify_config = config["apify"]
    search_config = config["search"]

    actor_id = _actor_rest_id(apify_config["actor_id"])
    search_url = build_search_url(search_config)

    payload = {
        "startUrls": [{"url": search_url}],
        "includeListingDetails": apify_config.get("include_listing_details", True),
    }
    results_limit = apify_config.get("results_limit", 40)
    if results_limit is not None:
        payload["resultsLimit"] = results_limit
    # If results_limit is None (config.json: "results_limit": null), the key
    # is omitted entirely - per Apify's own docs, "if this limit is not set,
    # as many results as possible will be returned", i.e. no artificial cap.

    # Optional hard spending cap enforced by Apify itself (documented
    # run-sync-get-dataset-items query param), independent of anything the
    # Actor does. This is a safety net, not a behavior change: if unset, no
    # cap is sent and nothing changes from before.
    query_params = {}
    max_total_charge_usd = apify_config.get("max_total_charge_usd")
    if max_total_charge_usd is not None:
        query_params["maxTotalChargeUsd"] = max_total_charge_usd

    response = requests.post(
        f"{APIFY_API_BASE}/acts/{actor_id}/run-sync-get-dataset-items",
        params=query_params,
        headers=_auth_headers(api_token),
        json=payload,
        timeout=apify_config.get("timeout_seconds", 180),
    )
    response.raise_for_status()
    raw_items = response.json()

    if not isinstance(raw_items, list):
        raise RuntimeError(f"Unexpected Apify response shape: {type(raw_items)}")

    listings = []
    for raw in raw_items:
        listing = parse_apify_listing(raw)
        if listing is not None:
            listings.append(listing)

    return _filter_recent(listings, search_config.get("days_since_listed", 1))


def parse_apify_listing(raw: dict) -> Optional[CarListing]:
    """Convert one raw dataset item from apify/facebook-marketplace-scraper
    into a CarListing. Returns None (and logs) for items that carry no usable
    listing data, e.g. the Actor's own {"error": "no_items"} placeholder rows.

    The Actor returns different field names depending on whether
    includeListingDetails is enabled:
      - details ON  (validated shape): listingTitle, listingPrice, itemUrl,
        locationText, primaryListingPhoto.photo_image_url, timestamp.
      - details OFF (per the Actor's own README, NOT yet validated against a
        real run): marketplace_listing_title, listing_price, listingUrl,
        location.reverse_geocode, primary_listing_photo.image.uri, and no
        timestamp field at all (posting date is an "extra detail").
    Both shapes are supported so toggling include_listing_details doesn't
    silently break parsing, but see README for the posted_at caveat.
    """
    if raw.get("error"):
        print(f"[WARN] Skipping Apify item with error: {raw.get('error')}")
        return None

    listing_id = raw.get("id")
    if not listing_id:
        print(f"[WARN] Skipping Apify item with no id: {raw}")
        return None

    title = raw.get("listingTitle") or raw.get("customTitle") or raw.get("marketplace_listing_title")

    price = None
    listing_price = raw.get("listingPrice") or raw.get("listing_price") or {}
    raw_amount = listing_price.get("amount")
    if raw_amount is not None:
        # "amount" is Apify's own machine-formatted decimal (e.g. "800.00",
        # "13500.00"): parse it as a plain float, NOT through parse_price(),
        # which would misread the "." as a thousands separator (bug found via
        # tests/test_apify_client.py: "800.00" -> 80000.0 instead of 800.0).
        try:
            price = float(raw_amount)
        except (TypeError, ValueError):
            price = None
    if price is None and listing_price.get("formatted_amount_zeros_stripped"):
        # Human-formatted display strings (e.g. "€1,350") DO need parse_price().
        price = parse_price(listing_price["formatted_amount_zeros_stripped"])
    if price is None and listing_price.get("formatted_amount"):
        price = parse_price(listing_price["formatted_amount"])

    description_text = (raw.get("description") or {}).get("text", "")
    search_text = " ".join(filter(None, [title, description_text]))
    year = parse_year(search_text)
    mileage = parse_mileage(search_text)

    location_text = (raw.get("locationText") or {}).get("text") or _location_from_reverse_geocode(
        raw.get("location")
    )

    image_url = None
    primary_photo = raw.get("primaryListingPhoto") or raw.get("primary_listing_photo") or {}
    if primary_photo.get("photo_image_url"):
        image_url = primary_photo["photo_image_url"]
    elif (primary_photo.get("image") or {}).get("uri"):
        image_url = primary_photo["image"]["uri"]
    else:
        photos = raw.get("listingPhotos") or []
        if photos:
            image_url = (photos[0].get("image") or {}).get("uri")

    listing_url = raw.get("itemUrl") or raw.get("listingUrl")
    # Only present when includeListingDetails=true; None otherwise (never
    # invented) - see _filter_recent(), which keeps listings with no date
    # rather than guessing.
    posted_at = raw.get("timestamp")

    _warn_unrecognized_fields(raw, title, price, year, mileage, listing_url)

    return CarListing(
        id=str(listing_id),
        title=title,
        price=price,
        year=year,
        mileage=mileage,
        location=location_text,
        image_url=image_url,
        listing_url=listing_url,
        posted_at=posted_at,
        raw_data=raw,
    )


def _location_from_reverse_geocode(location: Optional[dict]) -> Optional[str]:
    """Fallback location formatting for the "details off" output shape, which
    exposes location.reverse_geocode.{city,state} instead of a ready-made
    locationText.text string.
    """
    if not location:
        return None
    geocode = location.get("reverse_geocode") or {}
    city = geocode.get("city")
    state = geocode.get("state")
    if city and state:
        return f"{city}, {state}"
    return city or state


def _warn_unrecognized_fields(raw, title, price, year, mileage, listing_url) -> None:
    # Price is the only field that affects filtering, so a missing/unparseable
    # price is worth a loud warning (it causes the listing to be dropped).
    if title is None:
        print(f"[WARN] Listing {raw.get('id')}: no title field recognized")
    if price is None:
        print(f"[WARN] Listing {raw.get('id')}: could not parse price, listing will be rejected")
    if listing_url is None:
        print(f"[WARN] Listing {raw.get('id')}: no listing URL found")
    # Year/mileage are informational only (shown in Telegram when known) and
    # never affect filtering, so their absence is just logged for visibility.
    if year is None:
        print(f"[INFO] Listing {raw.get('id')}: year not found in title/description")
    if mileage is None:
        print(f"[INFO] Listing {raw.get('id')}: mileage not found in title/description")


def get_last_run_cost_usd(api_token: str) -> Optional[float]:
    """Best-effort lookup of the most recently finished Actor run's cost, for
    logging purposes only. This calls Apify's read-only run-listing API (no
    new Actor run is started, so this never costs anything) and returns None
    if the cost can't be determined - callers must treat that as "unknown",
    not as zero cost.
    """
    try:
        response = requests.get(
            f"{APIFY_API_BASE}/actor-runs",
            params={"limit": 1, "desc": "true"},
            headers=_auth_headers(api_token),
            timeout=15,
        )
        response.raise_for_status()
        items = response.json().get("data", {}).get("items", [])
        if not items:
            return None
        return items[0].get("usageTotalUsd")
    except (requests.RequestException, ValueError, KeyError) as exc:
        print(f"[WARN] Could not fetch Apify run cost: {exc}")
        return None


def _filter_recent(listings: List[CarListing], days_since_listed: int) -> List[CarListing]:
    """Double-check recency in Python using the Actor's own posted_at date,
    since sellers can bump old listings to the top of Marketplace and the
    Actor's daysSinceListed URL filter should not be blindly trusted.
    """
    if not days_since_listed:
        return listings

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_since_listed)
    recent = []
    for listing in listings:
        if not listing.posted_at:
            # No posted date available: keep it rather than silently dropping,
            # but this is logged so it's visible during debugging.
            print(f"[WARN] Listing {listing.id}: no posted_at date, cannot verify recency")
            recent.append(listing)
            continue
        try:
            posted_dt = datetime.fromisoformat(listing.posted_at.replace("Z", "+00:00"))
        except ValueError:
            print(f"[WARN] Listing {listing.id}: unparseable posted_at={listing.posted_at!r}")
            recent.append(listing)
            continue
        if posted_dt >= cutoff:
            recent.append(listing)
    return recent
