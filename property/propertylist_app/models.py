from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q, F, CheckConstraint
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.text import slugify
from django.contrib.auth.hashers import check_password, make_password


User = get_user_model()


class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db)

    def alive(self):
        return self.get_queryset().alive()

    def dead(self):
        return self.get_queryset().dead()



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
                qs = qs.exclude(status=Room.Lifecycle.HIDDEN)
        except Exception:
            pass
        return qs

    def dead(self):
        return self.filter(is_deleted=True)


class SoftDeleteModel(models.Model):
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    objects = SoftDeleteManager()
    all_objects = models.Manager()

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
    description = models.TextField(blank=True, default="")
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
        # ---- Advanced Search II (Option A) - explicit UI-matching fields ----

    YES_NO_PREF_CHOICES = [
        ("yes", "Yes"),
        ("no", "No"),
        ("no_preference", "No preference"),
    ]

    BATHROOM_TYPE_CHOICES = [
        ("private", "Private"),
        ("shared", "Shared"),
        ("no_preference", "No preference"),
    ]

    SUITABLE_FOR_CHOICES = [
        ("one_person", "One person"),
        ("couple", "Couple"),
        ("max_occupants", "Maximum occupants"),
        ("no_preference", "No preference"),
    ]

    HOUSEHOLD_TYPE_CHOICES = [
        ("professional", "Professional"),
        ("student", "Student"),
        ("mixed", "Mixed"),
        ("no_preference", "No preference"),
    ]

    HOUSEHOLD_ENVIRONMENT_CHOICES = [
        ("quiet", "Quiet"),
        ("sociable", "Sociable"),
        ("mixed", "Mixed"),
        ("no_preference", "No preference"),
    ]

    bathroom_type = models.CharField(
        max_length=32,
        choices=BATHROOM_TYPE_CHOICES,
        default="no_preference",
        blank=True,
    )

    shared_living_space = models.CharField(
        max_length=32,
        choices=YES_NO_PREF_CHOICES,
        default="no_preference",
        blank=True,
    )

    smoking_allowed_in_property = models.CharField(
        max_length=32,
        choices=YES_NO_PREF_CHOICES,
        default="no_preference",
        blank=True,
    )

    suitable_for = models.CharField(
        max_length=32,
        choices=SUITABLE_FOR_CHOICES,
        default="no_preference",
        blank=True,
    )

    max_occupants = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )

    household_bedrooms_min = models.PositiveSmallIntegerField(null=True, blank=True)
    household_bedrooms_max = models.PositiveSmallIntegerField(null=True, blank=True)

    household_type = models.CharField(
        max_length=32,
        choices=HOUSEHOLD_TYPE_CHOICES,
        default="no_preference",
        blank=True,
    )

    household_environment = models.CharField(
        max_length=32,
        choices=HOUSEHOLD_ENVIRONMENT_CHOICES,
        default="no_preference",
        blank=True,
    )

    pets_allowed = models.CharField(
        max_length=32,
        choices=YES_NO_PREF_CHOICES,
        default="no_preference",
        blank=True,
    )

    inclusive_household = models.CharField(
        max_length=32,
        choices=YES_NO_PREF_CHOICES,
        default="no_preference",
        blank=True,
    )

    accessible_entry = models.CharField(
        max_length=32,
        choices=YES_NO_PREF_CHOICES,
        default="no_preference",
        blank=True,
    )

    free_to_contact = models.BooleanField(default=False)

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
    paid_until = models.DateField(null=True, blank=True)

    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("active", "Active"),
        ("hidden", "Hidden"),
    )
    class Lifecycle:
        DRAFT = "draft"
        ACTIVE = "active"
        HIDDEN = "hidden"

        ALL = {DRAFT, ACTIVE, HIDDEN}

        PUBLIC = {ACTIVE}
        EDITABLE = {DRAFT, ACTIVE}
    
    
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default="active",
    )

    is_shared_room = models.BooleanField(
        default=False,
        help_text="Room is in an existing flat/house share.",
    )

    min_age = models.PositiveSmallIntegerField(null=True, blank=True)
    max_age = models.PositiveSmallIntegerField(null=True, blank=True)

    min_stay_months = models.PositiveSmallIntegerField(null=True, blank=True)
    max_stay_months = models.PositiveSmallIntegerField(null=True, blank=True)

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

    existing_flatmate_nationality = models.CharField(max_length=100, blank=True, default="")
    existing_flatmate_language = models.CharField(max_length=100, blank=True, default="")

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

    preferred_flatmate_min_age = models.PositiveSmallIntegerField(null=True, blank=True)
    preferred_flatmate_max_age = models.PositiveSmallIntegerField(null=True, blank=True)

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

    availability_from_time = models.TimeField(null=True, blank=True)
    availability_to_time = models.TimeField(null=True, blank=True)

    #  search engine indexing override per listing:
    # None = follow user's default, True = force allow, False = force noindex
    allow_search_indexing_override = models.BooleanField(null=True, blank=True, default=None)


    VIEW_DAYS_CHOICES = [
        ("everyday", "Everyday"),
        ("weekdays", "Weekdays only"),
        ("weekends", "Weekends only"),
        ("custom", "Custom dates"),
    ]
    view_available_days_mode = models.CharField(
        max_length=20,
        choices=VIEW_DAYS_CHOICES,
        default="everyday",
        help_text="Everyday / weekdays only / weekends only / custom dates.",
    )
    view_available_custom_dates = models.JSONField(
        blank=True,
        default=list,
        help_text="List of specific viewing dates when mode is 'custom'.",
    )
    
    cover_photo = models.ForeignKey(
            "RoomImage",
            null=True,
            blank=True,
            on_delete=models.SET_NULL,
            related_name="cover_for_rooms",
            help_text="User-selected cover photo for this room.",
        )
    

    @property
    def is_live(self):
        if self.status != "active" or getattr(self, "is_deleted", False):
            return False
        today = date.today()
        if self.paid_until and self.paid_until < today:
            return False
        return True

    @property
    def is_expired_listing(self):
        if not self.paid_until:
            return False
        return self.paid_until < date.today()

    def clean(self):
        super().clean()

        if (
            self.bills_included
            and self.price_per_month is not None
            and float(self.price_per_month) < 100.0
        ):
            raise ValidationError({"bills_included": "Bills cannot be included for such a low price."})

        if self.min_age is not None and self.max_age is not None and self.min_age > self.max_age:
            raise ValidationError({"min_age": "min_age cannot be greater than max_age."})

        if (
            self.min_stay_months is not None
            and self.max_stay_months is not None
            and self.min_stay_months > self.max_stay_months
        ):
            raise ValidationError(
                {"min_stay_months": "min_stay_months cannot be greater than max_stay_months."}
            )

        if (
            self.preferred_flatmate_min_age is not None
            and self.preferred_flatmate_max_age is not None
            and self.preferred_flatmate_min_age > self.preferred_flatmate_max_age
        ):
            raise ValidationError(
                {
                    "preferred_flatmate_min_age": (
                        "preferred_flatmate_min_age cannot be greater than preferred_flatmate_max_age."
                    )
                }
            )

    def save(self, *args, **kwargs):
        if self.property_owner_id is None:
            raise ValidationError({"property_owner": "property_owner is required."})

        if self.category_id is None:
            raise ValidationError({"category": "category is required."})

        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("title"),
                "property_owner",
                condition=Q(is_deleted=False),
                name="uq_room_owner_title_lower_alive",
            ),
        ]

    def __str__(self):
        return self.title





    def set_status(self, new_status: str):
        """
        Controlled lifecycle transition gate.
        """

        allowed = {
            self.Lifecycle.DRAFT: {self.Lifecycle.DRAFT, self.Lifecycle.ACTIVE, self.Lifecycle.HIDDEN},
            self.Lifecycle.ACTIVE: {self.Lifecycle.ACTIVE, self.Lifecycle.HIDDEN},
            self.Lifecycle.HIDDEN: set(),
        }

        if new_status not in self.Lifecycle.ALL:
            raise ValidationError("Invalid status value")

        if self.status not in allowed or new_status not in allowed[self.status]:
            raise ValidationError(
                f"Invalid transition: {self.status} → {new_status}"
            )

        self.status = new_status

# -----------
# UserProfile
# -----------
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    phone = models.CharField(max_length=15, unique=True, null=True, blank=True)
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)
    stripe_customer_id = models.CharField(max_length=100, blank=True, default="")
    read_receipts_enabled = models.BooleanField(default=True)

    avg_landlord_rating = models.FloatField(default=0.0)
    number_landlord_ratings = models.PositiveIntegerField(default=0)
    avg_tenant_rating = models.FloatField(default=0.0)
    number_tenant_ratings = models.PositiveIntegerField(default=0)

    ROLE_CHOICES = (
        ("landlord", "Landlord"),
        ("seeker", "Seeker"),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="seeker", db_index=True)

    ADMIN_ROLE_CHOICES = (
        ("", "No admin role"),
        ("super_admin", "Super Admin"),
        ("ops_admin", "Operations Admin"),
        ("moderator", "Moderation Admin"),
        ("finance_admin", "Finance Admin"),
        ("support_admin", "Support Admin"),
    )
    admin_role = models.CharField(max_length=30, choices=ADMIN_ROLE_CHOICES, blank=True, default="", db_index=True)

    pending_deletion_requested_at = models.DateTimeField(null=True, blank=True)
    pending_deletion_scheduled_for = models.DateTimeField(null=True, blank=True)

    ROLE_DETAIL_CHOICES = (
        ("live_in_landlord", "Live in Landlord"),
        ("live_out_landlord", "Live Out Landlord"),
        ("current_flatmate", "Current Flatmate"),
        ("former_flatmate", "Former Flatmate"),
        ("agent_broker", "Real Estate Agent/Broker"),
    )
    role_detail = models.CharField(max_length=64, blank=True, default="")

    address_manual = models.CharField(max_length=255, blank=True, default="")

    GENDER_CHOICES = (
        ("male", "Male"),
        ("female", "Female"),
        ("non_binary", "Non-binary"),
        ("prefer_not_to_say", "Prefer not to say"),
    )
    occupation = models.CharField(max_length=100, blank=True, default="")
    gender = models.CharField(max_length=32, choices=GENDER_CHOICES, blank=True, default="")
    postcode = models.CharField(max_length=12, blank=True, default="")
    date_of_birth = models.DateField(null=True, blank=True)
    about_you = models.TextField(max_length=100, blank=True, default="")

    email_verified = models.BooleanField(default=False, db_index=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    phone_verified = models.BooleanField(default=False, db_index=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    advertiser_verified = models.BooleanField(default=False, db_index=True)

    identity_verified = models.BooleanField(default=False, db_index=True)
    identity_verified_at = models.DateTimeField(null=True, blank=True)

    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    terms_version = models.CharField(max_length=20, blank=True, default="")
    marketing_consent = models.BooleanField(default=False)

    allow_search_indexing_default = models.BooleanField(default=True)

    PREFERRED_LANGUAGE_CHOICES = [
        ("en-GB", "English (UK)"),
        ("en-US", "English (US)"),
    ]
    preferred_language = models.CharField(max_length=10, choices=PREFERRED_LANGUAGE_CHOICES, default="en-GB")

    date_format = models.CharField(max_length=16, blank=True, default="dd/mm/yyyy")
    notify_email = models.BooleanField(default=True)
    notify_in_app = models.BooleanField(default=True)
    notify_confirmations = models.BooleanField(default=True)
    notify_reminders = models.BooleanField(default=True)
    notify_changes = models.BooleanField(default=True)

    def __str__(self):
        return f"Profile<{self.user_id}>"


class EmailOTP(models.Model):
    PURPOSE_LOGIN = "login"
    PURPOSE_EMAIL_VERIFY = "email_verify"
    PURPOSE_PASSWORD_RESET = "password_reset"
    PURPOSE_CHOICES = [
        (PURPOSE_LOGIN, "Login"),
        (PURPOSE_EMAIL_VERIFY, "Email verification"),
        (PURPOSE_PASSWORD_RESET, "Password reset"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_otps")
    email = models.EmailField(db_index=True)
    purpose = models.CharField(max_length=32, choices=PURPOSE_CHOICES, default=PURPOSE_LOGIN)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "purpose", "created_at"])]

    def is_expired(self):
        return timezone.now() >= self.expires_at

    def verify(self, code: str) -> bool:
        if self.used_at or self.is_expired() or self.attempts >= 5:
            return False
        self.attempts += 1
        ok = self.code == str(code)
        if ok:
            self.used_at = timezone.now()
        self.save(update_fields=["attempts", "used_at"])
        return ok


class PhoneOTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="phone_otps")
    phone = models.CharField(max_length=32, db_index=True)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)


class AvailabilitySlot(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="availability_slots")
    start = models.DateTimeField()
    end = models.DateTimeField()
    max_bookings = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["start"]
        constraints = [
            CheckConstraint(check=Q(end__gt=F("start")), name="slot_end_after_start"),
            CheckConstraint(check=Q(max_bookings__gte=1), name="slot_max_bookings_gte_1"),
            models.UniqueConstraint(fields=["room", "start", "end"], name="unique_slot_room_start_end"),
        ]

    def __str__(self):
        return f"{self.room_id}: {self.start} -> {self.end}"


class Booking(SoftDeleteModel):
    STATUS_BOOKED = "booked"
    STATUS_CANCELLED = "cancelled"
    STATUS_COMPLETED = "completed"
    STATUS_NO_SHOW = "no_show"
    STATUS_CHOICES = [
        (STATUS_BOOKED, "Booked"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_NO_SHOW, "No show"),
    ]

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="bookings")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bookings")
    slot = models.ForeignKey(AvailabilitySlot, on_delete=models.PROTECT, related_name="bookings", null=True, blank=True)
    start = models.DateTimeField()
    end = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_BOOKED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    canceled_at = models.DateTimeField(null=True, blank=True)


class SavedRoom(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="saved_rooms_links")
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="saved_by_links")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "room"], name="uq_saved_room_user_room")]


class MessageThread(SoftDeleteModel):
    participants = models.ManyToManyField(User, related_name="message_threads")
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, related_name="message_threads", null=True, blank=True)
    landlord = models.ForeignKey(User, on_delete=models.SET_NULL, related_name="landlord_message_threads", null=True, blank=True)
    seeker = models.ForeignKey(User, on_delete=models.SET_NULL, related_name="seeker_message_threads", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def set_role_participants(self, *, landlord=None, seeker=None):
        changed = []
        if landlord is not None and self.landlord_id != landlord.id:
            self.landlord = landlord
            changed.append("landlord")
        if seeker is not None and self.seeker_id != seeker.id:
            self.seeker = seeker
            changed.append("seeker")
        if changed:
            changed.append("updated_at")
            self.save(update_fields=changed)


class MessageThreadState(SoftDeleteModel):
    LABEL_VIEWING_SCHEDULED = "viewing_scheduled"
    LABEL_VIEWING_DONE = "viewing_done"
    LABEL_GOOD_FIT = "good_fit"
    LABEL_UNSURE = "unsure"
    LABEL_NOT_A_FIT = "not_a_fit"
    LABEL_PAPERWORK_PENDING = "paperwork_pending"
    LABEL_CHOICES = [
        (LABEL_VIEWING_SCHEDULED, "Viewing scheduled"),
        (LABEL_VIEWING_DONE, "Viewing done"),
        (LABEL_GOOD_FIT, "Good fit"),
        (LABEL_UNSURE, "Unsure"),
        (LABEL_NOT_A_FIT, "Not a fit"),
        (LABEL_PAPERWORK_PENDING, "Paperwork pending"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="message_thread_states")
    thread = models.ForeignKey(MessageThread, on_delete=models.CASCADE, related_name="states")
    label = models.CharField(max_length=32, choices=LABEL_CHOICES, blank=True, default="")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "thread"], name="uq_message_thread_state_user_thread")]
        indexes = [models.Index(fields=["user", "deleted_at"])]


class Message(models.Model):
    TYPE_USER = "user"
    TYPE_SYSTEM = "system"
    TYPE_CHOICES = [(TYPE_USER, "User"), (TYPE_SYSTEM, "System")]

    thread = models.ForeignKey(MessageThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="messages_sent")
    body = models.TextField()
    message_type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_USER)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["thread", "updated_at"])]


class MessageRead(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="reads")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="message_reads")
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["message", "user"], name="uq_message_read_message_user")]


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    template_key = models.CharField(max_length=120, blank=True, default="")
    title = models.CharField(max_length=255, blank=True, default="")
    message = models.TextField(blank=True, default="")
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)


class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=120)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class IdempotencyKey(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    key = models.CharField(max_length=255)
    action = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "key", "action"], name="uq_idem_user_key_action")]


class WebhookReceipt(models.Model):
    event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=120, blank=True, default="")
    payload = models.JSONField(default=dict)
    headers = models.JSONField(default=dict)
    processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Payment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="payments")
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    currency = models.CharField(max_length=8, default="gbp")
    status = models.CharField(max_length=32, default="pending")
    stripe_checkout_session_id = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Review(models.Model):
    ROLE_TENANT_TO_LANDLORD = "tenant_to_landlord"
    ROLE_LANDLORD_TO_TENANT = "landlord_to_tenant"
    ROLE_CHOICES = [
        (ROLE_TENANT_TO_LANDLORD, "Tenant to landlord"),
        (ROLE_LANDLORD_TO_TENANT, "Landlord to tenant"),
    ]

    tenancy = models.ForeignKey("Tenancy", on_delete=models.CASCADE, related_name="reviews")
    reviewer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reviews_written")
    reviewee = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reviews_received")
    role = models.CharField(max_length=32, choices=ROLE_CHOICES)
    overall_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    active = models.BooleanField(default=False)
    reveal_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenancy", "role"], name="uq_review_once_per_tenancy_role")]


class Tenancy(SoftDeleteModel):
    STATUS_PROPOSED = "proposed"
    STATUS_CONFIRMED = "confirmed"
    STATUS_ACTIVE = "active"
    STATUS_ENDED = "ended"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PROPOSED, "Proposed"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_ENDED, "Ended"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="tenancies")
    landlord = models.ForeignKey(User, on_delete=models.CASCADE, related_name="landlord_tenancies")
    tenant = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tenant_tenancies")
    proposed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="tenancies_proposed")
    move_in_date = models.DateField()
    duration_months = models.PositiveSmallIntegerField()
    proposed_duration_months = models.PositiveSmallIntegerField(null=True, blank=True)
    landlord_confirmed_at = models.DateTimeField(null=True, blank=True)
    tenant_confirmed_at = models.DateTimeField(null=True, blank=True)
    tenant_has_edited = models.BooleanField(default=False)
    review_open_at = models.DateTimeField(null=True, blank=True)
    review_deadline_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PROPOSED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class TenancyExtension(models.Model):
    tenancy = models.ForeignKey(Tenancy, on_delete=models.CASCADE, related_name="extensions")
    proposed_start_date = models.DateField(null=True, blank=True)
    proposed_duration_months = models.PositiveSmallIntegerField()
    proposed_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tenancy_extensions_proposed")
    landlord_confirmed_at = models.DateTimeField(null=True, blank=True)
    tenant_confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ContactMessage(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    subject = models.CharField(max_length=255)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class LandlordVerificationRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="landlord_verification_requests")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
