from django.contrib.auth.models import User
from rest_framework import serializers

from propertylist_app.models import (
    Room,
    RoomCategorie,
    Review,
    UserProfile,
    RoomImage,
    SavedRoom,
    MessageThread,
    Message,
    Booking,
    AvailabilitySlot,Payment,
    Report
)
from django.contrib.contenttypes.models import ContentType


from propertylist_app.validators import (
    validate_person_name,
    validate_age_18_plus,
    validate_avatar_image,
    normalize_uk_postcode,
    validate_listing_title,
    sanitize_html_description,
    validate_price,
    validate_available_from,
    validate_choice,
    validate_listing_photos,
    sanitize_search_text,
    validate_numeric_range,
    validate_radius_miles,      # ← use miles consistently
    validate_pagination,
    validate_ordering,
    normalise_price,
    normalise_phone,
    normalise_name,
    assert_not_duplicate_listing,
    assert_no_duplicate_files,
    enforce_user_caps,
)


# --------------------
# Reviews
# --------------------
class ReviewSerializer(serializers.ModelSerializer):
    review_user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Review
        fields = "__all__"


# --------------------
# Rooms
# --------------------
class RoomSerializer(serializers.ModelSerializer):
    # Read-only label of the category name (nice for clients to display)
    category = serializers.CharField(source="category.name", read_only=True)
    # Write-only category setter (so creates/updates still work)
    category_id = serializers.PrimaryKeyRelatedField(
        source="category", queryset=RoomCategorie.objects.all(), write_only=True
    )

    # Extras
    is_saved = serializers.SerializerMethodField(read_only=True)
    distance_miles = serializers.SerializerMethodField(read_only=True)

    # ---- Field validators you already wrote ----
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
        postcode_guess = parts[-1]
        normalize_uk_postcode(postcode_guess)  # raises if invalid
        return value

    def validate_available_from(self, value):
        return validate_available_from(value)

    def validate_property_type(self, value):
        allowed = {c[0] for c in Room._meta.get_field("property_type").choices}
        return validate_choice(value, allowed, label="property_type")

    def validate_image(self, value):
        validate_listing_photos([value])
        assert_no_duplicate_files([value])
        return value

    # ---- Object-level validation (merged) ----
    def validate(self, attrs):
        price = attrs.get("price_per_month")
        bills_included = attrs.get("bills_included")
        available_from = attrs.get("available_from")

        # price sanity (if present in partial updates)
        if price is not None:
            validate_price(price, min_val=50.0, max_val=20000.0)

        # bills_included guard
        if bills_included and price is not None and float(price) < 100.0:
            raise serializers.ValidationError({
                "bills_included": "Bills cannot be included for such a low price."
            })

        # non-negative integers
        for field in ("number_of_bedrooms", "number_of_bathrooms"):
            val = attrs.get(field)
            if val is not None and int(val) < 0:
                raise serializers.ValidationError({field: "Must be zero or a positive integer."})

        # availability guard
        if available_from is not None:
            validate_available_from(available_from)

               # ----- Per-owner, case-insensitive title uniqueness -----
        # Matches the DB constraint (Lower('title') + property_owner)
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            # figure out the final title we are validating against
            new_title = attrs.get("title")
            current_title = getattr(self.instance, "title", None)

            # only check if creating or title is changing
            if (self.instance is None and new_title) or (new_title and new_title != current_title):
                exists = (
                    Room.objects
                    .filter(property_owner=request.user)
                    .filter(title__iexact=new_title)
                )
                if self.instance is not None:
                    exists = exists.exclude(pk=self.instance.pk)
                if exists.exists():
                    raise serializers.ValidationError({
                        "title": "You already have a room with this title."
                    })


        # caps (on create only)
        if self.instance is None and self.context.get("request"):
            user = self.context["request"].user
            enforce_user_caps(
                user,
                listings_qs=Room.objects,
                max_listings=5
            )

        return attrs

    # keep your explicit field declarations (mirror model types)
    property_type = serializers.ChoiceField(
        choices=[('flat','Flat'), ('house','House'), ('studio','Studio')],
        required=True
    )
    price_per_month = serializers.DecimalField(max_digits=10, decimal_places=2, required=True)
    available_from  = serializers.DateField(required=True)

    class Meta:
        model = Room
        fields = "__all__"  # includes declared extra fields (category, category_id, is_saved, distance_miles)

    def get_is_saved(self, obj):
        request = self.context.get("request")
        if not request or not request.user or not request.user.is_authenticated:
            return False
        return SavedRoom.objects.filter(user=request.user, room=obj.id).exists()

    def get_distance_miles(self, obj):
        val = getattr(obj, "distance_miles", None)
        return round(val, 2) if isinstance(val, (int, float)) else val


class RoomCategorieSerializer(serializers.ModelSerializer):
    # slug is generated by the model; don’t let clients set it directly
    slug = serializers.SlugField(read_only=True)

    class Meta:
        model = RoomCategorie
        fields = "__all__"   # includes: key, name, about, website, slug, active


# --------------------
# Search filters
# --------------------
class SearchFiltersSerializer(serializers.Serializer):
    # free-text
    q = serializers.CharField(required=False, allow_blank=True)

    # numeric ranges
    min_price = serializers.DecimalField(required=False, max_digits=10, decimal_places=2)
    max_price = serializers.DecimalField(required=False, max_digits=10, decimal_places=2)

    # geography
    postcode = serializers.CharField(required=False)
    radius_miles = serializers.FloatField(required=False)   # ← standardized to miles

    # pagination / ordering
    limit = serializers.IntegerField(required=False)
    page = serializers.IntegerField(required=False)
    offset = serializers.IntegerField(required=False)
    ordering = serializers.CharField(required=False)  # e.g. "price_per_month,-available_from"

    # whitelist of fields the API allows clients to sort by
    ALLOWED_ORDER_FIELDS = {"price_per_month", "available_from", "created_at"}

    def validate_q(self, value):
        return sanitize_search_text(value)

    def validate_min_price(self, value):
        return validate_price(value, min_val=0.0, max_val=20000.0)

    def validate_max_price(self, value):
        return validate_price(value, min_val=0.0, max_val=20000.0)

    def validate_postcode(self, value):
        return normalize_uk_postcode(value) if value else value

    def validate_radius_miles(self, value):
        return validate_radius_miles(value, max_miles=100)

    def validate_ordering(self, value):
        return validate_ordering(value, self.ALLOWED_ORDER_FIELDS)

    def validate(self, attrs):
        # price range consistency
        validate_numeric_range(attrs.get("min_price"), attrs.get("max_price"),
                               label_min="min_price", label_max="max_price")

        # pagination rules
        validate_pagination(attrs.get("limit"), attrs.get("page"), attrs.get("offset"),
                            max_limit=50)

        # postcode requires radius if doing geo search (optional rule)
        if attrs.get("radius_miles") and not attrs.get("postcode"):
            raise serializers.ValidationError({"postcode": "Postcode is required when using radius search."})

        return attrs


# --------------------
# Auth / Profile
# --------------------
class RegistrationSerializer(serializers.ModelSerializer):
    password2 = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["username", "email", "password", "password2"]
        extra_kwargs = {"password": {"write_only": True}}

    def validate(self, data):
        if data["password"] != data["password2"]:
            raise serializers.ValidationError("Passwords must match.")
        return data


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
        fields = ["phone", "avatar"]  # now includes avatar

    def validate_avatar(self, file):
        if file is None:
            return file
        return validate_avatar_image(file)

# --------------------
# Photos / Messages / Bookings / Slots
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
        fields = ["id", "thread", "sender", "body", "created_at"]
        read_only_fields = ["thread", "sender", "created_at"]


class MessageThreadSerializer(serializers.ModelSerializer):
    participants = serializers.SlugRelatedField(
        slug_field="username",
        many=True,
        queryset=User.objects.all()
    )
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = MessageThread
        fields = ["id", "participants", "created_at", "last_message", "unread_count"]

    def get_last_message(self, obj):
        msg = obj.messages.order_by("-created_at").first()
        return MessageSerializer(msg).data if msg else None

    def get_unread_count(self, obj):
        """
        Count messages in this thread that:
        - were NOT sent by the current user, and
        - do NOT have a MessageRead record for the current user.
        """
        request = self.context.get("request")
        if not request or not request.user or not request.user.is_authenticated:
            return 0

        # Avoid N+1: the query is filtered; it's fine for now.
        return (
            obj.messages
            .exclude(sender=request.user)
            .exclude(reads__user=request.user)
            .count()
        )


class BookingSerializer(serializers.ModelSerializer):
    room_title = serializers.CharField(source="room.title", read_only=True)

    class Meta:
        model = Booking
        fields = ["id", "room", "slot", "room_title", "start", "end", "created_at", "canceled_at"]
        read_only_fields = ["created_at", "canceled_at"]


class AvailabilitySlotSerializer(serializers.ModelSerializer):
    is_full = serializers.SerializerMethodField()

    class Meta:
        model = AvailabilitySlot
        fields = ["id", "room", "start", "end", "max_bookings", "is_full"]
        read_only_fields = ["room", "is_full"]

    def get_is_full(self, obj):
        # relies on AvailabilitySlot.is_full property (backed by Booking FK with related_name="bookings")
        return obj.is_full


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            "id", "user", "room", "amount", "currency",
            "stripe_checkout_session_id", "stripe_payment_intent_id",
            "status", "error_message", "created_at"
        ]
        read_only_fields = [
            "user", "amount", "currency",
            "stripe_checkout_session_id", "stripe_payment_intent_id",
            "status", "error_message", "created_at"
        ]
    
    
class ReportSerializer(serializers.ModelSerializer):
    # Accept a friendly "target_type" + "object_id" from the client
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
        ttype = attrs.get("target_type")
        oid = attrs.get("object_id")
        if ttype == "room":
            model = Room
        elif ttype == "review":
            from propertylist_app.models import Review
            model = Review
        elif ttype == "message":
            from propertylist_app.models import Message
            model = Message
        elif ttype == "user":
            from django.contrib.auth import get_user_model
            model = get_user_model()
        else:
            raise serializers.ValidationError({"target_type": "Unsupported target type."})

        # ensure the object exists
        if not model.objects.filter(pk=oid).exists():
            raise serializers.ValidationError({"object_id": f"{ttype} with id {oid} does not exist."})

        return attrs

    def create(self, validated_data):
        # map target_type to content_type
        ttype = validated_data["target_type"]
        oid = validated_data["object_id"]

        if ttype == "room":
            model = Room
        elif ttype == "review":
            from propertylist_app.models import Review
            model = Review
        elif ttype == "message":
            from propertylist_app.models import Message
            model = Message
        else:
            from django.contrib.auth import get_user_model
            model = get_user_model()

        validated_data["content_type"] = ContentType.objects.get_for_model(model)
        # default status is "open"
        validated_data["reporter"] = self.context["request"].user
        return super().create(validated_data)
    