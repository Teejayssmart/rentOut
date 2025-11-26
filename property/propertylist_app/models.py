from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q, F, CheckConstraint
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.text import slugify

from django.contrib.auth import get_user_model
from uuid import uuid4


# ---------------------------
# Soft-delete base + queryset
# ---------------------------
class SoftDeleteQuerySet(models.QuerySet):
    def alive(self):
        qs = self.filter(is_deleted=False)
        # If model has a 'status' field, also require 'active'
        try:
            field_names = {f.name for f in self.model._meta.fields}
            if "status" in field_names:
                qs = qs.filter(status="active")
        except Exception:
            pass
        return qs

    def dead(self):
        return self.filter(is_deleted=True)


class SoftDeleteModel(models.Model):
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    objects = SoftDeleteQuerySet.as_manager()

    class Meta:
        abstract = True

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at"])


# -------------
# RoomCategorie
# -------------
class RoomCategorie(models.Model):
    key = models.CharField(max_length=30, unique=True, blank=True, default="")
    name = models.CharField(max_length=30)
    about = models.TextField(max_length=150, blank=True, default="")
    website = models.URLField(max_length=100, blank=True, default="")
    slug = models.SlugField(max_length=40, unique=True, null=True, blank=True, db_index=True)
    active = models.BooleanField(default=True, db_index=True)

    def save(self, *args, **kwargs):
        # --- key: required unique; derive from name if empty ---
        if not (self.key or "").strip():
            base = slugify(self.name) or "category"
            candidate = base[:30]  # enforce max_length
            i = 2
            while RoomCategorie.objects.filter(key=candidate).exclude(pk=self.pk).exists():
                suffix = f"-{i}"
                candidate = (base[: (30 - len(suffix))] + suffix)
                i += 1
            self.key = candidate

        # --- slug: keep it unique as well ---
        if not self.slug:
            base = slugify(self.name) or slugify(self.key)
            candidate = base
            i = 2
            while RoomCategorie.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{i}"
                i += 1
            self.slug = candidate

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# ----
# Room
# ----
class Room(SoftDeleteModel):
    title = models.CharField(max_length=200)
    description = models.TextField()
    price_per_month = models.DecimalField(max_digits=8, decimal_places=2)
    location = models.CharField(max_length=255)
    category = models.ForeignKey(RoomCategorie, on_delete=models.CASCADE, related_name="room_info")
    available_from = models.DateField(default=date.today)
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    furnished = models.BooleanField(default=False)
    bills_included = models.BooleanField(default=False)
    property_owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="rooms")
    image = models.ImageField(upload_to="room_images/", null=True, blank=True)
    number_of_bedrooms = models.IntegerField(default=1)
    number_of_bathrooms = models.IntegerField(default=1)
    property_type = models.CharField(
        max_length=100,
        choices=[("flat", "Flat"), ("house", "House"), ("studio", "Studio")],
    )
    parking_available = models.BooleanField(default=False)
    avg_rating = models.FloatField(default=0)
    number_rating = models.IntegerField(default=0)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    paid_until = models.DateField(null=True, blank=True)  # listing is paid/active until this date
    STATUS_CHOICES = (("active", "Active"), ("hidden", "Hidden"))
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="active")

    def clean(self):
        super().clean()
        if self.bills_included and self.price_per_month is not None and float(self.price_per_month) < 100.0:
            raise ValidationError({"bills_included": "Bills cannot be included for such a low price."})

    def save(self, *args, **kwargs):
        if self.property_owner_id is None:
            UserModel = get_user_model()
            owner = UserModel.objects.order_by("id").first()
            if owner is None:
                owner = UserModel.objects.create_user(
                    username=f"system_{uuid4().hex[:8]}",
                    password="!auto!",
                    email=""
                )
            self.property_owner = owner

        if self.category_id is None:
            cat, _ = RoomCategorie.objects.get_or_create(
                name="General", defaults={"key": "general", "slug": "general", "active": True}
            )
            self.category = cat

        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("title"),
                condition=Q(is_deleted=False),
                name="uq_room_title_lower_alive",
            ),
        ]

    def __str__(self):
        return self.title


# ------
# Review
# ------
class Review(models.Model):
    review_user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    description = models.CharField(max_length=200, null=True)
    created = models.DateTimeField(auto_now_add=True)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="reviews")
    active = models.BooleanField(default=True)
    update = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created"]
        constraints = [
            models.UniqueConstraint(fields=["room", "review_user"], name="uq_review_once_per_room"),
        ]
        indexes = [
            models.Index(fields=["room", "review_user"]),
            models.Index(fields=["room", "created"]),
        ]

    def __str__(self):
        return f"{self.rating} | {self.room.title} | {self.review_user}"


# -----------
# UserProfile
# -----------
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    phone = models.CharField(max_length=15, unique=True, null=True, blank=True)
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)
    ROLE_CHOICES = (("landlord", "Landlord"), ("seeker", "Seeker"))
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="seeker", db_index=True)
    email_verified = models.BooleanField(default=False, db_index=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    terms_version = models.CharField(max_length=20, blank=True, default="")
    marketing_consent = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} profile"


# --------
# AuditLog
# --------
class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=200)
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    extra_data = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"{self.timestamp} - {self.user} - {self.action}"


# ---------------
# IdempotencyKey
# ---------------
class IdempotencyKey(models.Model):
    user_id = models.IntegerField(db_index=True)
    key = models.CharField(max_length=200, db_index=True)
    action = models.CharField(max_length=100)  # e.g., "create_booking" / "charge_card"
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user_id", "key", "action")


# ----------
# RoomImage
# ----------
class RoomImageQuerySet(models.QuerySet):
    def approved(self):
        return self.filter(status="approved")


class RoomImage(models.Model):
    room = models.ForeignKey("Room", on_delete=models.PROTECT)
    image = models.ImageField(upload_to="room_images/", null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # moderation status
    status = models.CharField(
        max_length=16,
        choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="pending",
        db_index=True,
    )

    objects = RoomImageQuerySet.as_manager()


# -----------------
# AvailabilitySlot
# -----------------
class AvailabilitySlot(models.Model):
    room = models.ForeignKey("Room", related_name="availability_slots", on_delete=models.CASCADE)
    start = models.DateTimeField()
    end = models.DateTimeField()
    max_bookings = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("start",)
        constraints = [
            CheckConstraint(check=Q(end__gt=F("start")), name="slot_end_after_start"),
            CheckConstraint(check=Q(max_bookings__gte=1), name="slot_max_bookings_gte_1"),
            models.UniqueConstraint(fields=["room", "start", "end"], name="unique_slot_room_start_end"),
        ]

    def __str__(self):
        return f"{self.room} | {self.start:%Y-%m-%d %H:%M} → {self.end:%Y-%m-%d %H:%M} (cap {self.max_bookings})"


# -------
# Booking
# -------
class Booking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bookings")
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="bookings")
    slot = models.ForeignKey(AvailabilitySlot, on_delete=models.PROTECT, related_name="bookings", null=True, blank=True)
    start = models.DateTimeField()
    end = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    canceled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["room", "start", "end"])]


# ---------------
# WebhookReceipt
# ---------------
class WebhookReceipt(models.Model):
    source = models.CharField(max_length=50, db_index=True)   # e.g. "provider"
    event_id = models.CharField(max_length=255, unique=True)  # used for replay protection
    received_at = models.DateTimeField(auto_now_add=True)
    payload = models.JSONField(null=True, blank=True)         # full parsed JSON payload
    headers = models.JSONField(null=True, blank=True)         # selected headers for audit


# ---------
# SavedRoom
# ---------
class SavedRoom(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="saved_rooms_links")
    room = models.ForeignKey("Room", on_delete=models.CASCADE, related_name="saved_by_links")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "room")
        indexes = [
            models.Index(fields=["user", "room"]),
            models.Index(fields=["room"]),
        ]

    def __str__(self):
        return f"{getattr(self.user, 'username', 'user')} → {getattr(self, 'room_id', '∅')}"


# -------------
# MessageThread
# -------------
class MessageThread(models.Model):
    participants = models.ManyToManyField(User, related_name="message_threads")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        users = ", ".join(self.participants.values_list("username", flat=True)[:2])
        return f"Thread {self.id} ({users}…)"


# -------
# Message
# -------
class Message(models.Model):
    thread = models.ForeignKey(MessageThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_messages")
    body = models.TextField()
    created = models.DateTimeField(auto_now_add=True, db_index=True)  # existing
    updated = models.DateTimeField(auto_now=True, db_index=True)      # NEW

    class Meta:
        ordering = ["created"]
        indexes = [
            models.Index(fields=["thread", "created"]),
            models.Index(fields=["thread", "updated"]),  # NEW helpful index
        ]


class MessageRead(models.Model):
    """Records that a given user has read a specific message."""
    message = models.ForeignKey("Message", on_delete=models.CASCADE, related_name="reads")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="message_reads")
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "user")
        indexes = [models.Index(fields=["user", "message"])]

    def __str__(self):
        return f"Read m#{self.message_id} by {self.user_id} at {self.read_at:%Y-%m-%d %H:%M:%S}"


# -----------
# Notification
# -----------
class Notification(models.Model):
    """
    Simple user notification generated by app events (e.g., a new message).
    """
    class Type(models.TextChoices):
        MESSAGE = "message", "Message"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    type = models.CharField(max_length=32, choices=Type.choices, default=Type.MESSAGE)

    # Optional pointers to the event source (keep it simple for messages)
    thread = models.ForeignKey(
        "MessageThread",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    message = models.ForeignKey(
        "Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )

    title = models.CharField(max_length=120, blank=True, default="")
    body = models.TextField(blank=True, default="")

    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read", "created_at"]),
        ]

    def __str__(self):
        return f"Notif#{self.pk} to {getattr(self.user, 'username', self.user_id)} [{self.type}]"


# -------
# Payment
# -------
class Payment(models.Model):
    class Provider(models.TextChoices):
        STRIPE = "stripe", "Stripe"

    class Status(models.TextChoices):
        REQUIRES_PAYMENT = "requires_payment_method", "Requires payment"
        REQUIRES_ACTION = "requires_action", "Requires action"
        PROCESSING = "processing", "Processing"
        SUCCEEDED = "succeeded", "Succeeded"
        CANCELED = "canceled", "Canceled"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="payments")
    room = models.ForeignKey("Room", on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")

    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.STRIPE)
    amount = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=10, default="GBP")

    stripe_payment_intent_id = models.CharField(max_length=200, blank=True, default="")
    stripe_checkout_session_id = models.CharField(max_length=200, blank=True, default="")

    status = models.CharField(max_length=40, choices=Status.choices, default=Status.REQUIRES_PAYMENT)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["room", "created_at"]),
            models.Index(fields=["stripe_payment_intent_id"]),
            models.Index(fields=["stripe_checkout_session_id"]),
        ]

    def __str__(self):
        who = getattr(self.user, "username", self.user_id)
        return f"Payment {self.id} {self.amount} {self.currency} by {who} [{self.status}]"


# ----------------
# GDPR / Privacy
# ----------------
class Report(models.Model):
    """
    Generic reports for moderation (Room, Review, Message, User, etc).
    """
    TARGET_CHOICES = (
        ("room", "Room"),
        ("review", "Review"),
        ("message", "Message"),
        ("user", "User"),
    )
    STATUS_CHOICES = (
        ("open", "Open"),
        ("in_review", "In review"),
        ("resolved", "Resolved"),
        ("rejected", "Rejected"),
    )

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reports",
    )
    target_type = models.CharField(max_length=16, choices=TARGET_CHOICES)

    # Generic relation
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    target = GenericForeignKey("content_type", "object_id")

    reason = models.CharField(max_length=64)   # e.g., "spam", "abuse", "scam", "inaccurate", "other"
    details = models.TextField(blank=True)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="open")
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="handled_reports",
    )
    resolution_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["target_type", "object_id"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"Report #{self.pk} {self.target_type}:{self.object_id} ({self.status})"


class DataExport(models.Model):
    """Tracks user data exports and where the ZIP is stored (under MEDIA_ROOT)."""
    STATUS_CHOICES = (("queued", "queued"), ("processing", "processing"), ("ready", "ready"), ("failed", "failed"))
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="data_exports")
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    file_path = models.CharField(max_length=512, blank=True, default="")  # media-relative path
    expires_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")

    def is_expired(self):
        return bool(self.expires_at and timezone.now() >= self.expires_at)


class GDPRTombstone(models.Model):
    """Minimal marker that a user was anonymised/erased (store NO PII)."""
    user_id_hash = models.CharField(max_length=128)
    anonymised_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True, default="")


# -----
# EmailOTP
# -----
class EmailOTP(models.Model):
    """
    One-time email verification codes (6-digit, stored as plain text).
    Compatible with tests and OTP views.
    """
    user = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="email_otps",
    )
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
        ]

    @property
    def is_expired(self) -> bool:
        """True if this code is past its expiry time."""
        return timezone.now() >= self.expires_at

    def matches(self, value: str) -> bool:
        """Simple equality check against the 6-digit code."""
        return self.code == (value or "").strip()

    def mark_used(self) -> None:
        """Mark the code as used right now."""
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])

    @classmethod
    def create_for(cls, user, code: str, ttl_minutes: int = 10):
        """
        Factory used by EmailOTPResendView and tests.
        Creates a fresh OTP that expires after `ttl_minutes`.
        """
        expires_at = timezone.now() + timedelta(minutes=ttl_minutes)
        return cls.objects.create(
            user=user,
            code=str(code).strip(),
            expires_at=expires_at,
        )
