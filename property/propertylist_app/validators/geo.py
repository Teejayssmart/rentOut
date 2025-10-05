import math
from django.core.exceptions import ValidationError

_UK_POSTCODE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "

def normalize_uk_postcode(raw: str) -> str:
    """
    Basic UK postcode normalizer:
      - strips spaces, uppercases, filters invalid chars,
      - re-inserts single space before last 3 chars when possible.
    """
    if not raw:
        raise ValidationError("Postcode is required.")
    s = "".join(ch for ch in str(raw).upper().strip() if ch in _UK_POSTCODE_CHARS).replace(" ", "")
    if len(s) < 5:
        raise ValidationError("Postcode looks too short.")
    # Insert space before last 3 chars if not present
    if len(s) > 3:
        s = s[:-3] + " " + s[-3:]
    return s.strip()

def validate_radius_miles(val, *, max_miles: int = 100) -> int:
    try:
        v = int(val)
    except Exception:
        raise ValidationError("radius_miles must be an integer")
    if v < 1 or v > max_miles:
        raise ValidationError(f"radius_miles must be between 1 and {max_miles} miles")
    return v

def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great-circle distance between two (lat, lon) points in **miles**.
    """
    R = 3958.7613  # Earth radius in miles
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl   = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dl/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 6)
