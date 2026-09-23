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
    """
    if listing.price is None:
        return False

    min_price = filter_config.get("min_price")
    if min_price is not None and listing.price < min_price:
        return False

    max_price = filter_config.get("max_price")
    if max_price is not None and listing.price > max_price:
        return False

    return True
