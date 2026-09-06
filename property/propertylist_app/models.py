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
