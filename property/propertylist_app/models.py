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
        # key: required unique; derive from name if empty
        if not (self.key or "").strip():
            base = slugify(self.name) or "category"
            candidate = base[:30]  # enforce max_length
            i = 2
            while RoomCategorie.objects.filter(key=candidate).exclude(pk=self.pk).exists():
                suffix = f"-{i}"
                candidate = base[: (30 - len(suffix))] + suffix
                i += 1
            self.key = candidate

        # slug: keep it unique as well
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
    security_deposit = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Security deposit in GBP.",
    )
    location = models.CharField(max_length=255)
    category = models.ForeignKey(
        RoomCategorie,
        on_delete=models.CASCADE,
        related_name="room_info",
    )
    available_from = models.DateField(
        default=date.today,
        help_text="Date from which the room will be available for listing / move-in.",
    )
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    furnished = models.BooleanField(default=False)
    bills_included = models.BooleanField(default=False)
    property_owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="rooms",
    )
    image = models.ImageField(upload_to="room_images/", null=True, blank=True)
    number_of_bedrooms = models.IntegerField(default=1)
    number_of_bathrooms = models.IntegerField(default=1)
    property_type = models.CharField(
        max_length=100,
        choices=[
            ("flat", "Flat"),
            ("house", "House"),
            ("studio", "Studio"),
        ],
    )
    parking_available = models.BooleanField(default=False)
    avg_rating = models.FloatField(default=0)
    number_rating = models.IntegerField(default=0)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    # listing is paid/active until this date
    paid_until = models.DateField(null=True, blank=True)

    STATUS_CHOICES = (
        ("draft", "Draft"),    # not fully listed yet – appears only to owner
        ("active", "Active"),  # live listing – appears in search / homepage
        ("hidden", "Hidden"),  # manually hidden or GDPR-cleanup, admin use
    )
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default="active",
    )

    # ===== Advanced-search fields (for the modal) =====
    # “Rooms in existing shares”
    is_shared_room = models.BooleanField(
        default=False,
        help_text="Room is in an existing flat/house share.",
    )

    # “Rooms suitable for ages”
    min_age = models.PositiveSmallIntegerField(null=True, blank=True)
    max_age = models.PositiveSmallIntegerField(null=True, blank=True)

    # “Length of stay”
    min_stay_months = models.PositiveSmallIntegerField(null=True, blank=True)
    max_stay_months = models.PositiveSmallIntegerField(null=True, blank=True)

    # “Rooms for – females / males / couples / don’t mind”
    ROOM_FOR_CHOICES = [
        ("any", "Don't mind"),
        ("females", "Females"),
        ("males", "Males"),
        ("couples", "Couples"),
    ]
    room_for = models.CharField(
        max_length=16,
        choices=ROOM_FOR_CHOICES,
        default="any",
    )

    # “Room sizes – single / double / don’t mind”
    ROOM_SIZE_CHOICES = [
        ("dont_mind", "Don't mind"),
        ("single", "Single"),
        ("double", "Double"),
    ]
    room_size = models.CharField(
        max_length=16,
        choices=ROOM_SIZE_CHOICES,
        default="dont_mind",
    )

    # --- Existing flatmate (List a Room – Step 3/5, section 1) ---
    existing_flatmate_age = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Approximate age of current flatmate or average age in the household.",
    )

    EXISTING_GENDER_CHOICES = [
        ("male", "Male"),
        ("female", "Female"),
        ("non_binary", "Non-binary"),
        ("prefer_not_to_say", "Prefer not to say"),
    ]
    existing_flatmate_gender = models.CharField(
        max_length=32,
        choices=EXISTING_GENDER_CHOICES,
        blank=True,
        default="",
    )

    EXISTING_OCCUPATION_CHOICES = [
        ("professional", "Professional"),
        ("student", "Student"),
        ("prefer_not_to_say", "Prefer not to say"),
    ]
    existing_flatmate_occupation = models.CharField(
        max_length=32,
        choices=EXISTING_OCCUPATION_CHOICES,
        blank=True,
        default="",
    )

    # These are free text; FE uses big dropdown lists, BE just stores the chosen text.
    existing_flatmate_nationality = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )
    existing_flatmate_language = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    YES_NO_PREF_CHOICES = [
        ("yes", "Yes"),
        ("no", "No"),
        ("no_preference", "No preference"),
    ]
    existing_flatmate_smoking = models.CharField(
        max_length=20,
        choices=YES_NO_PREF_CHOICES,
        blank=True,
        default="no_preference",
        help_text="Do existing flatmates smoke?",
    )
    existing_flatmate_pets = models.CharField(
        max_length=20,
        choices=YES_NO_PREF_CHOICES,
        blank=True,
        default="",
        help_text="Are there pets in the home?",
    )
    existing_flatmate_lgbtqia_household = models.CharField(
        max_length=20,
        choices=YES_NO_PREF_CHOICES,
        blank=True,
        default="",
        help_text="Whether the household includes LGBTQIA+ people.",
    )
    
    
    # --- Flatmate preference (List a Room – Step 3/5, section 2) ---
    preferred_flatmate_nationality = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Preferred nationality of future flatmate (free text from dropdown).",
    )
    preferred_flatmate_language = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Preferred language of future flatmate (free text from dropdown).",
    )

    preferred_flatmate_min_age = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Minimum preferred age of flatmate.",
    )
    preferred_flatmate_max_age = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Maximum preferred age of flatmate.",
    )

    PREFERRED_OCCUPATION_CHOICES = [
        ("students_only", "For students only"),
        ("not_for_students", "Not for students"),
        ("open_to_everyone", "Open to everyone"),
    ]
    preferred_flatmate_occupation = models.CharField(
        max_length=32,
        choices=PREFERRED_OCCUPATION_CHOICES,
        blank=True,
        default="",
        help_text="Student / non-student preference for future flatmate.",
    )

    # Reuse YES_NO_PREF_CHOICES for Yes / No / No preference
    preferred_flatmate_pets = models.CharField(
        max_length=20,
        choices=YES_NO_PREF_CHOICES,
        blank=True,
        default="no_preference",
        help_text="Whether future flatmate can have / be around pets.",
    )
    preferred_flatmate_gender = models.CharField(
        max_length=20,
        choices=[
            ("no_preference", "No preference"),
            ("male", "Male"),
            ("female", "Female"),
            ("others", "Others"),
        ],
        blank=True,
        default="no_preference",
        help_text="Preferred gender of future flatmate.",
    )
    preferred_flatmate_smoking = models.CharField(
        max_length=20,
        choices=YES_NO_PREF_CHOICES,
        blank=True,
        default="no_preference",
        help_text="Whether future flatmate can smoke or not.",
    )
    preferred_flatmate_partners_allowed = models.CharField(
        max_length=20,
        choices=[
            ("yes", "Yes"),
            ("no", "No"),
        ],
        blank=True,
        default="no",
        help_text="Whether partners are allowed to stay over.",
    )
    preferred_flatmate_lgbtqia = models.CharField(
        max_length=20,
        choices=YES_NO_PREF_CHOICES,
        blank=True,
        default="no_preference",
        help_text="Preference about LGBTQIA+ flatmates.",
    )
    preferred_flatmate_vegan_vegetarian = models.CharField(
        max_length=20,
        choices=YES_NO_PREF_CHOICES,
        blank=True,
        default="no_preference",
        help_text="Preference about vegan/vegetarian flatmates.",
    )
    
    
    # Daily availability window – when the landlord is available for viewings
    availability_from_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Earliest time you are available (e.g. 16:30).",
    )
    availability_to_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Latest time you are available (e.g. 20:00).",
    )

    # --- Viewing availability (List a Room step 1) ---
    VIEW_DAYS_CHOICES = [
        ("everyday", "Everyday"),
        ("weekdays", "Weekdays only"),
        ("weekends", "Weekends only"),
        ("custom", "Custom dates"),
    ]

    # How the “View Available Days” dropdown is set
    view_available_days_mode = models.CharField(
        max_length=20,
        choices=VIEW_DAYS_CHOICES,
        default="everyday",
        help_text="Everyday / weekdays only / weekends only / custom dates.",
    )

    # When mode = 'custom', front-end sends an array of dates (YYYY-MM-DD)
    # that the calendar has highlighted (range or scattered).
    view_available_custom_dates = models.JSONField(
        blank=True,
        default=list,
        help_text="List of specific viewing dates when mode is 'custom'.",
    )

    @property
    def is_live(self):
        """
        Used for public listing visibility:
        - status is 'active'
        - not soft-deleted
        - paid_until is either NULL or today/in the future
        """
        if self.status != "active" or getattr(self, "is_deleted", False):
            return False

        today = date.today()
        if self.paid_until and self.paid_until < today:
            return False
        return True

    @property
    def is_expired_listing(self):
        """
        A listing that has *passed* its paid_until date.
        Still belongs to the owner but won't show in public search.
        """
        if not self.paid_until:
            return False
        return self.paid_until < date.today()

    def clean(self):
        super().clean()

        # Existing bills + price rule
        if (
            self.bills_included
            and self.price_per_month is not None
            and float(self.price_per_month) < 100.0
        ):
            raise ValidationError(
                {"bills_included": "Bills cannot be included for such a low price."}
            )

        # NEW: age range sanity
        if (
            self.min_age is not None
            and self.max_age is not None
            and self.min_age > self.max_age
        ):
            raise ValidationError(
                {"min_age": "min_age cannot be greater than max_age."}
            )

        # NEW: stay length sanity
        if (
            self.min_stay_months is not None
            and self.max_stay_months is not None
            and self.min_stay_months > self.max_stay_months
        ):
            raise ValidationError(
                {
                    "min_stay_months": (
                        "min_stay_months cannot be greater than max_stay_months."
                    )
                }
            )
            
        # Preferred flatmate age sanity (for Step 3/5 Flatmate Preference)
        if (
            self.preferred_flatmate_min_age is not None
            and self.preferred_flatmate_max_age is not None
            and self.preferred_flatmate_min_age > self.preferred_flatmate_max_age
        ):
            raise ValidationError(
                {
                    "preferred_flatmate_min_age": (
                        "preferred_flatmate_min_age cannot be greater than "
                        "preferred_flatmate_max_age."
                    )
                }
            )

        
            

    def save(self, *args, **kwargs):
        if self.property_owner_id is None:
            UserModel = get_user_model()
            owner = UserModel.objects.order_by("id").first()
            if owner is None:
                owner = UserModel.objects.create_user(
                    username=f"system_{uuid4().hex[:8]}",
                    password="!auto!",
                    email="",
                )
            self.property_owner = owner

        if self.category_id is None:
            cat, _ = RoomCategorie.objects.get_or_create(
                name="General",
                defaults={"key": "general", "slug": "general", "active": True},
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





# -----------
# UserProfile
# -----------
class UserProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    phone = models.CharField(max_length=15, unique=True, null=True, blank=True)
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)
    stripe_customer_id = models.CharField(max_length=100, blank=True, default="")

    ROLE_CHOICES = (("landlord", "Landlord"), ("seeker", "Seeker"))
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default="seeker",
        db_index=True,
    )

    # Detailed “Role” dropdown on the profile screen
    ROLE_DETAIL_CHOICES = (
        ("live_in_landlord", "Live in Landlord"),
        ("live_out_landlord", "Live Out Landlord"),
        ("current_flatmate", "Current Flatmate"),
        ("former_flatmate", "Former Flatmate"),
        ("agent_broker", "Real Estate Agent/Broker"),
    )
    role_detail = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )

    # Manual address text when user clicks “Enter Address Manually”
    address_manual = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    # Fields for My Profile page
    GENDER_CHOICES = (
        ("male", "Male"),
        ("female", "Female"),
        ("non_binary", "Non-binary"),
        ("prefer_not_to_say", "Prefer not to say"),
    )

    occupation = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )
    gender = models.CharField(
        max_length=32,
        choices=GENDER_CHOICES,
        blank=True,
        default="",
    )
    postcode = models.CharField(
        max_length=12,
        blank=True,
        default="",
    )
    date_of_birth = models.DateField(
        null=True,
        blank=True,
    )
    about_you = models.TextField(
        max_length=100,
        blank=True,
        default="",
    )

    email_verified = models.BooleanField(default=False, db_index=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    phone_verified = models.BooleanField(default=False, db_index=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    terms_version = models.CharField(max_length=20, blank=True, default="")
    marketing_consent = models.BooleanField(default=False)
    onboarding_completed = models.BooleanField(default=False)

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


class ContactMessage(models.Model):
    """
    Stores submissions from the Contact Us form.
    """
    name = models.CharField(max_length=120)
    email = models.EmailField()
    subject = models.CharField(max_length=200)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email} | {self.subject[:40]}"


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
        choices=[
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="pending",
        db_index=True,
    )

    objects = RoomImageQuerySet.as_manager()


# -----------------
# AvailabilitySlot
# -----------------
class AvailabilitySlot(models.Model):
    room = models.ForeignKey(
        "Room",
        related_name="availability_slots",
        on_delete=models.CASCADE,
    )
    start = models.DateTimeField()
    end = models.DateTimeField()
    max_bookings = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("start",)
        constraints = [
            CheckConstraint(
                check=Q(end__gt=F("start")),
                name="slot_end_after_start",
            ),
            CheckConstraint(
                check=Q(max_bookings__gte=1),
                name="slot_max_bookings_gte_1",
            ),
            models.UniqueConstraint(
                fields=["room", "start", "end"],
                name="unique_slot_room_start_end",
            ),
        ]

    def __str__(self):
        return (
            f"{self.room} | {self.start:%Y-%m-%d %H:%M} → "
            f"{self.end:%Y-%m-%d %H:%M} (cap {self.max_bookings})"
        )


# -------
# Booking
# -------
class Booking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bookings")
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="bookings")
    slot = models.ForeignKey(
        AvailabilitySlot,
        on_delete=models.PROTECT,
        related_name="bookings",
        null=True,
        blank=True,
    )
    start = models.DateTimeField()
    end = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    
    
    STATUS_ACTIVE = "active"
    STATUS_CANCELLED = "cancelled"
    STATUS_SUSPENDED = "suspended"

    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_SUSPENDED, "Suspended"),
    )

    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Booking #{self.id} for {self.room} by {self.user}"

    def cancel(self):
        self.status = self.STATUS_CANCELLED
        self.canceled_at = timezone.now()
        self.save(update_fields=["status", "canceled_at"])

    def suspend(self):
        self.status = self.STATUS_SUSPENDED
        if not self.canceled_at:
            self.canceled_at = timezone.now()
        self.save(update_fields=["status", "canceled_at"])

    class Meta:
        indexes = [
            models.Index(fields=["room", "start", "end"]),
        ]



# ------
# Review (booking-based, double-blind)
# ------
class Review(models.Model):

    ROLE_TENANT_TO_LANDLORD = "tenant_to_landlord"
    ROLE_LANDLORD_TO_TENANT = "landlord_to_tenant"

    ROLE_CHOICES = (
        (ROLE_TENANT_TO_LANDLORD, "Tenant → Landlord"),
        (ROLE_LANDLORD_TO_TENANT, "Landlord → Tenant"),
    )

    # Booking that ended
    booking = models.ForeignKey(
    Booking,
    on_delete=models.CASCADE,
    related_name="reviews",
    null=True,
    blank=True,
    )


    # Who wrote the review
    reviewer = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.CASCADE,
    related_name="reviews_written",
    null=True,
    blank=True,
    )


    # Who the review is about
    reviewee = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.CASCADE,
    related_name="reviews_received",
    null=True,
    blank=True,
    )


    # Direction
    role = models.CharField(
    max_length=32,
    choices=ROLE_CHOICES,
    null=True,
    blank=True,
    )


    # Checkbox selections from frontend
    review_flags = models.JSONField(default=list, blank=True)

    # Auto-computed 1–5 rating
    overall_rating = models.PositiveIntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )

    notes = models.TextField(blank=True, null=True)

    submitted_at = models.DateTimeField(auto_now_add=True)
    reveal_at = models.DateTimeField(null=True, blank=True)


    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["booking", "role"],
                name="uq_review_once_per_booking_role",
            ),
        ]

    def __str__(self):
        return f"{self.role} | booking {self.booking_id} | {self.reviewer} → {self.reviewee}"
    
    
    def save(self, *args, **kwargs):
        # Only auto-set reveal_at if it hasn't been set already.
        end_dt = None
        if self.booking:
            end_dt = getattr(self.booking, "end", None) or getattr(self.booking, "end_date", None)

        if self.reveal_at is None and end_dt:
            self.reveal_at = end_dt + timedelta(days=30)

        # Compute rating from checkboxes
        positives = {
            "responsive", "maintenance_good", "accurate_listing", "respectful_fair",
            "paid_on_time", "property_care_good", "good_communication", "followed_rules",
        }
        negatives = {
            "unresponsive", "maintenance_poor", "misleading_listing", "unfair_treatment",
            "late_payment", "property_care_poor", "poor_communication", "broke_rules",
        }

        flags = self.review_flags or []
        pos = sum(1 for f in flags if f in positives)
        neg = sum(1 for f in flags if f in negatives)
        score = 3 + (pos - neg)
        self.overall_rating = max(1, min(5, score))

        super().save(*args, **kwargs)




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
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="saved_rooms_links",
    )
    room = models.ForeignKey(
        "Room",
        on_delete=models.CASCADE,
        related_name="saved_by_links",
    )
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

    # Optional label for UI filters (Viewing scheduled, Good fit, etc.)
    label = models.CharField(
        max_length=32,
        blank=True,
        default="",
        db_index=True,
        help_text="Optional label for this thread (e.g. 'Viewing scheduled', 'Good fit').",
    )

    # Soft-delete flag for “Bin” folder (applies to both participants for now)
    is_deleted = models.BooleanField(default=False, db_index=True)

    def __str__(self):
        users = ", ".join(self.participants.values_list("username", flat=True)[:2])
        return f"Thread {self.id} ({users}…)"


class MessageThreadState(models.Model):
    """
    Per-user state for a message thread:
    - label (Viewing scheduled / Good fit / etc.)
    - in_bin (whether THIS user has moved the thread to Bin)
    """
    LABEL_CHOICES = [
        ("viewing_scheduled", "Viewing scheduled"),
        ("viewing_done", "Viewing done"),
        ("good_fit", "Good fit"),
        ("unsure", "Unsure"),
        ("not_a_fit", "Not a fit"),
        ("paperwork_pending", "Paperwork pending"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="thread_states",
    )
    thread = models.ForeignKey(
        "MessageThread",
        on_delete=models.CASCADE,
        related_name="states",
    )

    # If empty/blank → treated as "no status"
    label = models.CharField(
        max_length=32,
        choices=LABEL_CHOICES,
        blank=True,
        default="",
    )
    in_bin = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "thread")
        indexes = [
            models.Index(fields=["user", "thread"]),
            models.Index(fields=["user", "in_bin"]),
            models.Index(fields=["user", "label"]),
        ]

    def __str__(self):
        return (
            f"State(user={self.user_id}, thread={self.thread_id}, "
            f"label={self.label or 'no_status'}, bin={self.in_bin})"
        )


# -------
# Message
# -------
class Message(models.Model):
    thread = models.ForeignKey(
        MessageThread,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="sent_messages",
    )
    body = models.TextField()
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    updated = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ["created"]
        indexes = [
            models.Index(fields=["thread", "created"]),
            models.Index(fields=["thread", "updated"]),
        ]


class MessageRead(models.Model):
    """Records that a given user has read a specific message."""
    message = models.ForeignKey(
        "Message",
        on_delete=models.CASCADE,
        related_name="reads",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="message_reads",
    )
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "user")
        indexes = [
            models.Index(fields=["user", "message"]),
        ]

    def __str__(self):
        return (
            f"Read m#{self.message_id} by {self.user_id} "
            f"at {self.read_at:%Y-%m-%d %H:%M:%S}"
        )


# -----------
# Notification
# -----------
class Notification(models.Model):
    """
    Simple user notification generated by app events (e.g., a new message).
    """
    class Type(models.TextChoices):
        MESSAGE = "message", "Message"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    type = models.CharField(
        max_length=32,
        choices=Type.choices,
        default=Type.MESSAGE,
    )

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

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    room = models.ForeignKey(
        "Room",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )

    provider = models.CharField(
        max_length=20,
        choices=Provider.choices,
        default=Provider.STRIPE,
    )
    amount = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    currency = models.CharField(max_length=10, default="GBP")

    stripe_payment_intent_id = models.CharField(max_length=200, blank=True, default="")
    stripe_checkout_session_id = models.CharField(max_length=200, blank=True, default="")

    status = models.CharField(
        max_length=40,
        choices=Status.choices,
        default=Status.REQUIRES_PAYMENT,
    )

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

    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default="open",
    )
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
    STATUS_CHOICES = (
        ("queued", "queued"),
        ("processing", "processing"),
        ("ready", "ready"),
        ("failed", "failed"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="data_exports",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="queued",
    )
    file_path = models.CharField(
        max_length=512,
        blank=True,
        default="",
    )  # media-relative path
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


# -----
# PhoneOTP
# ------
class PhoneOTP(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="phone_otps",
    )
    phone = models.CharField(max_length=15)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["phone", "created_at"]),
        ]

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_used(self) -> bool:
        return self.used_at is not None
