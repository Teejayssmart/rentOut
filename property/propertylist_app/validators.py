from rest_framework import serializers
import re
from datetime import date
from django.utils import timezone
from io import BytesIO
from PIL import Image  # needs: pip install Pillow
import hashlib
import decimal
from django.core.exceptions import ValidationError
from django.db.models import Q
import hmac, hashlib, time

# =========================
# USER VALIDATORS
# =========================

# 1) Email validator (block disposable + role-based)
DISPOSABLE_DOMAINS = {"mailinator.com", "10minutemail.com", "yopmail.com", "tempmail.com"}
ROLE_LOCALPARTS = {"admin", "support", "noreply", "info", "contact"}

def deny_disposable_or_role_email(value):
    # value must look like "name@domain"
    if "@" not in value:
        raise serializers.ValidationError("Enter a valid email address.")
    local, domain = value.split("@", 1)
    if domain.lower() in DISPOSABLE_DOMAINS:
        raise serializers.ValidationError("Disposable email domains are not allowed.")
    if local.lower() in ROLE_LOCALPARTS or "noreply" in local.lower():
        raise serializers.ValidationError("Role-based emails are not allowed.")
    return value


# 2) Password strength validator
COMMON_PASSWORDS = {"password", "123456", "qwerty", "letmein"}

def validate_password_strength(value):
    # at least 8 chars, has upper, lower, digit, symbol, not common
    if len(value) < 8:
        raise serializers.ValidationError("Password must be at least 8 characters.")
    if not re.search(r"[A-Z]", value):
        raise serializers.ValidationError("Password must include an uppercase letter.")
    if not re.search(r"[a-z]", value):
        raise serializers.ValidationError("Password must include a lowercase letter.")
    if not re.search(r"\d", value):
        raise serializers.ValidationError("Password must include a digit.")
    if not re.search(r"[^\w\s]", value):
        raise serializers.ValidationError("Password must include a symbol.")
    if value.lower() in COMMON_PASSWORDS:
        raise serializers.ValidationError("Password is too common.")
    return value


# 3) Phone validator (E.164 format, e.g. +447911123456)
def validate_phone_e164(value):
    if not re.fullmatch(r"^\+[1-9]\d{9,14}$", value or ""):
        raise serializers.ValidationError("Phone must be in E.164 format (+447911123456).")
    return value


# 4) Username policy (3–30, letters/numbers/_/-) + blacklist
USERNAME_BLACKLIST = {"admin", "root", "support", "owner"}
USERNAME_REGEX = re.compile(r"^[A-Za-z0-9_-]{3,30}$")

def validate_username_policy(value):
    if not USERNAME_REGEX.fullmatch(value or ""):
        raise serializers.ValidationError(
            "Username must be 3–30 chars and only contain letters, numbers, underscores, or hyphens."
        )
    if value.lower() in USERNAME_BLACKLIST:
        raise serializers.ValidationError("This username is not allowed.")
    return value


# =========================
# PROFILE VALIDATORS
# =========================

# Name: letters, spaces, hyphens, apostrophes; 1–60 chars
NAME_REGEX = re.compile(r"^[A-Za-z][A-Za-z\s\-']{0,59}$")

def validate_person_name(value):
    if not value:
        raise serializers.ValidationError("Name is required.")
    v = value.strip()
    if not NAME_REGEX.fullmatch(v):
        raise serializers.ValidationError(
            "Name may contain letters, spaces, hyphens, and apostrophes (1–60 chars)."
        )
    return v

# DOB / Age: must be 18+
def validate_age_18_plus(dob):
    if not isinstance(dob, date):
        raise serializers.ValidationError("Enter a valid date of birth.")
    today = timezone.now().date()
    # add 18 years (handle Feb 29)
    try:
        eighteenth = dob.replace(year=dob.year + 18)
    except ValueError:
        eighteenth = dob.replace(year=dob.year + 18, day=28)
    if eighteenth > today:
        raise serializers.ValidationError("You must be at least 18 years old.")
    return dob

# Avatar: JPEG/PNG/WebP, ≤5MB, min 256x256, strip EXIF
ALLOWED_IMAGE_CT = {"image/jpeg", "image/png", "image/webp"}
MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5 MB
MIN_DIMENSION = 256

def validate_avatar_image(file_obj):
    if not file_obj:
        raise serializers.ValidationError("Avatar image is required.")
    ct = getattr(file_obj, "content_type", None)
    if ct not in ALLOWED_IMAGE_CT:
        raise serializers.ValidationError("Avatar must be JPEG, PNG, or WebP.")
    if file_obj.size and file_obj.size > MAX_AVATAR_BYTES:
        raise serializers.ValidationError("Avatar must be 5 MB or smaller.")

    try:
        img = Image.open(file_obj)
        width, height = img.size
        if width < MIN_DIMENSION or height < MIN_DIMENSION:
            raise serializers.ValidationError("Avatar must be at least 256×256 pixels.")

        # remove EXIF by re-saving
        img = img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img
        out = BytesIO()
        fmt = "JPEG" if ct == "image/jpeg" else ("PNG" if ct == "image/png" else "WEBP")
        save_kwargs = {}
        if fmt == "WEBP":
            save_kwargs["method"] = 6
        img.save(out, format=fmt, **save_kwargs)
        out.seek(0)

        from django.core.files.uploadedfile import InMemoryUploadedFile
        cleaned = InMemoryUploadedFile(
            file=out,
            field_name=getattr(file_obj, 'field_name', None),
            name=file_obj.name,
            content_type=ct,
            size=out.getbuffer().nbytes,
            charset=None,
        )
        return cleaned
    except serializers.ValidationError:
        raise
    except Exception:
        raise serializers.ValidationError("Could not process avatar image. Please upload a valid image.")


# UK Postcode: validate + normalise to "OUTCODE INCODE"
UK_POSTCODE_REGEX = re.compile(
    r"""^(
        (GIR\s?0AA)|
        ((ASCN|BBND|[A-Z]{1,2}\d[A-Z\d]?|BFPO)\s?\d[ABD-HJLN-UW-Z]{2})
    )$""",
    re.IGNORECASE | re.VERBOSE,
)

def normalize_uk_postcode(value):
    if not value:
        raise serializers.ValidationError("Postcode is required.")
    raw = re.sub(r"\s+", "", value).upper()
    if not (5 <= len(raw) <= 7) or not UK_POSTCODE_REGEX.fullmatch(raw):
        raise serializers.ValidationError("Enter a valid UK postcode.")
    return f"{raw[:-3]} {raw[-3:]}"

def require_city_present(city):
    if not city or not city.strip():
        raise serializers.ValidationError("City is required.")
    return city.strip().title()


# =========================
# LISTING VALIDATORS
# =========================

# Title: 10–100 chars; no banned words
BANNED_WORDS = {"scam", "fraud", "weapon", "drugs", "hate", "racist", "xxx", "adult"}

def validate_listing_title(value, min_len=10, max_len=100):
    if not value or not isinstance(value, str):
        raise serializers.ValidationError("Title is required.")
    v = value.strip()
    if not (min_len <= len(v) <= max_len):
        raise serializers.ValidationError(f"Title must be {min_len}-{max_len} characters.")
    if any(bad in v.lower() for bad in BANNED_WORDS):
        raise serializers.ValidationError("Title contains banned or offensive words.")
    return v

# Description: min 30, max, HTML sanitised
try:
    import bleach
    def sanitize_html_description(value, min_len=30, max_len=4000):
        if not value or not isinstance(value, str):
            raise serializers.ValidationError("Description is required.")
        cleaned = bleach.clean(
            value,
            tags=["b", "strong", "i", "em", "ul", "ol", "li", "br", "p"],
            attributes={},
            strip=True,
        )
        text_only = bleach.clean(cleaned, tags=[], strip=True)
        if len(text_only.strip()) < min_len:
            raise serializers.ValidationError(f"Description must be at least {min_len} characters.")
        if len(cleaned) > max_len:
            raise serializers.ValidationError(f"Description must be no more than {max_len} characters.")
        return cleaned
except Exception:
    def sanitize_html_description(value, min_len=30, max_len=4000):
        if not value or not isinstance(value, str):
            raise serializers.ValidationError("Description is required.")
        cleaned = re.sub(r"<[^>]+>", "", value).strip()
        if len(cleaned) < min_len:
            raise serializers.ValidationError(f"Description must be at least {min_len} characters.")
        if len(cleaned) > max_len:
            raise serializers.ValidationError(f"Description must be no more than {max_len} characters.")
        return cleaned

# Price: numeric, positive, sensible range
def validate_price(value, min_val=10.0, max_val=20000.0):
    try:
        amt = float(value)
    except Exception:
        raise serializers.ValidationError("Price must be a number.")
    if amt <= 0:
        raise serializers.ValidationError("Price must be positive.")
    if not (min_val <= amt <= max_val):
        raise serializers.ValidationError(f"Price must be between {min_val:g} and {max_val:g}.")
    return amt

# Rent period normaliser
def normalize_rent_period(value):
    if not value:
        return "month"
    v = str(value).strip().lower()
    if v in {"pm", "per month", "monthly", "month"}:
        return "month"
    if v in {"pw", "per week", "weekly", "week"}:
        return "week"
    raise serializers.ValidationError("Rent period must be 'week' or 'month'.")

# Deposit: ≤ 5 weeks’ rent (if AST applies)
def validate_deposit(deposit, rent_amount, rent_period="month", ast_applies=True):
    dep = validate_price(deposit, min_val=0.0, max_val=500000.0)
    if not ast_applies:
        return dep
    period = normalize_rent_period(rent_period)
    weekly_rent = (float(rent_amount) / 4.345) if period == "month" else float(rent_amount)
    max_dep = 5.0 * weekly_rent
    if dep > max_dep + 1e-6:
        raise serializers.ValidationError("Deposit cannot exceed 5 weeks’ rent (AST rule).")
    return dep

# Availability date: today or later
def validate_available_from(d):
    if not isinstance(d, date):
        raise serializers.ValidationError("Enter a valid date.")
    if d < timezone.now().date():
        raise serializers.ValidationError("Availability date cannot be in the past.")
    return d

# Enum choices helper (e.g., property_type)
def validate_choice(value, allowed, label="value"):
    if value not in allowed:
        raise serializers.ValidationError(f"{label} must be one of: {', '.join(sorted(allowed))}.")
    return value

# Occupancy: min ≤ max
def validate_min_lte_max(min_val, max_val, label_min="min", label_max="max"):
    try:
        a = int(min_val)
        b = int(max_val)
    except Exception:
        raise serializers.ValidationError("Occupancy limits must be integers.")
    if a < 0 or b < 0:
        raise serializers.ValidationError("Occupancy limits cannot be negative.")
    if a > b:
        raise serializers.ValidationError(f"{label_min} cannot be greater than {label_max}.")
    return a, b

# Photos: count/types/size/dimensions
ALLOWED_IMAGE_CT_LISTING = {"image/jpeg", "image/png", "image/webp"}
MAX_FILES = 10
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB
MIN_DIM = 600

def validate_listing_photos(files):
    if not files or len(files) == 0:
        raise serializers.ValidationError("At least one photo is required.")
    if len(files) > MAX_FILES:
        raise serializers.ValidationError(f"No more than {MAX_FILES} photos allowed.")
    cleaned_files = []
    for f in files:
        ct = getattr(f, "content_type", None)
        if ct not in ALLOWED_IMAGE_CT_LISTING:
            raise serializers.ValidationError("Photos must be JPEG, PNG, or WebP.")
        if getattr(f, "size", 0) > MAX_FILE_BYTES:
            raise serializers.ValidationError("Each photo must be 5 MB or smaller.")
        try:
            img = Image.open(f)
            w, h = img.size
            if w < MIN_DIM or h < MIN_DIM:
                raise serializers.ValidationError(f"Each photo must be at least {MIN_DIM}×{MIN_DIM} pixels.")
            cleaned_files.append(f)
        except Exception:
            raise serializers.ValidationError("One or more photos are invalid or corrupted.")
    return cleaned_files

# Booleans
def ensure_boolean(value, label="value"):
    if isinstance(value, bool):
        return value
    raise serializers.ValidationError(f"{label} must be true or false.")

# House rules: cap length; block discriminatory phrases
DISALLOWED_DISCRIMINATION = {
    "no blacks", "no asians", "whites only", "men only", "women only",
    "no disabled", "no lgbt", "christians only", "muslims only"
}

def validate_house_rules(text, max_len=1500):
    if not isinstance(text, str):
        raise serializers.ValidationError("House rules must be text.")
    cleaned = text.strip()
    if len(cleaned) > max_len:
        raise serializers.ValidationError(f"House rules must be no more than {max_len} characters.")
    low = cleaned.lower()
    if any(phrase in low for phrase in DISALLOWED_DISCRIMINATION):
        raise serializers.ValidationError("House rules contain discriminatory wording, which is not allowed.")
    return cleaned


# =========================
# SEARCH & FILTERS
# =========================

# q: keep only safe characters and trim length
def sanitize_search_text(value, max_len=120):
    if value is None:
        return ""
    # remove anything not allowed (simple allowlist)
    cleaned = re.sub(r"[^A-Za-z0-9\s\-,.'()/]", "", str(value))
    cleaned = cleaned.strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip()
    return cleaned

# ordering: allow only whitelisted fields (supports "-field")
def validate_ordering(value, allowed_fields):
    if not value:
        return ""
    v = value.strip()
    parts = [p.strip() for p in v.split(",") if p.strip()]
    for p in parts:
        base = p[1:] if p.startswith("-") else p
        if base not in allowed_fields:
            raise serializers.ValidationError(
                f"Invalid sort field '{base}'. Allowed: {', '.join(sorted(allowed_fields))}."
            )
    return ",".join(parts)

# numeric range: min <= max
def validate_numeric_range(min_val, max_val, label_min="min", label_max="max"):
    if min_val is None or max_val is None:
        return
    try:
        a = float(min_val)
        b = float(max_val)
    except Exception:
        raise serializers.ValidationError({label_min: "Range values must be numbers."})
    if a > b:
        raise serializers.ValidationError({label_min: f"{label_min} cannot be greater than {label_max}."})

# radius in km: 0..max_km
def validate_radius_km(value, max_km=100):
    if value is None or value == "":
        return 0.0
    try:
        v = float(value)
    except Exception:
        raise serializers.ValidationError("Radius must be a number (km).")
    if v < 0:
        raise serializers.ValidationError("Radius cannot be negative.")
    if v > max_km:
        raise serializers.ValidationError(f"Radius cannot exceed {max_km} km.")
    return v

# pagination: limit ≤ max_limit; page ≥ 1; offset ≥ 0
def validate_pagination(limit, page, offset, max_limit=50):
    if limit is not None:
        try:
            l = int(limit)
        except Exception:
            raise serializers.ValidationError({"limit": "Limit must be an integer."})
        if l < 1 or l > max_limit:
            raise serializers.ValidationError({"limit": f"Limit must be between 1 and {max_limit}."})
    if page is not None:
        try:
            p = int(page)
        except Exception:
            raise serializers.ValidationError({"page": "Page must be an integer."})
        if p < 1:
            raise serializers.ValidationError({"page": "Page must be ≥ 1."})
    if offset is not None:
        try:
            o = int(offset)
        except Exception:
            raise serializers.ValidationError({"offset": "Offset must be an integer."})
        if o < 0:
            raise serializers.ValidationError({"offset": "Offset must be ≥ 0."})



# =========================
# BOOKINGS / PAYMENTS VALIDATORS
# =========================

# Amounts: must be positive and within sensible range
def validate_amount(value, min_val=1.0, max_val=20000.0):
    try:
        amt = float(value)
    except Exception:
        raise serializers.ValidationError("Amount must be a number.")
    if amt <= 0:
        raise serializers.ValidationError("Amount must be positive.")
    if not (min_val <= amt <= max_val):
        raise serializers.ValidationError(f"Amount must be between {min_val:g} and {max_val:g}.")
    return amt

# Currency: only GBP allowed
def validate_currency(value):
    if str(value).upper() != "GBP":
        raise serializers.ValidationError("Only GBP currency is supported.")
    return "GBP"

# Dates/times: must be in the future
def validate_future_datetime(dt):
    if not dt:
        raise serializers.ValidationError("Date/time is required.")
    if dt < timezone.now():
        raise serializers.ValidationError("Date/time must be in the future.")
    return dt

# Check for booking clashes (simplified — you’ll need to query DB in views)
def validate_booking_no_clash(start_dt, end_dt, existing_bookings):
    if start_dt >= end_dt:
        raise serializers.ValidationError("End time must be after start time.")
    for b in existing_bookings:
        if not (end_dt <= b.start or start_dt >= b.end):
            raise serializers.ValidationError("Booking dates clash with an existing booking.")
    return start_dt, end_dt

# Card details: basic Luhn check for card number
def luhn_check(card_number):
    num = str(card_number).replace(" ", "")
    if not num.isdigit():
        raise serializers.ValidationError("Card number must contain only digits.")
    total = 0
    reverse_digits = num[::-1]
    for i, d in enumerate(reverse_digits):
        n = int(d)
        if i % 2 == 1:  # double every second digit
            n *= 2
            if n > 9:
                n -= 9
        total += n
    if total % 10 != 0:
        raise serializers.ValidationError("Card number is invalid.")
    return num

# Card expiry: must be in future
def validate_card_expiry(month, year):
    try:
        m = int(month)
        y = int(year)
    except Exception:
        raise serializers.ValidationError("Expiry month/year must be numbers.")
    if not (1 <= m <= 12):
        raise serializers.ValidationError("Expiry month must be 1–12.")
    today = timezone.now().date()
    if y < today.year or (y == today.year and m < today.month):
        raise serializers.ValidationError("Card expiry date must be in the future.")
    return m, y

# CVV: only validate format, do not store it
def validate_cvv(cvv):
    if not re.fullmatch(r"\d{3,4}", str(cvv)):
        raise serializers.ValidationError("CVV must be 3 or 4 digits.")
    return cvv  # do not save to DB, just use for processing

# Refunds / cancellations: basic check — policy-driven
def validate_refund_policy(action, booking):
    # example rules — adjust as needed
    if action == "refund":
        if not booking.is_refundable:
            raise serializers.ValidationError("This booking is non-refundable.")
    if action == "cancel":
        if booking.start <= timezone.now():
            raise serializers.ValidationError("Cannot cancel after booking has started.")
    return action

# Identity / KYC: must provide legal name, DOB, address
def validate_kyc(data):
    if not data.get("name"):
        raise serializers.ValidationError("Legal name is required for KYC.")
    if not data.get("dob"):
        raise serializers.ValidationError("Date of birth is required for KYC.")
    if not data.get("address"):
        raise serializers.ValidationError("Address is required for KYC.")
    # you would usually pass this data to an external provider (like Stripe, Onfido)
    return data



# =========================
# REVIEWS & RATINGS VALIDATORS
# =========================

# Rating: must be integer 1–5
def validate_rating(value):
    try:
        r = int(value)
    except Exception:
        raise serializers.ValidationError("Rating must be a number 1–5.")
    if r < 1 or r > 5:
        raise serializers.ValidationError("Rating must be between 1 and 5.")
    return r

# Text: optional or required, with length limits
def validate_review_text(value, required=False, min_len=10, max_len=1000):
    if not value or str(value).strip() == "":
        if required:
            raise serializers.ValidationError("Review text is required.")
        return ""  # allow empty if optional
    text = str(value).strip()
    if len(text) < min_len:
        raise serializers.ValidationError(f"Review text must be at least {min_len} characters.")
    if len(text) > max_len:
        raise serializers.ValidationError(f"Review text must be no more than {max_len} characters.")
    return text

# Eligibility: one review per stay; no self-reviews
def validate_review_eligibility(user, room, existing_reviews):
    # only one review per user/room
    if existing_reviews.filter(review_user=user, room=room).exists():
        raise serializers.ValidationError("You have already reviewed this room.")
    # user cannot review their own room
    if room.property_owner == user:
        raise serializers.ValidationError("You cannot review your own room.")
    return True

# Edits: only within allowed time window (e.g., 7 days)
def validate_review_edit(review, days_limit=7):
    limit_date = review.created + timezone.timedelta(days=days_limit)
    if timezone.now() > limit_date:
        raise serializers.ValidationError(
            f"Reviews can only be edited within {days_limit} days of posting."
        )
    return True

# (Optional) moderation check — block banned/offensive words
BANNED_REVIEW_WORDS = {"scam", "fraud", "hate", "racist", "fake", "spam"}

def validate_review_moderation(text):
    if not text:
        return text
    lower = str(text).lower()
    if any(bad in lower for bad in BANNED_REVIEW_WORDS):
        raise serializers.ValidationError("Review contains inappropriate or offensive words.")
    return text






# ---------- Normalisation ----------

def normalise_price(value):
    """Decimal, 2dp, non-negative."""
    try:
        d = decimal.Decimal(str(value)).quantize(decimal.Decimal("0.01"))
    except Exception:
        raise ValidationError("Price must be a number.")
    if d < 0:
        raise ValidationError("Price cannot be negative.")
    return d

_UK_PHONE_RE = re.compile(r"^\+?[0-9\s\-()]{7,20}$")

def normalise_phone(value: str) -> str:
    """Simple E.164-ish clean (no library): keep + and digits."""
    if not value:
        return value
    cleaned = re.sub(r"[^\d+]", "", value)
    if not _UK_PHONE_RE.fullmatch(cleaned):
        raise ValidationError("Phone format is invalid.")
    return cleaned

def normalise_name(value: str) -> str:
    """Trim and title-case (keeps apostrophes/hyphens sensible)."""
    v = (value or "").strip()
    if not v:
        raise ValidationError("Name is required.")
    return re.sub(r"\s+", " ", v).title()


# ---------- Photo hashing & reuse ----------

def image_sha256(file_obj) -> str:
    """Return SHA-256 hex digest of an uploaded image file."""
    pos = file_obj.tell() if hasattr(file_obj, "tell") else None
    file_obj.seek(0)
    h = hashlib.sha256()
    for chunk in iter(lambda: file_obj.read(8192), b""):
        h.update(chunk)
    digest = h.hexdigest()
    try:
        file_obj.seek(pos or 0)
    except Exception:
        pass
    return digest

def assert_no_duplicate_files(files) -> None:
    """Ensure the same photo isn’t uploaded twice in this request."""
    seen = set()
    for f in files or []:
        dig = image_sha256(f)
        if dig in seen:
            raise ValidationError("Duplicate photo uploaded in this listing.")
        seen.add(dig)

def assert_photos_not_seen_before(files, photo_qs, hash_field: str = "hash") -> None:
    """
    Ensure none of the uploaded photos match an existing stored hash.
    - photo_qs: queryset over a Photo/RoomImage model that has a stored hash field.
    """
    if not files:
        return
    new_hashes = [image_sha256(f) for f in files]
    existing = set(photo_qs.filter(**{f"{hash_field}__in": new_hashes})
                             .values_list(hash_field, flat=True))
    if existing:
        raise ValidationError("One or more photos have been used before.")


# ---------- Duplicate listing detection ----------

def assert_not_duplicate_listing(
    *,
    title: str,
    postcode_normalised: str,
    room_qs,
    exclude_room_id=None,
) -> None:
    """
    Detect duplicates by (normalised title + normalised postcode).
    - room_qs: queryset over Room model.
    - assumes Room has stored normalised fields, e.g. title_norm/postcode_norm, or you filter with icontains.
    """
    qs = room_qs
    if exclude_room_id:
        qs = qs.exclude(pk=exclude_room_id)
    if qs.filter(title__iexact=title.strip(),
                 location__iendswith=postcode_normalised).exists():
        raise ValidationError("A similar listing (title + postcode) already exists.")



def ensure_idempotency(user_id: int, key: str, action: str, payload_bytes: bytes, idem_qs):
    """
    - key: taken from 'Idempotency-Key' header (or similar)
    - idem_qs: IdempotencyKey.objects
    """
    if not key:
        raise ValidationError("Missing Idempotency-Key.")
    req_hash = hashlib.sha256(payload_bytes or b"").hexdigest()
    exists = idem_qs.filter(user_id=user_id, key=key, action=action).exists()
    if exists:
        raise ValidationError("Duplicate request (idempotency).")
    return {"request_hash": req_hash}



def validate_no_booking_conflict(room, start_dt, end_dt, booking_qs, exclude_id=None):
    """
    Overlap rule: (start < existing_end) AND (end > existing_start)
    """
    qs = booking_qs.filter(room=room)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    conflict = qs.filter(
        Q(start__lt=end_dt) & Q(end__gt=start_dt)
    ).exists()
    if conflict:
        raise ValidationError("Selected dates clash with an existing booking.")
    
    
def enforce_cap(current_count: int, limit: int, label: str):
    if current_count >= limit:
        raise ValidationError(f"Max {label} limit reached ({limit}).")

def enforce_user_caps(user, *, listings_qs=None, messages_qs=None, uploads_qs=None,
                      max_listings=5, max_messages_per_day=200, max_uploads=50):
    if listings_qs is not None:
        enforce_cap(listings_qs.filter(property_owner=user, is_deleted=False).count(), max_listings, "active listings")
    if messages_qs is not None:
        # if you track per-day counts, filter by date=timezone.now().date()
        enforce_cap(messages_qs.filter(sender=user).count(), max_messages_per_day, "messages")
    if uploads_qs is not None:
        enforce_cap(uploads_qs.filter(owner=user).count(), max_uploads, "uploads")    
        
def verify_webhook_signature(*, secret: str, payload: bytes, signature_header: str, scheme="sha256=", clock_skew=300):
    """
    signature_header example: "sha256=HEX, t=TIMESTAMP"
    - Verifies HMAC(secret, payload) == hex
    - Enforces timestamp within +/- clock_skew seconds to prevent replays
    """
    if not signature_header or scheme not in signature_header:
        raise ValidationError("Missing or invalid webhook signature header.")

    # parse "sha256=... , t=..."
    parts = [p.strip() for p in signature_header.split(",")]
    sig_hex = None
    ts = None
    for p in parts:
        if p.startswith(scheme):
            sig_hex = p[len(scheme):]
        elif p.startswith("t="):
            try:
                ts = int(p[2:])
            except Exception:
                pass
    if not sig_hex or not ts:
        raise ValidationError("Invalid webhook signature header format.")

    # timestamp window
    now = int(time.time())
    if abs(now - ts) > clock_skew:
        raise ValidationError("Webhook timestamp outside acceptable window.")

    # HMAC
    computed = hmac.new(key=secret.encode(), msg=payload, digestmod=hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, sig_hex):
        raise ValidationError("Invalid webhook signature.")

    return {"timestamp": ts, "signature": sig_hex}


def ensure_webhook_not_replayed(event_id: str, receipt_qs):
    """
    - event_id: unique ID provided by the sender in headers/payload
    - receipt_qs: WebhookReceipt.objects
    """
    if not event_id:
        raise ValidationError("Missing webhook event ID.")
    if receipt_qs.filter(event_id=event_id).exists():
        raise ValidationError("Duplicate webhook (replay).")        