"""Address to coordinates, via OpenStreetMap Nominatim.

Proxied through the API rather than called from the browser, for three reasons
that all matter:

* Nominatim's usage policy requires an identifying User-Agent and caps callers
  at one request per second. A browser cannot be trusted to honour either, and
  a page that fires one lookup per keystroke gets the whole deployment blocked.
* The console would otherwise talk to a third party directly, so every operator
  browser would leak the site addresses of a customer's plants.
* It can be turned off. Some deployments have no outbound internet at all, and
  the answer there has to be "type the coordinates in", not a hung request.

Geocoding is **always optional**. Every caller falls back to manual entry, and
a failure here returns an empty result rather than an error - a site that
cannot be geocoded is a site with a slightly emptier map, not a site that
cannot be created.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from apps.core.logging import get_logger

logger = get_logger("devices.geocoding")

#: Nominatim asks for at most one request per second from any one client.
_MIN_INTERVAL_SECONDS = 1.1
_lock = threading.Lock()
_last_call = 0.0

CACHE_TTL_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True, slots=True)
class Place:
    latitude: float
    longitude: float
    display_name: str
    city: str = ""
    #: ISO 3166-1 alpha-2, upper case, to match ``Site.country``.
    country: str = ""
    #: IANA name derived from the coordinates, not from the address text.
    #: Blank when it cannot be determined, which the console treats as
    #: "leave whatever is already selected".
    timezone_name: str = ""


def timezone_for(latitude: float, longitude: float) -> str:
    """IANA zone for a point, or ``""`` if it cannot be resolved.

    Offline, from a bundled boundary set. Deliberately not a second web
    service: geocoding already depends on one upstream being reachable, and
    doubling that to fill in a field the operator can pick from a dropdown
    would be a poor trade.

    Ocean coordinates resolve to an ``Etc/GMT±N`` zone. Those are real IANA
    names but they are fixed offsets with no daylight-saving rules, so a site
    that lands on one is almost certainly a mistyped coordinate - better to
    return nothing and let the operator look at it.
    """
    try:
        from tzfpy import get_tz
    except ImportError:  # pragma: no cover - the package is a hard dependency
        return ""

    try:
        # Note the argument order: tzfpy takes longitude first.
        zone = get_tz(float(longitude), float(latitude)) or ""
    except (TypeError, ValueError):
        return ""
    return "" if zone.startswith("Etc/") else zone


def _throttle() -> None:
    """Serialise outbound calls, because the usage policy is per client."""
    global _last_call
    with _lock:
        elapsed = time.monotonic() - _last_call
        if elapsed < _MIN_INTERVAL_SECONDS:
            time.sleep(_MIN_INTERVAL_SECONDS - elapsed)
        _last_call = time.monotonic()


def is_enabled() -> bool:
    return bool(settings.GEOCODING["ENABLED"] and settings.GEOCODING["ENDPOINT"])


def search(address: str, *, limit: int = 5, language: str = "") -> list[Place]:
    """Look up an address. Returns ``[]` for anything that did not work.

    Never raises. Every failure mode - disabled, offline, rate limited, garbage
    response - reaches the caller as "no results", because the caller's job in
    all four cases is identical: let the operator type the numbers in.
    """
    address = (address or "").strip()
    if len(address) < 3 or not is_enabled():
        return []

    # Hashed rather than interpolated: addresses contain spaces and non-ASCII,
    # and memcached rejects both in a key. A cache that silently refuses every
    # write would leave the rate limiter as the only thing between a busy form
    # and a block.
    digest = hashlib.sha256(
        f"{language}|{limit}|{address.lower()}".encode()
    ).hexdigest()[:32]
    key = f"geocode:{digest}"
    cached = cache.get(key)
    if cached is not None:
        return [Place(**item) for item in cached]

    params = {
        "q": address,
        "format": "jsonv2",
        "limit": str(max(1, min(limit, 10))),
        # Needed for the city and country fields. Without it the caller has to
        # parse them back out of the display name, which is localised, ordered
        # differently per country, and not machine readable.
        "addressdetails": "1",
    }
    if language:
        params["accept-language"] = language

    url = f"{settings.GEOCODING['ENDPOINT']}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            # Required by the usage policy. A generic agent gets blocked.
            "User-Agent": settings.GEOCODING["USER_AGENT"],
            "Accept": "application/json",
        },
    )

    try:
        _throttle()
        with urllib.request.urlopen(
            request, timeout=settings.GEOCODING["TIMEOUT_SECONDS"]
        ) as response:
            document = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        logger.warning(
            "geocoding lookup failed",
            extra={"error": str(exc)[:200], "address": address[:120]},
        )
        return []

    places: list[Place] = []
    for item in document if isinstance(document, list) else []:
        try:
            latitude = float(item["lat"])
            longitude = float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue

        detail = item.get("address") or {}
        # Nominatim files the settlement under whichever of these fits the
        # place, so there is no single key to read.
        city = ""
        for field in ("city", "town", "village", "municipality", "county", "state"):
            if detail.get(field):
                city = str(detail[field])
                break

        places.append(
            Place(
                latitude=latitude,
                longitude=longitude,
                display_name=str(item.get("display_name") or address)[:400],
                city=city[:120],
                country=str(detail.get("country_code") or "").upper()[:2],
                timezone_name=timezone_for(latitude, longitude),
            )
        )

    # Cached even when empty: a misspelled address does not become spellable by
    # being asked about again, and the rate limit is the scarce resource.
    cache.set(
        key,
        [
            {
                "latitude": p.latitude,
                "longitude": p.longitude,
                "display_name": p.display_name,
                "city": p.city,
                "country": p.country,
                "timezone_name": p.timezone_name,
            }
            for p in places
        ],
        CACHE_TTL_SECONDS,
    )
    return places
