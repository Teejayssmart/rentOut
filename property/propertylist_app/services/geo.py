
from __future__ import annotations

from typing import Tuple, Optional
from django.core.cache import cache
from django.conf import settings

# Reuse your existing helpers from validators (normalizer + raw geocoder + distance)
from propertylist_app.validators import normalize_uk_postcode, geocode_postcode as _raw_geocode


CACHE_PREFIX = "geo:postcode:"
# Default TTL: 7 days (in seconds)
CACHE_TTL = getattr(settings, "GEO_CACHE_TTL_SECONDS", 60 * 60 * 24 * 7)


def geocode_postcode_cached(postcode_raw: str) -> Tuple[float, float]:
    """
    Normalize the UK postcode, then return (lat, lon) using cache.
    Falls back to your existing validators.geocode_postcode for the actual lookup.
    """
    if not postcode_raw:
        raise ValueError("Postcode required")

    normal = normalize_uk_postcode(postcode_raw)
    key = f"{CACHE_PREFIX}{normal}"

    cached = cache.get(key)
    if cached and isinstance(cached, (list, tuple)) and len(cached) == 2:
        return float(cached[0]), float(cached[1])

    # Call the existing function that does the real API hit (kept in validators)
    lat, lon = _raw_geocode(normal)

    # Cache result
    cache.set(key, (lat, lon), timeout=CACHE_TTL)
    return lat, lon
