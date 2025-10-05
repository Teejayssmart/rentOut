import re
import hmac, hashlib, json
from django.core.exceptions import ValidationError
from datetime import date
from decimal import Decimal, InvalidOperation
from django.utils import timezone
from django.db.models import Q


def verify_webhook_signature(*, secret: str, payload: bytes, signature_header: str, scheme: str = "sha256=", clock_skew: int = 300):
    """
    Generic HMAC verification: header must look like "sha256=<hex>" (default).
    """
    if not signature_header or not signature_header.startswith(scheme):
        raise ValidationError("Missing or invalid webhook signature header.")
    provided_hex = signature_header[len(scheme):].strip()
    mac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256)
    expected_hex = mac.hexdigest()
    if not hmac.compare_digest(provided_hex, expected_hex):
        raise ValidationError("Webhook signature mismatch.")

def ensure_webhook_not_replayed(event_id: str, receipt_qs):
    """
    Guard against replay: raise if a receipt with this event_id already exists.
    """
    if not event_id:
        raise ValidationError("Missing webhook event id.")
    if receipt_qs.filter(event_id=event_id).exists():
        raise ValidationError("Duplicate webhook event.")

def ensure_idempotency(*, user_id: int, key: str, action: str, payload_bytes: bytes, idem_qs):
    """
    Check if the same (user, action, hash) already processed.
    Returns a dict with 'request_hash'.
    """
    if not key:
        raise ValidationError("Missing Idempotency-Key header.")
    req_hash = hashlib.sha256(payload_bytes or b"").hexdigest()
    existing = idem_qs.filter(user_id=user_id, action=action, request_hash=req_hash, key=key).first()
    return {"request_hash": req_hash, "existing": existing}






# Optional: upgrade sanitisation if 'bleach' is available.
try:
    import bleach
    _HAS_BLEACH = True
except Exception:
    _HAS_BLEACH = False


def sanitize_html_description(text: str, *, max_len: int = 10_000) -> str:
    """
    Clean user-supplied HTML for listing descriptions.
    - If 'bleach' is available, allow a safe subset of tags/attributes.
    - Otherwise, strip all tags as a conservative fallback.
    - Enforces a max length.
    """
    text = (text or "").strip()

    if len(text) > max_len:
        raise ValidationError(f"Description too long (max {max_len} chars).")

    if _HAS_BLEACH:
        allowed_tags = [
            "b", "i", "em", "strong", "u", "br", "p", "ul", "ol", "li", "span",
            "blockquote", "code", "pre", "a"
        ]
        allowed_attrs = {"a": ["href", "title", "rel", "target"], "span": ["style"]}
        allowed_protocols = ["http", "https", "mailto"]
        cleaned = bleach.clean(
            text,
            tags=allowed_tags,
            attributes=allowed_attrs,
            protocols=allowed_protocols,
            strip=True,
        )
        # Optionally linkify plain URLs:
        try:
            cleaned = bleach.linkify(cleaned, callbacks=[bleach.linkifier.NOFOLLOW, bleach.linkifier.TargetBlank()])
        except Exception:
            # Older bleach versions may not support this API—ignore gracefully.
            pass
        return cleaned

    # Fallback: remove all HTML tags
    return re.sub(r"<[^>]*>", "", text)


def sanitize_search_text(text: str, *, max_len: int = 200) -> str:
    """
    Normalise free-text search input:
      - Trim, collapse whitespace
      - Restrict length (to avoid excessive query payloads)
      - Remove control chars
    """
    text = (text or "").strip()
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    # Remove control characters
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    if len(text) > max_len:
        text = text[:max_len].rstrip()
    return text


NAME_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ' -]{2,100}$")  # supports accents, spaces, hyphens, apostrophes
UK_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.I)


# ------------- Person / Profile -------------

def validate_person_name(value: str) -> str:
    """Basic human name validation."""
    value = (value or "").strip()
    if not value:
        raise ValidationError("Name is required.")
    if not NAME_RE.match(value):
        raise ValidationError("Enter a valid name.")
    return value


def validate_age_18_plus(dob: date) -> date:
    """Ensure user is at least 18."""
    if not isinstance(dob, date):
        raise ValidationError("Enter a valid date of birth.")
    today = timezone.now().date()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if age < 18:
        raise ValidationError("You must be at least 18 years old.")
    return dob


def normalise_name(value: str) -> str:
    """Trim and collapse whitespace in names."""
    value = (value or "").strip()
    value = re.sub(r"\s+", " ", value)
    return value


def normalise_phone(value: str) -> str:
    """Very light E.164-ish normaliser (keeps digits + optional leading '+')."""
    value = (value or "").strip()
    value = re.sub(r"[^\d+]", "", value)
    # optional: basic sanity
    if len(value.replace("+", "")) < 7:
        raise ValidationError("Enter a valid phone number.")
    return value


# ------------- Listing fields -------------

def validate_listing_title(value: str) -> str:
    """Reasonable constraints on listing titles."""
    value = (value or "").strip()
    if not value:
        raise ValidationError("Title is required.")
    if len(value) < 5:
        raise ValidationError("Title is too short (min 5 characters).")
    if len(value) > 120:
        raise ValidationError("Title is too long (max 120 characters).")
    return value


def validate_price(value, *, min_val: float = 0.0, max_val: float = 1_000_000.0) -> Decimal:
    """Ensure price is a Decimal within range."""
    try:
        dec = Decimal(value)
    except (InvalidOperation, TypeError):
        raise ValidationError("Enter a valid price.")
    if dec < Decimal(str(min_val)) or dec > Decimal(str(max_val)):
        raise ValidationError(f"Price must be between {min_val} and {max_val}.")
    # 2 dp typical for currency
    return dec.quantize(Decimal("0.01"))


def normalise_price(value) -> Decimal:
    """Coerce price-like strings (e.g. '£1,250.50') to Decimal(1250.50)."""
    if value is None:
        raise ValidationError("Price is required.")
    if isinstance(value, (int, float, Decimal)):
        return validate_price(value)
    # strip currency symbols and commas
    cleaned = str(value).strip()
    cleaned = cleaned.replace(",", "")
    cleaned = re.sub(r"[^\d.]", "", cleaned)
    return validate_price(cleaned)


def validate_available_from(d: date) -> date:
    """Date must be today or in the future (not in the past)."""
    if not isinstance(d, date):
        raise ValidationError("Enter a valid date.")
    if d < timezone.now().date():
        raise ValidationError("available_from cannot be in the past.")
    return d


def validate_choice(value, allowed, *, label="value"):
    """Ensure value belongs to an allowed set."""
    if value not in set(allowed):
        raise ValidationError(f"{label} must be one of: {', '.join(map(str, allowed))}.")
    return value


# ------------- Ranges / Pagination / Ordering -------------

def validate_numeric_range(min_v, max_v, *, label_min="min", label_max="max"):
    """Ensure min <= max when both provided."""
    if min_v is None or max_v is None:
        return
    try:
        if Decimal(min_v) > Decimal(max_v):
            raise ValidationError({label_min: f"{label_min} cannot be greater than {label_max}."})
    except (InvalidOperation, TypeError):
        raise ValidationError("Enter valid numeric bounds.")
    return (min_v, max_v)


def validate_pagination(limit=None, page=None, offset=None, *, max_limit=100):
    """Basic pagination sanity: limit positive and <= max; page/offset non-negative."""
    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ValidationError({"limit": "limit must be an integer."})
        if limit <= 0 or limit > max_limit:
            raise ValidationError({"limit": f"limit must be between 1 and {max_limit}."})
    if page is not None:
        try:
            page = int(page)
        except (TypeError, ValueError):
            raise ValidationError({"page": "page must be an integer."})
        if page < 0:
            raise ValidationError({"page": "page cannot be negative."})
    if offset is not None:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise ValidationError({"offset": "offset must be an integer."})
        if offset < 0:
            raise ValidationError({"offset": "offset cannot be negative."})
    return {"limit": limit, "page": page, "offset": offset}


def validate_ordering(ordering: str, allowed_fields: set[str]):
    """Validate comma-separated ordering fields against a whitelist."""
    ordering = (ordering or "").strip()
    if not ordering:
        return ordering
    parts = [p.strip() for p in ordering.split(",") if p.strip()]
    for p in parts:
        base = p[1:] if p.startswith("-") else p
        if base not in allowed_fields:
            raise ValidationError({"ordering": f"Unsupported ordering field: {base}"})
    return ",".join(parts)


# ------------- Quotas / Business caps -------------

def enforce_user_caps(user, *, listings_qs, max_listings: int = 5):
    """
    Enforce a maximum number of active (non-deleted, visible) listings per user.
    Expect listings_qs to be Room.objects (or similar).
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise ValidationError("Authentication required.")
    # Consider alive()/status if available
    try:
        current = listings_qs.filter(property_owner=user, is_deleted=False).count()
    except Exception:
        current = listings_qs.filter(property_owner=user).count()
    if current >= max_listings:
        raise ValidationError(f"You have reached the maximum of {max_listings} active listings.")
    return True


def assert_not_duplicate_listing(
    user,
    *,
    title: str,
    queryset,
    location: str | None = None,
    exclude_pk: int | None = None,
) -> bool:
    """
    Guard against creating/updating a listing with a duplicate title (case-insensitive)
    for the same owner. Optionally also match on location.

    Args:
        user: the owner (must be authenticated)
        title: proposed listing title
        queryset: usually Room.objects (or a filtered subset)
        location: optional; if provided we also require same location to count as duplicate
        exclude_pk: exclude this PK when updating an existing row

    Raises:
        ValidationError if a duplicate exists.
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise ValidationError("Authentication required.")

    qs = queryset.filter(property_owner=user, is_deleted=False, title__iexact=title)
    if location:
        qs = qs.filter(location__iexact=location)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)

    if qs.exists():
        # tailor the message to your UX
        raise ValidationError("You already have a listing with this title.")

    return True