import os, json, zipfile, hashlib
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from django.core.files.storage import default_storage
from django.db.models import Q
from django.core.files.storage import FileSystemStorage


from propertylist_app.models import (
    Room, Review, RoomImage, SavedRoom, MessageThread, Message, MessageRead,
    Booking, AvailabilitySlot, Payment, Report, AuditLog, DataExport, GDPRTombstone
)

def _safe_media_read(path: str) -> bytes:
    try:
        with default_storage.open(path, "rb") as f:
            return f.read()
    except Exception:
        return b""

def _user_hash(user) -> str:
    salt = getattr(settings, "GDPR_HASH_SALT", "change-me")
    return hashlib.sha256(f"{salt}:{user.pk}".encode()).hexdigest()

def _retention_days(key, default_days):
    return int(getattr(settings, "GDPR_RETENTION", {}).get(key, default_days))

def collect_user_data(user):
    """Return serialisable dict of the user’s data across your models."""
    data = {
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "date_joined": getattr(user, "date_joined", None),
            "last_login": getattr(user, "last_login", None),
        },
        "profile": {},
        "rooms": list(Room.objects.filter(property_owner=user).values()),
        "reviews": list(Review.objects.filter(Q(reviewer=user) | Q(reviewee=user)).values()),
        "saved_rooms": list(SavedRoom.objects.filter(user=user).values()),
        "threads": list(MessageThread.objects.filter(participants=user).values("id", "created_at")),
        "messages": list(Message.objects.filter(thread__participants=user, sender=user).values()),
        "bookings": list(Booking.objects.filter(user=user).values()),
        "payments": list(Payment.objects.filter(user=user).values()),
        "reports":  list(Report.objects.filter(reporter=user).values()),
        "audit": [],
    }
    # Profile (defensive – your current model only has phone)
    profile = getattr(user, "profile", None)
    if profile:
        data["profile"] = {
            "phone": getattr(profile, "phone", None),
            "address": getattr(profile, "address", None) if hasattr(profile, "address") else None,
            "postcode": getattr(profile, "postcode", None) if hasattr(profile, "postcode") else None,
            "avatar": getattr(getattr(profile, "avatar", None), "name", None) if hasattr(profile, "avatar") else None,
        }
    try:
        data["audit"] = list(AuditLog.objects.filter(user=user).values())
    except Exception:
        pass
    return data

@transaction.atomic
def preview_erasure(user):
    return {
        "delete": {
            # Profile in your schema holds phone; treat as PII container
            "profile": 1 if hasattr(user, "profile") else 0,
        },
        "anonymise": {
            "rooms": Room.objects.filter(property_owner=user, is_deleted=False).count(),
            "reviews": Review.objects.filter(Q(reviewer=user) | Q(reviewee=user)).count(),
            "messages": Message.objects.filter(sender=user).count(),
        },
        "retain_non_pii": {
            "payments": Payment.objects.filter(user=user).count(),
            "bookings": Booking.objects.filter(user=user).count(),
        }
    }

@transaction.atomic
def perform_erasure(user):
    """
    Redact PII on user/profile, anonymise authored content, and keep accounting data without personal links.
    """
    # Redact user core info and deactivate
    user.email = f"deleted+{user.id}@example.invalid"
    user.first_name = ""
    user.last_name = ""
    user.username = f"deleted_user_{user.id}"
    user.is_active = False
    user.save()

    # Profile (defensive for optional fields)
    profile = getattr(user, "profile", None)
    if profile:
        if hasattr(profile, "phone"):    profile.phone = ""
        if hasattr(profile, "address"):  profile.address = ""
        if hasattr(profile, "postcode"): profile.postcode = ""
        if hasattr(profile, "avatar") and getattr(profile, "avatar"):
            try:
                default_storage.delete(profile.avatar.name)
            except Exception:
                pass
            profile.avatar = None
        profile.save()

    # Content → anonymise (keep useful marketplace data)
    Room.objects.filter(property_owner=user).update(property_owner=None)
    Review.objects.filter(reviewer=user).update(reviewer=None)
    Review.objects.filter(reviewee=user).update(reviewee=None)
    Message.objects.filter(sender=user).update(sender=None)

    # Accounting/booking → drop personal link but keep record
    Payment.objects.filter(user=user).update(user=None)
    Booking.objects.filter(user=user).update(user=None)

    GDPRTombstone.objects.create(user_id_hash=_user_hash(user), note="GDPR erasure")
    return True


def build_export_zip(user, export_obj: DataExport) -> str:
    """
    Create ZIP under MEDIA_ROOT/exports/<user_id>/export_<ts>.zip.
    Returns the media-relative path.
    """
    ts = timezone.now().strftime("%Y%m%dT%H%M%S")
    rel_dir = os.path.join("exports", str(user.id))
    rel_zip = os.path.join(rel_dir, f"export_{ts}.zip")

    storage = FileSystemStorage(location=settings.MEDIA_ROOT, base_url=settings.MEDIA_URL)

    abs_path = storage.path(rel_zip)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    payload = collect_user_data(user)

    media_to_embed = []
    avatar_rel = (payload.get("profile") or {}).get("avatar")
    if avatar_rel:
        media_to_embed.append(("media/" + avatar_rel, avatar_rel))

    with zipfile.ZipFile(abs_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(payload, default=str, indent=2))
        for arcname, storage_path in media_to_embed:
            blob = _safe_media_read(storage_path)
            if blob:
                zf.writestr(arcname, blob)

    export_obj.status = "ready"
    export_obj.file_path = rel_zip
    export_obj.expires_at = timezone.now() + timedelta(days=_retention_days("export_link_days", 7))
    export_obj.save(update_fields=["status", "file_path", "expires_at"])
    return rel_zip
