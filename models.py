"""Data models for the Facebook Marketplace car monitor."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CarListing:
    """A single car/vehicle listing, normalized from an Apify Actor result."""

    id: str
    title: Optional[str]
    price: Optional[float]
    year: Optional[int]
    mileage: Optional[int]
    location: Optional[str]
    image_url: Optional[str]
    listing_url: Optional[str]
    posted_at: Optional[str]  # ISO 8601 string, when available
    source: str = "facebook_marketplace"
    raw_data: dict = field(default_factory=dict, repr=False)
