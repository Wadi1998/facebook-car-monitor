"""Parsing helpers for raw text values and filtering logic for CarListing objects.

This module never invents data: if a value cannot be parsed, the corresponding
function returns None and the caller must treat it as "unknown" rather than
guessing a number.
"""

import re
from typing import Optional

from models import CarListing

# Matches a 19xx or 20xx year as a standalone number (word boundary).
_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")

# Matches a number optionally using spaces/dots/commas as thousand separators,
# immediately followed by "km" (case-insensitive), e.g. "150.000 km", "150 000km".
_MILEAGE_RE = re.compile(r"(\d[\d\s.,]{2,})\s*km", re.IGNORECASE)

# Matches a plain numeric price, allowing spaces/dots/commas as separators and
# an optional currency symbol, e.g. "15 000 €", "15,000", "€15000".
_PRICE_RE = re.compile(r"[\d][\d\s.,]*")

# A keyword-based Marketplace *search* (e.g. query="Véhicules") returns more
# listings than the strict category page, but occasionally picks up clearly
# unrelated items (observed real example: a pressure washer). This is a
# best-effort, deliberately conservative blacklist of common non-vehicle
# categories - it only rejects listings that CLEARLY match one of these, so a
# real vehicle with an unusual title is never wrongly excluded (matches every
# other "never invent/never wrongly reject" rule in this project).
_NON_VEHICLE_KEYWORDS = [
    "nettoyeur", "netoyeur", "haute pression", "aspirateur", "frigo", "réfrigérateur", "congélateur",
    "canapé", "fauteuil", "armoire", "matelas", "lit ", "table basse",
    "télé", "televisie", "ordinateur", "gsm", "smartphone", "meuble",
    "lave-linge", "lave-vaisselle", "cuisinière", "four ", "tondeuse",
    "perceuse", "outillage", "jouet", "vêtement", "chaussure", "poussette",
]


def is_likely_non_vehicle(title) -> bool:
    """True only when the title clearly matches a common non-vehicle
    Marketplace category. Never invents a "yes it's a vehicle" answer either
    way: an unknown/ambiguous title is NOT flagged (returns False), so it's
    kept rather than risk excluding a real vehicle listing.
    """
    if not title:
        return False
    lowered = str(title).lower()
    return any(keyword in lowered for keyword in _NON_VEHICLE_KEYWORDS)


def parse_price(value) -> Optional[float]:
    """Parse a price from a number, numeric string, or formatted string like
    "15 000 €" / "15,000" / "15.000" into a float. Returns None if not parseable.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    match = _PRICE_RE.search(text)
    if not match:
        return None
    digits = _normalize_number(match.group(0))
    if digits is None:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def parse_mileage(text) -> Optional[int]:
    """Extract a mileage in km from free text such as a title or description.
    Returns None if no km value is found.
    """
    if not text:
        return None
    match = _MILEAGE_RE.search(str(text))
    if not match:
        return None
    digits = _normalize_number(match.group(1))
    if digits is None:
        return None
    try:
        return int(float(digits))
    except ValueError:
        return None


def parse_year(text) -> Optional[int]:
    """Extract a plausible vehicle model year (1950-2049) from free text.
    Returns None if no such year is found.
    """
    if not text:
        return None
    match = _YEAR_RE.search(str(text))
    if not match:
        return None
    return int(match.group(1))


def _normalize_number(raw: str) -> Optional[str]:
    """Turn "15 000", "15.000", "15,000", "150 182" into a plain digit string,
    handling spaces/dots/commas used as thousand separators. Assumes the value
    represents an integer amount (prices/mileage in this project have no
    meaningful decimals in the source text).
    """
    cleaned = raw.strip()
    digits_only = re.sub(r"[^\d]", "", cleaned)
    if not digits_only:
        return None
    return digits_only


def passes_filters(listing: CarListing, filter_config: dict) -> bool:
    """Return True if the listing's price is within [min_price, max_price].

    Price is the only business filter. Year and mileage are informational
    only (shown in the Telegram message when known) and never affect whether
    a listing is kept, even when they're missing.

    If the price is missing or could not be parsed, the listing is always
    rejected: we never guess whether an unpriced listing would have matched.

    The only other check is an opt-in, conservative anti-noise filter
    (`exclude_non_vehicle_keywords`, default True) needed because a
    keyword-based Marketplace search (search.query in config.json) can
    occasionally return clearly-unrelated items - see is_likely_non_vehicle().
    """
    if listing.price is None:
        return False

    min_price = filter_config.get("min_price")
    if min_price is not None and listing.price < min_price:
        return False

    max_price = filter_config.get("max_price")
    if max_price is not None and listing.price > max_price:
        return False

    if filter_config.get("exclude_non_vehicle_keywords", True) and is_likely_non_vehicle(listing.title):
        return False

    return True
