from django.contrib.auth import get_user_model, password_validation
User = get_user_model()
from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType
import re
from rest_framework import serializers




from propertylist_app.models import (
    Room, RoomCategorie, Review, UserProfile, RoomImage,
    SavedRoom, MessageThread, Message, Booking,
    AvailabilitySlot, Payment, Report, Notification, EmailOTP,
    MessageThreadState, ContactMessage,PhoneOTP,

)
from propertylist_app.validators import (
    validate_person_name, validate_age_18_plus, validate_avatar_image,
    normalize_uk_postcode, validate_listing_title, sanitize_html_description,
    validate_price, validate_available_from, validate_choice,
    validate_listing_photos, sanitize_search_text, validate_numeric_range,
    validate_radius_miles, validate_pagination, validate_ordering,
    normalise_price, normalise_phone, normalise_name,
    assert_not_duplicate_listing, assert_no_duplicate_files,
    enforce_user_caps,

)

from django.utils import timezone
from django.core import mail
from django.utils.crypto import get_random_string
import re
from datetime import date






# --------------------
# Review Serializer
# --------------------


from rest_framework import serializers
from propertylist_app.models import Review


class ReviewSerializer(serializers.ModelSerializer):
    """
    General review serializer used by ReviewDetail / legacy endpoints.
    Keep it present because views.py imports it.
    """
    class Meta:
        model = Review
        fields = (
            "id",
            "booking",
            "reviewer",
            "reviewee",
            "role",
            "overall_rating",
            "review_flags",
            "notes",
            "submitted_at",
            "reveal_at",
            "active",
        )
        read_only_fields = (
            "id",
            "reviewer",
            "reviewee",
            "overall_rating",
            "submitted_at",
            "reveal_at",
        )


class UserReviewListSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.CharField(source="reviewer.username", read_only=True)
    reviewer_avatar = serializers.SerializerMethodField()
    reveal_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Review
        fields = (
            "id",
            "role",
            "overall_rating",
            "review_flags",
            "notes",
            "submitted_at",
            "reveal_at",
            "reviewer_name",
            "reviewer_avatar",
            "booking",
        )

    def get_reviewer_avatar(self, obj):
        """
        reviewer.profile is your OneToOne related_name.
        Return the avatar URL if present, else None.
        """
        profile = getattr(getattr(obj, "reviewer", None), "profile", None)
        avatar = getattr(profile, "avatar", None)
        if not avatar:
            return None
        try:
            return avatar.url
        except Exception:
            return None

class BookingReviewCreateSerializer(serializers.ModelSerializer):
    booking_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = Review
        fields = (
            "booking_id",
            "review_flags",
            "notes",
        )

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user

        booking_id = attrs.get("booking_id")

        try:
            booking = Booking.objects.select_related("room").get(id=booking_id)
        except Booking.DoesNotExist:
            raise serializers.ValidationError("Booking does not exist.")

        # booking must have ended
        if not booking.end or booking.end > timezone.now():
            raise serializers.ValidationError(
                "You can only review after the booking has ended."
            )

        # must be within 30 days
        review_deadline = booking.end + timezone.timedelta(days=30)
        if timezone.now() > review_deadline:
            raise serializers.ValidationError(
                "The 30-day review window has expired."
            )

        tenant = booking.user
        landlord = booking.room.property_owner

        if user != tenant and user != landlord:
            raise serializers.ValidationError(
                "You are not allowed to review this booking."
            )

        # determine role
        if user == tenant:
            role = Review.ROLE_TENANT_TO_LANDLORD
            reviewee = landlord
        else:
            role = Review.ROLE_LANDLORD_TO_TENANT
            reviewee = tenant

        # prevent duplicate review
        if Review.objects.filter(booking=booking, role=role).exists():
            raise serializers.ValidationError(
                "You have already submitted a review for this booking."
            )

        # must provide at least flags or notes
        flags = attrs.get("review_flags", [])
        notes = attrs.get("notes")
        
        if flags:
            unknown = [f for f in flags if f not in self.ALLOWED_FLAGS]
            if unknown:
                raise serializers.ValidationError(
                    {"review_flags": f"Unknown review flag(s): {', '.join(unknown)}"}
                )


        if not flags and not notes:
            raise serializers.ValidationError(
                "Please select at least one checkbox or write a short note."
            )

        # attach server-controlled values
        attrs["booking"] = booking
        attrs["reviewer"] = user
        attrs["reviewee"] = reviewee
        attrs["role"] = role

        return attrs

    def create(self, validated_data):
        # booking_id is not a model field
        validated_data.pop("booking_id")

        return Review.objects.create(**validated_data)



    ALLOWED_FLAGS = {
        # Tenant -> Landlord
        "responsive",
        "maintenance_good",
        "accurate_listing",
        "respectful_fair",
        "unresponsive",
        "maintenance_poor",
        "misleading_listing",
        "unfair_treatment",

        # Landlord -> Tenant
        "paid_on_time",
        "property_care_good",
        "good_communication",
        "followed_rules",
        "late_payment",
        "property_care_poor",
        "poor_communication",
        "broke_rules",
    }
    



class UserReviewSummarySerializer(serializers.Serializer):
    landlord_count = serializers.IntegerField()
    landlord_average = serializers.FloatField(allow_null=True)

    tenant_count = serializers.IntegerField()
    tenant_average = serializers.FloatField(allow_null=True)

    total_reviews_count = serializers.IntegerField()
    overall_rating_average = serializers.FloatField(allow_null=True)


    
    

# --------------------
# Room Serializer
# --------------------
class RoomSerializer(serializers.ModelSerializer):
    category = serializers.CharField(source="category.name", read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        source="category",
        queryset=RoomCategorie.objects.all(),
        write_only=True,
    )
    is_saved = serializers.SerializerMethodField(read_only=True)
    distance_miles = serializers.SerializerMethodField(read_only=True)

    # extra fields for Find a Room cards
    owner_name = serializers.SerializerMethodField(read_only=True)
    owner_avatar = serializers.SerializerMethodField(read_only=True)
    main_photo = serializers.SerializerMethodField(read_only=True)
    photo_count = serializers.SerializerMethodField(read_only=True)
    listing_state = serializers.SerializerMethodField(read_only=True)
    
        # Amenity keys matching the Step 2/5 chips
    AMENITY_CHOICES = {
        # Home
        "in_unit_laundry",
        "broadband_inclusive",
        "en_suite",
        "bills_inclusive",
        "tv",
        "air_conditioning",
        "furnished",
        "unfurnished",
        "balcony",
        "pets_allowed",
        "large_closet",
        "private_bath",

        # Property
        "exercise_equipment",
        "elevator",
        "doorman",
        "heating",
        "paid_parking",
        "outdoor_space",
        "swimming_pool",
        "free_parking",
        "bbq_grill",
        "fire_pit",
        "pool_table",

        # Safety
        "smoke_alarm",
        "first_aid_kit",
        "security_system",
        "carbon_monoxide",
        "fire_extinguisher",
        "disabled_accessible",
        "must_climb_stairs",
    }


    class Meta:
        model = Room
        fields = "__all__"

    def validate_title(self, value):
        return validate_listing_title(value)

    def validate_description(self, value):
        """
        Clean the HTML and enforce a minimum description length.
        User must write at least 25 words.
        """
        clean = sanitize_html_description(value or "")

        words = [w for w in clean.split() if w.strip()]
        if len(words) < 25:
            raise serializers.ValidationError(
                "Description must be at least 25 words."
            )

        return clean


    def validate_price_per_month(self, value):
        value = normalise_price(value)
        return validate_price(value, min_val=50.0, max_val=20000.0)
    
    
    def validate_amenities(self, value):
        """
        Front-end sends a list of amenity *keys* (strings).
        Example:
            ["in_unit_laundry", "broadband_inclusive", "smoke_alarm"]
        We ensure:
        - it's a list
        - every item is in AMENITY_CHOICES
        - everything is normalised to a simple list of strings
        """
        if value in (None, "", []):
            return []

        if not isinstance(value, (list, tuple)):
            raise serializers.ValidationError("Amenities must be a list of strings.")

        cleaned = []
        invalid = []

        for item in value:
            key = str(item).strip()
            if not key:
                continue
            if key not in self.AMENITY_CHOICES:
                invalid.append(key)
            else:
                cleaned.append(key)

        if invalid:
            raise serializers.ValidationError(
                f"Unknown amenity keys: {', '.join(sorted(set(invalid)))}"
            )

        return cleaned

    
    
    def validate_security_deposit(self, value):
        # normalise_price handles strings like "£200" or "200.00"
        value = normalise_price(value)
        # allow zero, but cap it to something sensible
        return validate_price(value, min_val=0.0, max_val=50000.0)


    def validate_location(self, value):
        parts = str(value or "").strip().split()
        if not parts:
            raise serializers.ValidationError("Location is required.")
        normalize_uk_postcode(parts[-1])
        return value

    def validate_property_type(self, value):
        allowed = {c[0] for c in Room._meta.get_field("property_type").choices}
        return validate_choice(value, allowed, label="property_type")

    def validate_image(self, value):
        validate_listing_photos([value])
        assert_no_duplicate_files([value])
        return value
    
    

    def validate(self, attrs):
        price = attrs.get("price_per_month")
        bills_included = attrs.get("bills_included")
        available_from = attrs.get("available_from")

        # price sanity (respect Decimal); allow partial updates
        if price is not None:
            validate_price(price, min_val=50.0, max_val=20000.0)

        # bills_included guard (only when price is provided)
        if bills_included and price is not None and float(price) < 100.0:
            raise serializers.ValidationError(
                {"bills_included": "Bills cannot be included for such a low price."}
            )

        # non-negative integers
        for field in ("number_of_bedrooms", "number_of_bathrooms"):
            val = attrs.get(field)
            if val is not None and int(val) < 0:
                raise serializers.ValidationError(
                    {field: "Must be zero or a positive integer."}
                )

        # available_from must not be in the past (when provided)
        if available_from is not None:
            validate_available_from(available_from)

        # ----- Minimum / maximum rental period (months, 1–12) -----
        # Support PATCH: if a field is not in attrs, fall back to instance
        min_stay = attrs.get(
            "min_stay_months",
            getattr(self.instance, "min_stay_months", None),
        )
        max_stay = attrs.get(
            "max_stay_months",
            getattr(self.instance, "max_stay_months", None),
        )

        def _check_month_field(val, field_name):
            if val is None:
                return
            try:
                val_int = int(val)
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    {field_name: "Must be an integer number of months."}
                )
            if val_int < 1 or val_int > 12:
                raise serializers.ValidationError(
                    {field_name: "Must be between 1 and 12 months."}
                )
            # normalise back into attrs so DB always sees clean ints
            attrs[field_name] = val_int

        _check_month_field(min_stay, "min_stay_months")
        _check_month_field(max_stay, "max_stay_months")

        min_final = attrs.get("min_stay_months", min_stay)
        max_final = attrs.get("max_stay_months", max_stay)
        if min_final is not None and max_final is not None and min_final > max_final:
            raise serializers.ValidationError(
                {"min_stay_months": "Minimum rental period cannot be greater than maximum rental period."}
            )

        # --- Daily availability time window (optional HH:MM) ---
        start_time = attrs.get("availability_from_time")
        end_time = attrs.get("availability_to_time")

        # For PATCH, fall back to existing instance values
        if self.instance is not None:
            if start_time is None:
                start_time = getattr(self.instance, "availability_from_time", None)
            if end_time is None:
                end_time = getattr(self.instance, "availability_to_time", None)

        # Case 1: one side missing
        if start_time and not end_time:
            raise serializers.ValidationError(
                {"availability_to_time": "Please provide an end time as well."}
            )

        if end_time and not start_time:
            raise serializers.ValidationError(
                {"availability_from_time": "Please provide a start time as well."}
            )

        # Case 2: invalid order
        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError(
                {"availability_to_time": "End time must be after start time."}
            )

        # ----- Preferred flatmate min/max age sanity -----
        pref_min_age = attrs.get(
            "preferred_flatmate_min_age",
            getattr(self.instance, "preferred_flatmate_min_age", None),
        )
        pref_max_age = attrs.get(
            "preferred_flatmate_max_age",
            getattr(self.instance, "preferred_flatmate_max_age", None),
        )

        if pref_min_age is not None and pref_max_age is not None:
            try:
                pref_min_int = int(pref_min_age)
                pref_max_int = int(pref_max_age)
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    {"preferred_flatmate_min_age": "Min and max age must be integers."}
                )
            if pref_min_int > pref_max_int:
                raise serializers.ValidationError(
                    {"preferred_flatmate_min_age": "Minimum preferred age cannot be greater than maximum preferred age."}
                )

        # ----- Per-owner duplicate check -----
        request = self.context.get("request")
        if request and getattr(request.user, "is_authenticated", False):
            new_title = attrs.get("title") or getattr(self.instance, "title", None)
            if new_title:
                assert_not_duplicate_listing(
                    request.user,
                    title=new_title,
                    queryset=Room.objects,
                    exclude_pk=getattr(self.instance, "pk", None),
                )

        # --- Availability: mode vs custom dates consistency ---
        mode = attrs.get(
            "view_available_days_mode",
            getattr(self.instance, "view_available_days_mode", "everyday"),
        )
        custom_dates = attrs.get(
            "view_available_custom_dates",
            getattr(self.instance, "view_available_custom_dates", []),
        )

        if mode == "custom":
            if not custom_dates:
                raise serializers.ValidationError(
                    {"view_available_custom_dates": "Provide at least one date when using custom mode."}
                )
        else:
            attrs["view_available_custom_dates"] = []

        return attrs



    def get_is_saved(self, obj):
        request = self.context.get("request")
        user = request.user if request and hasattr(request, "user") else None
        if not user or not user.is_authenticated:
            return False
        return SavedRoom.objects.filter(user=user, room=obj.id).exists()

    def get_distance_miles(self, obj):
        val = getattr(obj, "distance_miles", None)
        return round(val, 2) if isinstance(val, (int, float)) else val
    
    def get_listing_state(self, obj):
            """
            Returns one of: 'draft', 'active', 'expired', 'hidden'.
            Used by the 'My Listings' page to group into tabs:
            - Draft    (listing_state == 'draft')
            - Live     (listing_state == 'active')
            - Expired  (listing_state == 'expired')
            """
            # If the queryset annotated a listing_state, reuse it.
            state = getattr(obj, "listing_state", None)
            if state:
                return state

            from datetime import date
            today = date.today()

            # 1) Explicit hidden + past paid_until = expired
            if obj.status == "hidden" and obj.paid_until and obj.paid_until < today:
                return "expired"

            # 2) Hidden but not clearly expired
            if obj.status == "hidden":
                return "hidden"

            # 3) No paid_until at all = draft (never paid / not live yet)
            if obj.paid_until is None:
                return "draft"

            # 4) Paid until date in the past = expired
            if obj.paid_until < today:
                return "expired"

            # 5) Otherwise treat as active
            return "active"



    def get_owner_name(self, obj):
        user = getattr(obj, "property_owner", None)
        if not user:
            return ""
        full_name = (user.get_full_name() or "").strip()
        return full_name or user.username

    def get_owner_avatar(self, obj):
        user = getattr(obj, "property_owner", None)
        if not user:
            return None

        profile = getattr(user, "profile", None)
        if not profile or not profile.avatar:
            return None

        request = self.context.get("request")
        url = profile.avatar.url
        if request is not None:
            return request.build_absolute_uri(url)
        return url

    def get_main_photo(self, obj):
        # prefer first approved RoomImage; fall back to legacy Room.image
        first_image = (
            obj.roomimage_set.filter(status="approved")
            .order_by("id")
            .first()
        )
        if first_image and first_image.image:
            url = first_image.image.url
        elif obj.image:
            url = obj.image.url
        else:
            return None

        request = self.context.get("request")
        if request is not None:
            return request.build_absolute_uri(url)
        return url

    def get_photo_count(self, obj):
        count = obj.roomimage_set.filter(status="approved").count()
        if count > 0:
            return count
        return 1 if obj.image else 0
    
        # --- New helpers for 'View Available Days' ---


    def validate_view_available_days_mode(self, value):
        # DRF already checks choices; this is just a safety normaliser.
        return (value or "everyday").strip()

    def validate_view_available_custom_dates(self, value):
        """
        Front-end sends an array of dates (strings) when mode='custom'.
        We accept:
          - ["2025-12-01", "2025-12-03"]
          - [date(2025, 12, 1), ...]
        and normalise everything to list of YYYY-MM-DD strings.
        """
        if value in (None, ""):
            return []

        if not isinstance(value, (list, tuple)):
            raise serializers.ValidationError("Must be a list of dates.")

        normalised = []
        for item in value:
            if isinstance(item, date):
                normalised.append(item.isoformat())
                continue
            if isinstance(item, str):
                try:
                    d = date.fromisoformat(item)
                except ValueError:
                    raise serializers.ValidationError(
                        "Dates must be in 'YYYY-MM-DD' format."
                    )
                normalised.append(d.isoformat())
                continue
            raise serializers.ValidationError(
                "Each item must be a date or 'YYYY-MM-DD' string."
            )

        return normalised


# --------------------
# Room Preview Serializer (Step 5/5)
# --------------------
class RoomPreviewSerializer(serializers.Serializer):
    """
    Used by Step 5/5 (Preview & Edit) screen.

    Returns:
      - full RoomSerializer payload (all fields)
      - photos[] list with absolute URLs for approved images
        and a fallback to legacy Room.image if no RoomImage exists.
    """

    room = serializers.SerializerMethodField()
    photos = serializers.SerializerMethodField()

    def get_room(self, obj):
        """
        Reuse the existing RoomSerializer so Step 5 gets
        the same fields as other endpoints.
        """
        return RoomSerializer(obj, context=self.context).data

    def get_photos(self, obj):
        """
        Returns a list like:
        [
          {"id": 1, "url": "https://.../image1.jpg", "status": "approved"},
          {"id": 2, "url": "https://.../image2.jpg", "status": "approved"},
          ...
        ]

        If there are no RoomImage rows yet, but the legacy Room.image
        field is set, we return one 'legacy' photo entry.
        """
        request = self.context.get("request")
        photos = []

        # Prefer RoomImage objects with status='approved'
        qs = obj.roomimage_set.filter(status="approved").order_by("id")

        for img in qs:
            if not img.image:
                continue
            url = img.image.url
            if request is not None:
                url = request.build_absolute_uri(url)
            photos.append(
                {
                    "id": img.id,
                    "url": url,
                    "status": img.status,
                }
            )

        # Fallback to legacy Room.image if no approved RoomImage exists
        if not photos and obj.image:
            url = obj.image.url
            if request is not None:
                url = request.build_absolute_uri(url)
            photos.append(
                {
                    "id": None,
                    "url": url,
                    "status": "legacy",
                }
            )

        return photos




# --------------------
# Room Category Serializer
# --------------------
class RoomCategorieSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(read_only=True)

    class Meta:
        model = RoomCategorie
        fields = "__all__"


# --------------------
# Search Filters
# --------------------
class SearchFiltersSerializer(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True)
    min_price = serializers.DecimalField(required=False, max_digits=10, decimal_places=2)
    max_price = serializers.DecimalField(required=False, max_digits=10, decimal_places=2)
    postcode = serializers.CharField(required=False)
    radius_miles = serializers.FloatField(required=False)
    limit = serializers.IntegerField(required=False)
    page = serializers.IntegerField(required=False)
    offset = serializers.IntegerField(required=False)
    ordering = serializers.CharField(required=False)

    # property type filters (basic & advanced)
    property_types = serializers.ListField(
        child=serializers.ChoiceField(choices=["flat", "house", "studio"]),
        required=False,
        allow_empty=True,
    )
    ALLOWED_ORDER_FIELDS = {"price_per_month", "available_from", "created_at"}

    # ========== Advanced search filters ==========
    # “Rooms in existing shares”
    include_shared = serializers.BooleanField(required=False)

    # “Rooms suitable for ages”
    min_age = serializers.IntegerField(required=False)
    max_age = serializers.IntegerField(required=False)

    # “Length of stay”
    min_stay_months = serializers.IntegerField(required=False)
    max_stay_months = serializers.IntegerField(required=False)

    # “Rooms for”
    room_for = serializers.ChoiceField(
        choices=["any", "females", "males", "couples"],
        required=False,
    )

    # “Room sizes”
    room_size = serializers.ChoiceField(
        choices=["dont_mind", "single", "double"],
        required=False,
    )

    ALLOWED_ORDER_FIELDS = {"price_per_month", "available_from", "created_at", "updated_at"}

    def validate(self, attrs):
        # existing price / pagination rules
        validate_numeric_range(attrs.get("min_price"), attrs.get("max_price"))
        validate_pagination(attrs.get("limit"), attrs.get("page"), attrs.get("offset"))

        # radius must have postcode
        if attrs.get("radius_miles") and not attrs.get("postcode"):
            raise serializers.ValidationError(
                {"postcode": "Postcode is required when using radius search."}
            )

        # NEW: ages range sanity (simple check)
        if attrs.get("min_age") is not None or attrs.get("max_age") is not None:
            validate_numeric_range(attrs.get("min_age"), attrs.get("max_age"))

        # NEW: stay length range sanity
        if attrs.get("min_stay_months") is not None or attrs.get("max_stay_months") is not None:
            validate_numeric_range(attrs.get("min_stay_months"), attrs.get("max_stay_months"))

        return attrs


class FindAddressSerializer(serializers.Serializer):
    postcode = serializers.CharField()

    def validate_postcode(self, value):
        # Re-use your existing UK postcode normaliser
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Postcode is required.")
        return normalize_uk_postcode(value)


# --------------------
# Home / City summaries
# --------------------
class CitySummarySerializer(serializers.Serializer):
    """
    Lightweight object for 'London / 132 rooms' style data.
    """
    name = serializers.CharField()
    room_count = serializers.IntegerField()


class HomeSummarySerializer(serializers.Serializer):
    """
    Top-level payload for the home page.
    """
    featured_rooms = RoomSerializer(many=True)
    latest_rooms = RoomSerializer(many=True)
    popular_cities = CitySummarySerializer(many=True)
    stats = serializers.DictField()
    app_links = serializers.DictField()


# --------------------
# User & Auth
# --------------------
class RegistrationSerializer(serializers.ModelSerializer):
    password2 = serializers.CharField(write_only=True, required=False, allow_blank=True)
    # NEW fields to match Figma
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=[("landlord", "Landlord"), ("seeker", "Seeker")])
    terms_accepted = serializers.BooleanField()
    terms_version = serializers.CharField()
    marketing_consent = serializers.BooleanField(required=False, default=False)

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "password",
            "password2",
            "first_name",
            "last_name",
            "role",
            "terms_accepted",
            "terms_version",
            "marketing_consent",
        ]
        extra_kwargs = {"password": {"write_only": True}}

    def validate(self, attrs):
        # password match
        pw = attrs.get("password") or ""
        pw2 = attrs.get("password2", "")

        if pw2 and pw != pw2:
            raise serializers.ValidationError({"password2": "Passwords must match."})

        # --- Custom password policy (tests expect these rules) ---
        errors = {}

        # length
        if len(pw) < 8:
            errors.setdefault("password", []).append("Password must be at least 8 characters long.")

        # at least one lowercase
        if not re.search(r"[a-z]", pw):
            errors.setdefault("password", []).append("Password must contain at least one lowercase letter.")

        # at least one uppercase
        if not re.search(r"[A-Z]", pw):
            errors.setdefault("password", []).append("Password must contain at least one uppercase letter.")

        # at least one digit
        if not re.search(r"\d", pw):
            errors.setdefault("password", []).append("Password must contain at least one digit.")

        # at least one special character (non-alphanumeric)
        if not re.search(r"[^\w\s]", pw):
            errors.setdefault("password", []).append("Password must contain at least one special character.")

        if errors:
            # The tests only care about status=400, not specific messages
            raise serializers.ValidationError(errors)

        # Keep Django's built-in validators as an extra safety net
        password_validation.validate_password(pw)

        # terms
        if attrs.get("terms_accepted") is not True:
            raise serializers.ValidationError(
                {"terms_accepted": "You must accept Terms & Privacy."}
            )
        if not (attrs.get("terms_version") or "").strip():
            raise serializers.ValidationError(
                {"terms_version": "Terms version is required."}
            )

        return attrs

    def create(self, validated):
        validated.pop("password2", None)
        role = validated.pop("role")
        terms_accepted = validated.pop("terms_accepted")
        terms_version = validated.pop("terms_version")
        marketing = validated.pop("marketing_consent", False)

        password = validated.pop("password")
        user = User.objects.create_user(**validated, password=password)

        # ensure profile and set flags
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = role
        profile.marketing_consent = bool(marketing)
        profile.terms_accepted_at = timezone.now()
        profile.terms_version = terms_version
        profile.email_verified = False
        profile.save()

        # generate 6-digit OTP and email it
        code = get_random_string(6, allowed_chars="0123456789")
        EmailOTP.objects.filter(user=user, used_at__isnull=True).update(
            used_at=timezone.now()
        )
        EmailOTP.create_for(user, code, ttl_minutes=10)

        # simple email (console backend ok for now)
        mail.send_mail(
            subject="Verify your email (RentOut)",
            message=f"Your verification code is: {code}",
            from_email=None,
            recipient_list=[user.email],
            fail_silently=True,
        )
        return user

    def to_representation(self, instance):
        # minimal payload; FE knows to show OTP step next
        masked = (
            instance.email[:2]
            + "•••@"
            + instance.email.split("@")[-1]
            if instance.email
            else ""
        )
        return {
            "id": instance.pk,
            "username": instance.username,
            "email": instance.email,
            "email_masked": masked,
            "need_otp": True,
        }


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()  # username OR email
    password = serializers.CharField(write_only=True)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name"]





_UK_POSTCODE_RE = re.compile(
    r"^(GIR 0AA|"
    r"((([A-Z]{1,2}[0-9]{1,2})|"
    r"([A-Z]{1,2}[0-9][A-Z])|"
    r"([A-Z]{1}[0-9]{1,2})|"
    r"([A-Z]{1}[0-9][A-Z]))\s?[0-9][A-Z]{2}))$"
)


def _normalise_postcode(value: str) -> str:
    if value is None:
        return ""
    v = str(value).strip().upper()
    v = re.sub(r"\s+", "", v)  # remove all spaces
    if len(v) <= 3:
        return v
    return f"{v[:-3]} {v[-3:]}"  # insert single space before last 3


def _age_in_years(dob: date) -> int:
    today = timezone.localdate()
    years = today.year - dob.year
    if (today.month, today.day) < (dob.month, dob.day):
        years -= 1
    return years







class UserProfileSerializer(serializers.ModelSerializer):
    # tests expect "user" in response
    user = serializers.IntegerField(source="user_id", read_only=True)

    # tests send "Female" and expect "Female" back
    gender = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    # tests send lowercase postcode and expect normalised
    postcode = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    # tests expect these keys to exist, even if you only store address_manual for now
    address_line_1 = serializers.SerializerMethodField()
    address_line_2 = serializers.SerializerMethodField()
    city = serializers.SerializerMethodField()
    county = serializers.SerializerMethodField()
    country = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = (
            "id",
            "user",
            "role",
            "role_detail",
            "onboarding_completed",
            "gender",
            "occupation",
            "postcode",
            "date_of_birth",
            "about_you",
            "phone",
            "avatar",
            "address_line_1",
            "address_line_2",
            "city",
            "county",
            "country",
            "address_manual",
            "email_verified",
            "phone_verified",
            "phone_verified_at",
            "marketing_consent",
            "notify_rentout_updates",
            "notify_reminders",
            "notify_messages",
            "notify_confirmations",

        )
        read_only_fields = (
            "id",
            "user",
            "avatar",
            "email_verified",
        )

    # ---------- address placeholders (until you implement structured address fields) ----------
    def get_address_line_1(self, obj):
        return ""

    def get_address_line_2(self, obj):
        return ""

    def get_city(self, obj):
        return ""

    def get_county(self, obj):
        return ""

    def get_country(self, obj):
        return ""

    # ---------- normalisers / validators ----------
    def validate_gender(self, value):
        if value is None:
            return ""
        v = str(value).strip()
        if v == "":
            return ""

        # accept UI values like "Female", "Male", etc.
        lower = v.lower()
        mapping = {
        "female": "female",
        "male": "male",
        "non-binary": "non_binary",
        "non binary": "non_binary",
        "non_binary": "non_binary",
        "prefer not to say": "prefer_not_to_say",
        "prefer_not_to_say": "prefer_not_to_say",
        "other": "non_binary",  # optional fallback if older clients send "other"
    }

        if lower in mapping:
            return mapping[lower]

        # if your model doesn't include prefer_not_to_say, this will still fail fast and clearly
        raise serializers.ValidationError("Invalid gender value.")

    def validate_postcode(self, value):
        value = (value or "").strip()
        if value == "":
            return ""

        try:
            # validates and returns a normalised UK postcode
            return normalize_uk_postcode(value)
        except Exception:
            raise serializers.ValidationError("Invalid UK postcode.")

    def validate_date_of_birth(self, value):
        if not value:
            return value

        today = timezone.localdate()
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < 18:
            raise serializers.ValidationError("You must be at least 18 years old.")
        return value

    def to_representation(self, instance):
        data = super().to_representation(instance)

        # return display label for gender ("Female") to satisfy your tests/UI
        if getattr(instance, "gender", ""):
            try:
                data["gender"] = instance.get_gender_display()
            except Exception:
                # fallback if gender isn't a choices field in your DB for some reason
                data["gender"] = data.get("gender") or ""
        else:
            data["gender"] = ""

        return data
    
    
    
    
class ReviewCardSerializer(serializers.ModelSerializer):
        reviewer_name = serializers.CharField(source="reviewer.username", read_only=True)
        reviewer_avatar = serializers.SerializerMethodField()

        class Meta:
            model = Review
            fields = (
                "id",
                "overall_rating",
                "notes",
                "submitted_at",
                "reviewer_name",
                "reviewer_avatar",
            )

        def get_reviewer_avatar(self, obj):
            profile = getattr(getattr(obj, "reviewer", None), "profile", None)
            avatar = getattr(profile, "avatar", None)
            if not avatar:
                return None
            try:
                return avatar.url
            except Exception:
                return None    
    
    
class ProfilePageSerializer(serializers.Serializer):
        # header/user
        id = serializers.IntegerField()
        email = serializers.EmailField()
        username = serializers.CharField()
        date_joined = serializers.DateTimeField()

        # profile fields
        avatar = serializers.CharField(allow_blank=True, allow_null=True, required=False)
        role = serializers.CharField()
        gender = serializers.CharField(allow_blank=True, required=False)
        occupation = serializers.CharField(allow_blank=True, required=False)
        postcode = serializers.CharField(allow_blank=True, required=False)
        address_manual = serializers.CharField(allow_blank=True, required=False)
        date_of_birth = serializers.DateField(allow_null=True, required=False)
        about_you = serializers.CharField(allow_blank=True, required=False)

        # computed display fields for UI
        age = serializers.IntegerField(allow_null=True)
        location = serializers.CharField(allow_blank=True)

        # review stats
        total_reviews = serializers.IntegerField()
        overall_rating = serializers.FloatField(allow_null=True)

        landlord_reviews_count = serializers.IntegerField()
        landlord_rating_average = serializers.FloatField(allow_null=True)

        tenant_reviews_count = serializers.IntegerField()
        tenant_rating_average = serializers.FloatField(allow_null=True)

        # preview list (2 cards like your screenshot)
        reviews_preview = ReviewCardSerializer(many=True)    
            
    

class ContactMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = [
            "id",
            "name",
            "email",
            "subject",
            "message",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


# --------------------
# Room Images / Messages / Bookings / Slots / Payments / Reports
# --------------------
class RoomImageSerializer(serializers.ModelSerializer):
    # Use FileField so DRF/Pillow doesn't try to decode the image during tests
    image = serializers.FileField()

    class Meta:
        model = RoomImage
        fields = ["id", "room", "image", "status"]
        read_only_fields = ["room", "status"]

    # generate thumbnails after upload
    def create(self, validated_data):
        obj = super().create(validated_data)
        f = validated_data.get("image")
        if f:
            from django.utils.crypto import get_random_string  # local import if needed
            from propertylist_app.services.images import (
                generate_thumbnails_and_return_paths,
            )

            stem = get_random_string(12)  # unique-ish stem
            base_dir = "room_images/thumbs"
            try:
                generate_thumbnails_and_return_paths(f, base_dir, stem)
            except Exception:
                # Do not fail the main upload if thumbnail generation fails
                pass
        return obj


class MessageSerializer(serializers.ModelSerializer):
    sender = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Message
        fields = ["id", "thread", "sender", "body", "created"]
        read_only_fields = ["thread", "sender", "created"]


class MessageThreadSerializer(serializers.ModelSerializer):
    participants = serializers.SlugRelatedField(
        slug_field="username", many=True, queryset=User.objects.all()
    )
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    # NEW: per-user state fields
    label = serializers.SerializerMethodField()
    in_bin = serializers.SerializerMethodField()

    class Meta:
        model = MessageThread
        fields = [
            "id",
            "participants",
            "created_at",
            "last_message",
            "unread_count",
            "label",
            "in_bin",
        ]

    def get_last_message(self, obj):
        msg = obj.messages.order_by("-created").first()
        return MessageSerializer(msg).data if msg else None

    def get_unread_count(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return 0
        return obj.messages.exclude(sender=request.user).exclude(
            reads__user=request.user
        ).count()

    def _get_state_for_user(self, obj):
        """
        Helper to get MessageThreadState for the current user.
        If the view has pre-attached obj._state_for_user, use that;
        otherwise do a small DB lookup.
        """
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None

        # If view pre-attached a state
        st = getattr(obj, "_state_for_user", None)
        if st is not None:
            return st

        # Fallback: 1 query per thread
        return MessageThreadState.objects.filter(user=user, thread=obj).first()

    def get_label(self, obj):
        st = self._get_state_for_user(obj)
        if not st or not st.label:
            return None  # treated as "no status"
        return st.label

    def get_in_bin(self, obj):
        st = self._get_state_for_user(obj)
        return bool(st.in_bin) if st else False


class MessageThreadStateUpdateSerializer(serializers.Serializer):
    """
    Used by PATCH /api/messages/threads/<thread_id>/state/
    to update per-user label and/or in_bin.
    """
    label = serializers.ChoiceField(
        choices=[
            "viewing_scheduled",
            "viewing_done",
            "good_fit",
            "unsure",
            "not_a_fit",
            "paperwork_pending",
            "no_status",        # special value to clear label
        ],
        required=False,
    )
    in_bin = serializers.BooleanField(required=False)

    def validate(self, attrs):
        # nothing fancy yet; we just normalise label
        label = attrs.get("label")
        if label == "no_status":
            attrs["label"] = ""  # clear label in DB
        return attrs


class BookingSerializer(serializers.ModelSerializer):
    room_title = serializers.CharField(source="room.title", read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "room",
            "slot",
            "room_title",
            "start",
            "end",
            "status",
            "created_at",
            "canceled_at",
        ]
        read_only_fields = ["created_at", "canceled_at"]
        extra_kwargs = {
            "room": {"required": False},
            "slot": {"required": False},
            "start": {"required": False},
            "end": {"required": False},
        }


class AvailabilitySlotSerializer(serializers.ModelSerializer):
    is_full = serializers.SerializerMethodField()

    class Meta:
        model = AvailabilitySlot
        fields = ["id", "room", "start", "end", "max_bookings", "is_full"]
        read_only_fields = ["room", "is_full"]

    def get_is_full(self, obj):
        return obj.is_full


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            "id",
            "user",
            "room",
            "amount",
            "currency",
            "stripe_checkout_session_id",
            "stripe_payment_intent_id",
            "status",
            "created_at",
        ]
        read_only_fields = fields


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id",
            "type",
            "title",
            "body",
            "thread",
            "message",
            "is_read",
            "created_at",
        ]
        read_only_fields = fields


class ReportSerializer(serializers.ModelSerializer):
    target_type = serializers.ChoiceField(
        choices=[c[0] for c in Report.TARGET_CHOICES]
    )

    class Meta:
        model = Report
        fields = [
            "id",
            "reporter",
            "target_type",
            "object_id",
            "reason",
            "details",
            "status",
            "handled_by",
            "resolution_notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "reporter",
            "status",
            "handled_by",
            "resolution_notes",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        model_map = {
            "room": Room,
            "review": Review,
            "message": Message,
            "user": User,
        }
        model = model_map.get(attrs["target_type"])
        if not model or not model.objects.filter(pk=attrs["object_id"]).exists():
            raise serializers.ValidationError(
                {"object_id": "Invalid object ID for the given target type."}
            )
        return attrs

    def create(self, validated_data):
        model = {
            "room": Room,
            "review": Review,
            "message": Message,
            "user": User,
        }[validated_data["target_type"]]
        validated_data["content_type"] = ContentType.objects.get_for_model(model)
        validated_data["reporter"] = self.context["request"].user
        return super().create(validated_data)


# --- GDPR ---
class GDPRExportStartSerializer(serializers.Serializer):
    confirm = serializers.BooleanField(required=True)


class GDPRDeleteConfirmSerializer(serializers.Serializer):
    confirm = serializers.BooleanField(required=True)
    idempotency_key = serializers.CharField(
        required=False, allow_blank=True, max_length=64
    )


# --- OTP Serializers (single, final versions) ---
class EmailOTPVerifySerializer(serializers.Serializer):
    """
    Used by /api/auth/verify-otp/
    """
    user_id = serializers.IntegerField()
    code = serializers.CharField(max_length=6)

    def validate_user_id(self, value):
        UserModel = get_user_model()
        if not UserModel.objects.filter(pk=value).exists():
            raise serializers.ValidationError("User not found.")
        return value

    def validate_code(self, value):
        value = (value or "").strip()
        if len(value) != 6 or not value.isdigit():
            raise serializers.ValidationError("Code must be a 6-digit number.")
        return value


class EmailOTPResendSerializer(serializers.Serializer):
    """
    Used by /api/auth/resend-otp/
    """
    user_id = serializers.IntegerField()

    def validate_user_id(self, value):
        UserModel = get_user_model()
        if not UserModel.objects.filter(pk=value).exists():
            raise serializers.ValidationError("User not found.")
        return value


class OnboardingCompleteSerializer(serializers.Serializer):
    confirm = serializers.BooleanField()



class PhoneOTPStartSerializer(serializers.Serializer):
    phone = serializers.CharField()

    def validate_phone(self, value):
        v = (value or "").strip()
        if v == "":
            raise serializers.ValidationError("Phone number is required.")
        # keep simple to match UI; you can tighten later (E.164 etc.)
        if len(v) < 8:
            raise serializers.ValidationError("Phone number looks too short.")
        return v


class PhoneOTPVerifySerializer(serializers.Serializer):
    phone = serializers.CharField()
    code = serializers.CharField()

    def validate_phone(self, value):
        v = (value or "").strip()
        if v == "":
            raise serializers.ValidationError("Phone number is required.")
        return v

    def validate_code(self, value):
        v = (value or "").strip()
        if len(v) != 6 or not v.isdigit():
            raise serializers.ValidationError("OTP must be 6 digits.")
        return v
    
    
class NotificationPreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = (
            "marketing_consent",
            "notify_rentout_updates",
            "notify_reminders",
            "notify_messages",
            "notify_confirmations",
        )




class InboxItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["thread", "notification"])
    created_at = serializers.DateTimeField()

    # common display fields
    title = serializers.CharField(allow_blank=True, required=False)
    preview = serializers.CharField(allow_blank=True, required=False)
    is_read = serializers.BooleanField()

    # ids so frontend can open the right thing
    thread_id = serializers.IntegerField(required=False)
    notification_id = serializers.IntegerField(required=False)

    # optional helper for routing in frontend
    deep_link = serializers.CharField(allow_blank=True, required=False)
    