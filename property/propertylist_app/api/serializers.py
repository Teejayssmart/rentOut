from django.contrib.auth import get_user_model
User = get_user_model()

from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType

from propertylist_app.models import (
    Room, RoomCategorie, Review, UserProfile, RoomImage,
    SavedRoom, MessageThread, Message, Booking,
    AvailabilitySlot, Payment, Report, Notification,
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
    category_id = serializers.PrimaryKeyRelatedField(source="category", queryset=RoomCategorie.objects.all(), write_only=True)
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
        price          = attrs.get("price_per_month")
        bills_included = attrs.get("bills_included")
        available_from = attrs.get("available_from")

        # price sanity (respect Decimal); allow partial updates
        if price is not None:
            validate_price(price, min_val=50.0, max_val=20000.0)

        # bills_included guard (only when price is provided)
        if bills_included and price is not None and float(price) < 100.0:
            raise serializers.ValidationError({
                "bills_included": "Bills cannot be included for such a low price."
            })

        # non-negative integers
        for field in ("number_of_bedrooms", "number_of_bathrooms"):
            val = attrs.get(field)
            if val is not None and int(val) < 0:
                raise serializers.ValidationError({field: "Must be zero or a positive integer."})

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
        user = self.context.get("request").user if self.context.get("request") else None
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

    ALLOWED_ORDER_FIELDS = {"price_per_month", "available_from", "created_at"}

    def validate(self, attrs):
        validate_numeric_range(attrs.get("min_price"), attrs.get("max_price"))
        validate_pagination(attrs.get("limit"), attrs.get("page"), attrs.get("offset"))
        if attrs.get("radius_miles") and not attrs.get("postcode"):
            raise serializers.ValidationError({"postcode": "Postcode is required when using radius search."})
        return attrs


# --------------------
# User & Auth
# --------------------
class RegistrationSerializer(serializers.ModelSerializer):
    # Accept password2 but don’t require it (so tests that only send `password` won’t 500)
    password2 = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ["username", "email", "password", "password2"]
        extra_kwargs = {"password": {"write_only": True}}

    def validate(self, attrs):
        pw = attrs.get("password")
        pw2 = attrs.get("password2", "")
        if pw2 and pw != pw2:
            raise serializers.ValidationError({"password2": "Passwords must match."})
        return attrs

    def create(self, validated_data):
        # Remove password2 if present, hash password properly
        validated_data.pop("password2", None)
        password = validated_data.pop("password")
        user = User.objects.create_user(**validated_data, password=password)
        return user

    def to_representation(self, instance):
        # Keep the 201 response clean; don’t leak anything sensitive
        return {
            "id": instance.pk,
            "username": instance.username,
            "email": instance.email,
        }



class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
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
        fields = ["phone", "avatar"]

    def validate_avatar(self, file):
        if file:
            return validate_avatar_image(file)
        return file


# --------------------
# Room Images / Messages / Bookings / Slots / Payments / Reports
# --------------------
class RoomImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomImage
        fields = ["id", "room", "image"]
        read_only_fields = ["room"]


class MessageSerializer(serializers.ModelSerializer):
    sender = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Message
        fields = ["id", "thread", "sender", "body", "created"]
        read_only_fields = ["thread", "sender", "created"]


class MessageThreadSerializer(serializers.ModelSerializer):
    participants = serializers.SlugRelatedField(slug_field="username", many=True, queryset=User.objects.all())
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = MessageThread
        fields = ["id", "participants", "created_at", "last_message", "unread_count"]

    def get_last_message(self, obj):
        msg = obj.messages.order_by("-created").first()
        return MessageSerializer(msg).data if msg else None

    def get_unread_count(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return 0
        return obj.messages.exclude(sender=request.user).exclude(reads__user=request.user).count()


class BookingSerializer(serializers.ModelSerializer):
    room_title = serializers.CharField(source="room.title", read_only=True)

    class Meta:
        model = Booking
        fields = ["id", "room", "slot", "room_title", "start", "end", "created_at", "canceled_at"]
        read_only_fields = ["created_at", "canceled_at"]
        extra_kwargs = {
            "room":  {"required": False},
            "slot":  {"required": False},
            "start": {"required": False},
            "end":   {"required": False},
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
            "id", "user", "room", "amount", "currency",
            "stripe_checkout_session_id", "stripe_payment_intent_id",
            "status", "created_at"
        ]
        read_only_fields = fields
        
        
class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id", "type", "title", "body",
            "thread", "message",
            "is_read", "created_at",
        ]
        read_only_fields = fields
        


class ReportSerializer(serializers.ModelSerializer):
    target_type = serializers.ChoiceField(choices=[c[0] for c in Report.TARGET_CHOICES])

    class Meta:
        model = Report
        fields = [
            "id", "reporter", "target_type", "object_id",
            "reason", "details",
            "status", "handled_by", "resolution_notes",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "reporter", "status", "handled_by", "resolution_notes", "created_at", "updated_at"]

    def validate(self, attrs):
        model_map = {
            "room": Room,
            "review": Review,
            "message": Message,
            "user": User,
        }
        model = model_map.get(attrs["target_type"])
        if not model or not model.objects.filter(pk=attrs["object_id"]).exists():
            raise serializers.ValidationError({"object_id": "Invalid object ID for the given target type."})
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
    idempotency_key = serializers.CharField(required=False, allow_blank=True, max_length=64)
