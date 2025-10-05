"""
Public facade for custom validators.

Usage everywhere:
    from propertylist_app.validators import validate_price, normalize_uk_postcode, ...
"""

# --- GEO ---
from .geo import (
    normalize_uk_postcode,
    validate_radius_miles,
    haversine_miles,
)

# --- BOOKING ---
from .booking import validate_no_booking_conflict

# --- IMAGES / FILES ---
from .images import (
    validate_avatar_image,
    validate_listing_photos,
    assert_no_duplicate_files,
)

# --- IO (network / low-level) ---
from .io import geocode_postcode

# --- SECURITY / SANITISERS / BUSINESS RULES ---
from .security import (
    # webhooks / idempotency
    verify_webhook_signature,
    ensure_webhook_not_replayed,
    ensure_idempotency,

    # text / sanitisation
    sanitize_html_description,
    sanitize_search_text,

    # domain validations
    validate_person_name,
    validate_age_18_plus,
    validate_listing_title,
    validate_price,
    validate_available_from,
    validate_choice,

    # ranges / paging / ordering
    validate_numeric_range,
    validate_pagination,
    validate_ordering,

    # normalisation + quotas
    normalise_price,
    normalise_phone,
    normalise_name,
    enforce_user_caps,
    assert_not_duplicate_listing,
)

# ---- Aliases to cover US/UK spelling imports ----
# If some code imports "normalize_price", provide an alias to normalise_price.
try:
    normalize_price  # type: ignore[name-defined]
except NameError:
    normalize_price = normalise_price  # alias

# If some code imports "normalise_uk_postcode", map it to normalize_uk_postcode.
try:
    normalise_uk_postcode  # type: ignore[name-defined]
except NameError:
    normalise_uk_postcode = normalize_uk_postcode  # alias

__all__ = [
    # geo
    "normalize_uk_postcode", "normalise_uk_postcode", "validate_radius_miles", "haversine_miles", "geocode_postcode",
    # booking
    "validate_no_booking_conflict",
    # images/files
    "validate_avatar_image", "validate_listing_photos", "assert_no_duplicate_files",
    # webhooks / idempotency
    "verify_webhook_signature", "ensure_webhook_not_replayed", "ensure_idempotency",
    # sanitizers
    "sanitize_html_description", "sanitize_search_text",
    # domain validations
    "validate_person_name", "validate_age_18_plus", "validate_listing_title",
    "validate_price", "validate_available_from", "validate_choice",
    # ranges / paging / ordering
    "validate_numeric_range", "validate_pagination", "validate_ordering",
    # normalisation / quotas
    "normalise_price", "normalize_price", "normalise_phone", "normalise_name", "enforce_user_caps",
    "assert_not_duplicate_listing",
]

