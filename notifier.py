"""Sends new listing notifications to Telegram via plain HTTP calls to the
Bot API (no extra SDK dependency needed for this MVP).
"""

from datetime import datetime, timezone

import requests

from models import CarListing

TELEGRAM_API_BASE = "https://api.telegram.org"


def format_posted_at(posted_at: str) -> str:
    """Format the Facebook posting ISO timestamp as "JJ/MM/AAAA à HH:MM"
    (local time). Returns None if the value is missing or unparseable -
    never guessed.
    """
    if not posted_at:
        return None
    try:
        dt = datetime.fromisoformat(posted_at.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None
    return dt.strftime("%d/%m/%Y à %H:%M")


def format_message(listing: CarListing) -> str:
    """Build the Telegram message text.

    Price is always shown (it's the only required field for a notification to
    be sent at all). Year, mileage and posting date are purely informational:
    their lines are only included when the value is actually known, never
    guessed.
    """
    title = listing.title or "Annonce sans titre"
    price = f"{listing.price:,.0f} €".replace(",", " ") if listing.price is not None else "Prix inconnu"
    location = listing.location or "Localisation inconnue"
    posted_at_text = format_posted_at(listing.posted_at)

    lines = [
        "🚨 NOUVELLE ANNONCE",
        "",
        f"🚗 {title}",
        "",
        f"💰 {price}",
    ]
    if listing.year is not None:
        lines.append(f"📅 {listing.year}")
    if listing.mileage is not None:
        lines.append(f"🛣️ {listing.mileage:,} km".replace(",", " "))
    if posted_at_text is not None:
        lines.append(f"🕒 Publiée le {posted_at_text}")

    lines.append("")
    lines.append(f"📍 {location}")
    lines.append("")
    lines.append("🔗 Voir l'annonce")
    lines.append(listing.listing_url or "URL indisponible")

    return "\n".join(lines)


def send_listing_notification(listing: CarListing, bot_token: str, chat_id: str) -> bool:
    """Send a Telegram notification for a new listing. Returns True on success.

    Tries a photo with caption first when an image is available. If Telegram
    can't deliver it (e.g. it fails to fetch a Facebook CDN image URL, which
    happens regularly), falls back to a text-only message rather than losing
    the notification entirely. Never raises: failures are logged and False is
    returned so the monitoring loop can keep running.
    """
    message = format_message(listing)

    if listing.image_url:
        if _post_telegram(bot_token, "sendPhoto", {"chat_id": chat_id, "caption": message, "photo": listing.image_url}):
            return True
        print(f"[WARN] Listing {listing.id}: sendPhoto failed, retrying as text-only message")

    return _post_telegram(bot_token, "sendMessage", {"chat_id": chat_id, "text": message})


def _post_telegram(bot_token: str, method: str, data: dict) -> bool:
    """POST to the Telegram Bot API. Returns True on success (HTTP 200).

    Never logs the request URL, which embeds the bot token - only Telegram's
    own JSON error description (or a generic message for network errors) is
    printed, so the token can never leak into logs.
    """
    try:
        resp = requests.post(f"{TELEGRAM_API_BASE}/bot{bot_token}/{method}", data=data, timeout=30)
    except requests.RequestException as exc:
        print(f"[ERROR] Telegram {method} failed: network error ({type(exc).__name__})")
        return False

    if resp.status_code == 200:
        return True

    try:
        description = resp.json().get("description", resp.text[:200])
    except ValueError:
        description = resp.text[:200]
    print(f"[ERROR] Telegram {method} failed ({resp.status_code}): {description}")
    return False
