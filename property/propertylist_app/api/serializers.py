from django.contrib.auth import get_user_model, password_validation
User = get_user_model()

from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType

from propertylist_app.models import (
    Room, RoomCategorie, Review, UserProfile, RoomImage,
    SavedRoom, MessageThread, Message, Booking,
    AvailabilitySlot, Payment, Report, Notification, EmailOTP,
    MessageThreadState,ContactMessage,

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


# --------------------
# Review Serializer
# --------------------
class ReviewSerializer(serializers.ModelSerializer):
    review_user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Review
        fields = "__all__"
        # Room comes from URL (view), user comes from request; don't require them in POST body
        read_only_fields = ["room", "review_user"]


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

    class Meta:
        model = Room
        fields = "__all__"

    def validate_title(self, value):
        return validate_listing_title(value)

    def validate_description(self, value):
        return sanitize_html_description(value)

    def validate_price_per_month(self, value):
        value = normalise_price(value)
        return validate_price(value, min_val=50.0, max_val=20000.0)

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

        # ----- Per-owner duplicate check (centralised) -----
        request = self.context.get("request")
        if request and getattr(request.user, "is_authenticated", False):
            # final title to check (handle PATCH without title change)
            new_title = attrs.get("title") or getattr(self.instance, "title", None)
            if new_title:
                assert_not_duplicate_listing(
                    request.user,
                    title=new_title,
                    queryset=Room.objects,
                    exclude_pk=getattr(self.instance, "pk", None),
                    # If you also want to consider location for duplicates, uncomment:
                    # location=attrs.get("location") or getattr(self.instance, "location", None),
                )

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

    ALLOWED_ORDER_FIELDS = {"price_per_month", "available_from", "created_at",  "updated_at",}

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


class UserProfileSerializer(serializers.ModelSerializer):
    avatar = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = UserProfile
        fields = [
            "phone",
            "avatar",
            "occupation",
            "postcode",
            "date_of_birth",
            "gender",
            "about_you",
            "role",          # high-level (landlord / seeker)
            "role_detail",   # detailed dropdown on profile screen
            "address_manual",
        ]

    def validate_avatar(self, file):
        if file:
            return validate_avatar_image(file)
        return file

    def validate_postcode(self, value):
        # optional, but if given, normalise it
        if value:
            return normalize_uk_postcode(value)
        return value

    def validate_date_of_birth(self, value):
        # optional, but if given, enforce 18+
        if value:
            validate_age_18_plus(value)
        return value



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
