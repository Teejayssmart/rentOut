import json, urllib.request
from django.core.exceptions import ValidationError

# Low-level geocode that **does network I/O** (kept separate from pure validators).
# It's intentionally simple; your services layer wraps this with caching.

def geocode_postcode(postcode: str):
    """
    Dummy example using postcodes.io (UK). Replace with your real provider.
    Returns (lat, lon) as floats or raises ValidationError.
    """
    if not postcode:
        raise ValidationError("Postcode required.")
    url = f"https://api.postcodes.io/postcodes/{urllib.parse.quote(postcode)}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        raise ValidationError("Failed to geocode postcode.")
    if data.get("status") != 200 or not data.get("result"):
        raise ValidationError("Postcode not found.")
    res = data["result"]
    return float(res["latitude"]), float(res["longitude"])
