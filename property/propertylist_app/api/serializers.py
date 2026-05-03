from django.contrib.auth import get_user_model, password_validation,authenticate
User = get_user_model()
from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType
import re
from dateutil.relativedelta import relativedelta
from datetime import date, datetime, time, timedelta
from datetime import date as _date  # add if not already present
from django.shortcuts import get_object_or_404
from django.db import transaction


from typing import Optional, Any, Dict, List
from drf_spectacular.types import OpenApiTypes


from drf_spectacular.utils import extend_schema_field
from propertylist_app.models import Room, Booking, Tenancy  # ensure Booking + Tenancy imported
from propertylist_app.models import (
    Room, RoomCategorie, Review, UserProfile, RoomImage,
    SavedRoom, MessageThread, Message, Booking,
    AvailabilitySlot, Payment, Report, Notification, EmailOTP,
    MessageThreadState, ContactMessage,PhoneOTP,Tenancy,

)
from propertylist_app.validators import (
    validate_person_name, validate_age_18_plus, validate_avatar_image,
    normalize_uk_postcode, validate_listing_title, sanitize_html_description,
    validate_price, validate_available_from, validate_choice,
    validate_listing_photos, sanitize_search_text, validate_numeric_range,
    validate_radius_miles, validate_pagination, validate_ordering,
    normalise_price, normalise_phone, normalise_name, normalise_email,
    sanitize_plain_text,
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
            "tenancy",
        )

    @extend_schema_field(OpenApiTypes.URI)
    def get_reviewer_avatar(self, obj) -> Optional[str]:
        """
        reviewer.profile is your OneToOne related_name.
        Return the avatar URL if present, else None.
        """
        profile = getattr(getattr(obj, "reviewer", None), "profile", None)
        avatar = getattr(profile, "avatar", None)
        if not avatar:
            return None

        request = self.context.get("request")
        try:
            url = avatar.url
        except Exception:
            return None

        if request is not None:
            return request.build_absolute_uri(url)
        return url



class ReviewSerializer(serializers.ModelSerializer):
    review_mode = serializers.SerializerMethodField()
    display_summary = serializers.SerializerMethodField()
    positive_labels = serializers.SerializerMethodField()
    negative_labels = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = [
            "id",
            "tenancy",
            "reviewer",
            "reviewee",
            "role",
            "review_flags",
            "overall_rating",
            "notes",
            "display_summary",
            "review_mode",
            "positive_labels",
            "negative_labels",
            "submitted_at",
            "reveal_at",
            "active",
        ]
        read_only_fields = fields

    # --- keep the same flag sets as models.py save() logic (must match exactly) ---
    TENANT_TO_LANDLORD_POS = {"responsive", "maintenance_good", "accurate_listing", "respectful_fair"}
    TENANT_TO_LANDLORD_NEG = {"unresponsive", "maintenance_poor", "misleading_listing", "unfair_treatment"}

    LANDLORD_TO_TENANT_POS = {
        "clean_and_tidy",
        "friendly",
        "good_communication",
        "paid_on_time",
        "property_care_good",
        "followed_rules",
    }
    LANDLORD_TO_TENANT_NEG = {
        "messy",
        "rude",
        "poor_communication",
        "late_payment",
        "property_care_poor",
        "broke_rules",
    }

    # Optional: label text for flags (frontend-friendly)
    FLAG_LABELS = {
        # Tenant -> Landlord
        "responsive": "Responsive",
        "maintenance_good": "Good maintenance",
        "accurate_listing": "Accurate listing",
        "respectful_fair": "Respectful and fair",
        "unresponsive": "Unresponsive",
        "maintenance_poor": "Poor maintenance",
        "misleading_listing": "Misleading listing",
        "unfair_treatment": "Unfair treatment",

        # Landlord -> Tenant
        "clean_and_tidy": "Clean and tidy",
        "friendly": "Friendly",
        "good_communication": "Good communication",
        "paid_on_time": "Paid on time",
        "property_care_good": "Took care of the property",
        "followed_rules": "Followed the rules",
        "messy": "Messy",
        "rude": "Rude",
        "poor_communication": "Poor communication",
        "late_payment": "Late payment",
        "property_care_poor": "Poor care of the property",
        "broke_rules": "Broke the rules",
    }

    @extend_schema_field(OpenApiTypes.STR)
    def get_review_mode(self, obj) -> str:
        flags = obj.review_flags or []
        return "checklist" if flags else "text"

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_positive_labels(self, obj) -> List[str]:
        flags = set(obj.review_flags or [])
        if obj.role == Review.ROLE_TENANT_TO_LANDLORD:
            pos = flags.intersection(self.TENANT_TO_LANDLORD_POS)
        else:
            pos = flags.intersection(self.LANDLORD_TO_TENANT_POS)
        return [self.FLAG_LABELS.get(k, k) for k in sorted(pos)]

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_negative_labels(self, obj) -> List[str]:
        flags = set(obj.review_flags or [])
        if obj.role == Review.ROLE_TENANT_TO_LANDLORD:
            neg = flags.intersection(self.TENANT_TO_LANDLORD_NEG)
        else:
            neg = flags.intersection(self.LANDLORD_TO_TENANT_NEG)
        return [self.FLAG_LABELS.get(k, k) for k in sorted(neg)]

    @extend_schema_field(OpenApiTypes.STR)
    def get_display_summary(self, obj) -> str:
        """
        Hard rule:
        - If notes exist (text option), return notes EXACTLY as stored (no edits).
        - If checklist option, generate a short sentence from selected labels.
        """
        flags = obj.review_flags or []
        notes = obj.notes

        # Option B: text + stars (do not tamper)
        if not flags:
            return notes if notes is not None else ""

        # Option A: checklist -> backend-generated wording
        pos = self.get_positive_labels(obj)
        neg = self.get_negative_labels(obj)

        parts = []
        if pos:
            parts.append(", ".join(pos))
        if neg:
            parts.append("However: " + ", ".join(neg))

        return ". ".join(parts) if parts else ""



class ReviewCreateSerializer(serializers.Serializer):
    tenancy_id = serializers.IntegerField()

    #  allow manual rating input (1â€“5) when flags are not provided
    overall_rating = serializers.IntegerField(min_value=1, max_value=5, required=False)

    review_flags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        allow_empty=True,
    )
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)
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
    "clean_and_tidy",
    "friendly",
    "good_communication",
    "paid_on_time",
    "property_care_good",
    "followed_rules",
    "messy",
    "rude",
    "poor_communication",
    "late_payment",
    "property_care_poor",
    "broke_rules",
    }



    def validate(self, attrs):
        request = self.context["request"]
        user = request.user
        now = timezone.now()

        tenancy_id = attrs.get("tenancy_id")
        tenancy = (
            Tenancy.objects.select_related("room", "landlord", "tenant")
            .filter(id=tenancy_id)
            .first()
        )
        if not tenancy:
            raise serializers.ValidationError({"tenancy_id": "Tenancy does not exist."})

        if user.id not in {tenancy.tenant_id, tenancy.landlord_id}:
            raise serializers.ValidationError("You are not allowed to review this tenancy.")

        if tenancy.status not in {
            Tenancy.STATUS_CONFIRMED,
            Tenancy.STATUS_ACTIVE,
            Tenancy.STATUS_ENDED,
        }:
            raise serializers.ValidationError("Tenancy is not confirmed yet.")

        if not tenancy.review_open_at:
            raise serializers.ValidationError("Tenancy review schedule is not ready yet.")

        if now < tenancy.review_open_at:
            raise serializers.ValidationError("You can only review after the tenancy ends (plus 7 days).")

        if tenancy.review_deadline_at and now > tenancy.review_deadline_at:
            raise serializers.ValidationError("The review window has expired.")

        # Determine role + reviewee securely
        if user.id == tenancy.tenant_id:
            role = Review.ROLE_TENANT_TO_LANDLORD
            reviewee = tenancy.landlord
        else:
            role = Review.ROLE_LANDLORD_TO_TENANT
            reviewee = tenancy.tenant

        if Review.objects.filter(tenancy=tenancy, role=role).exists():
            raise serializers.ValidationError("You have already submitted a review for this tenancy.")

        # Review content mode
        flags = attrs.get("review_flags") or []
        notes = attrs.get("notes")
        manual_rating = attrs.get("overall_rating")

        # Reject unknown flags
        invalid_flags = [f for f in flags if f not in self.ALLOWED_FLAGS]
        if invalid_flags:
            raise serializers.ValidationError(
                {"review_flags": [f"Invalid review flag(s): {', '.join(sorted(set(invalid_flags)))}"]}
            )

        has_flags = len(flags) > 0
        has_text = bool((notes or "").strip())
        has_manual_rating = manual_rating is not None

        if has_flags:
            # Option A: checklist only
            if has_text:
                raise serializers.ValidationError(
                    {"notes": "Do not send notes when using review_flags (checklist option)."}
                )
            if has_manual_rating:
                raise serializers.ValidationError(
                    {"overall_rating": "Do not send overall_rating when using review_flags (checklist option)."}
                )
        else:
            # Option B: text + rating only
            if not has_text:
                raise serializers.ValidationError(
                    {"notes": "Provide notes when not using review_flags (text option)."}
                )
            if not has_manual_rating:
                raise serializers.ValidationError(
                    {"overall_rating": "Provide overall_rating (1-5) when not using review_flags (text option)."}
                )

        attrs["tenancy"] = tenancy
        attrs["reviewer"] = user
        attrs["reviewee"] = reviewee
        attrs["role"] = role


        return attrs

    def create(self, validated_data):
        # tenancy_id is only an input field; tenancy is already in validated_data
        validated_data.pop("tenancy_id", None)
        return Review.objects.create(**validated_data)


class StillLivingConfirmResponseSerializer(serializers.Serializer):
    tenancy_id = serializers.IntegerField()
    landlord_confirmed = serializers.BooleanField()
    tenant_confirmed = serializers.BooleanField()
    still_living_confirmed_at = serializers.DateTimeField(allow_null=True)


class TenancyExtensionCreateSerializer(serializers.Serializer):
    proposed_duration_months = serializers.IntegerField(min_value=1, max_value=24)


class TenancyExtensionRespondSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["accept", "reject"])


class TenancyExtensionResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    tenancy_id = serializers.IntegerField()
    proposed_by_user_id = serializers.IntegerField()
    proposed_duration_months = serializers.IntegerField()
    status = serializers.CharField()
    responded_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()




class TenancyProposalSerializer(serializers.Serializer):
    """
    Creates a tenancy proposal between a landlord (room owner) and a tenant (any other user).

    Rules:
    - room_id must exist
    - counterparty_user_id must be the "other person" (cannot be yourself)
    - landlord is always room.property_owner
    - if the requester is the landlord, counterparty is tenant
    - if the requester is not the landlord, counterparty must be the landlord (prevents proposing to random users)
    - move_in_date cannot be in the past
    - duration_months: 1..12
    - prevents duplicate open proposals for same room + same landlord + same tenant
    """

    room_id = serializers.IntegerField()
    counterparty_user_id = serializers.IntegerField()  # landlord supplies tenant, tenant supplies landlord
    move_in_date = serializers.DateField()
    duration_months = serializers.IntegerField(min_value=1, max_value=12)

    def _has_completed_viewing(self, *, room, user):
        now = timezone.now()
        return Booking.objects.filter(
            room=room,
            user=user,
            is_deleted=False,
            status=Booking.STATUS_ACTIVE,
            canceled_at__isnull=True,
            end__lte=now,  # viewing completed
        ).exists()

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user

        room = Room.objects.select_related("property_owner").filter(id=attrs["room_id"]).first()
        if not room:
            raise serializers.ValidationError({"room_id": "Room not found."})

        landlord = getattr(room, "property_owner", None)
        if not landlord:
            raise serializers.ValidationError({"room_id": "Room has no property owner."})

        counterparty_id = attrs["counterparty_user_id"]
        if counterparty_id == user.id:
            raise serializers.ValidationError({"counterparty_user_id": "Counterparty cannot be yourself."})

        if attrs["move_in_date"] < timezone.localdate():
            raise serializers.ValidationError({"move_in_date": "Move-in date cannot be in the past."})

        # role resolution
        if user.id == landlord.id:
            tenant = User.objects.filter(id=counterparty_id).first()
            if not tenant:
                raise serializers.ValidationError({"counterparty_user_id": "Tenant user not found."})

            # enforce: landlord can only choose a tenant who has completed a viewing
            if not self._has_completed_viewing(room=room, user=tenant):
                raise serializers.ValidationError(
                    {"counterparty_user_id": "Tenant must have completed a viewing for this room before tenancy can be proposed."}
                )

        else:
            if counterparty_id != landlord.id:
                raise serializers.ValidationError(
                    {"counterparty_user_id": "For this room, the counterparty must be the landlord."}
                )
            tenant = user

            # enforce: tenant must have completed a viewing
            if not self._has_completed_viewing(room=room, user=tenant):
                raise serializers.ValidationError(
                    {"room_id": "You must have completed a viewing for this room before proposing a tenancy."}
                )



        attrs["room"] = room
        attrs["landlord"] = landlord
        attrs["tenant"] = tenant
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        now = timezone.now()

        room = validated_data["room"]
        landlord = validated_data["landlord"]
        tenant = validated_data["tenant"]

        # proposer auto-confirms their side
        landlord_confirmed_at = now if user.id == landlord.id else None
        tenant_confirmed_at = now if user.id == tenant.id else None

        tenancy, created = Tenancy.objects.get_or_create(
            room=room,
            tenant=tenant,
            defaults={
                "landlord": landlord,
                "proposed_by": user,
                "move_in_date": validated_data["move_in_date"],
                "duration_months": validated_data["duration_months"],
                "landlord_confirmed_at": landlord_confirmed_at,
                "tenant_confirmed_at": tenant_confirmed_at,
                "status": Tenancy.STATUS_PROPOSED,
            },
        )

        if not created:
            # â€œlast write winsâ€ update
            tenancy.landlord = landlord  # keep consistent with room owner
            tenancy.proposed_by = user
            tenancy.move_in_date = validated_data["move_in_date"]
            tenancy.duration_months = validated_data["duration_months"]

            # reset confirmations: proposer confirmed, other cleared
            if user.id == landlord.id:
                tenancy.landlord_confirmed_at = now
                tenancy.tenant_confirmed_at = None
            else:
                tenancy.tenant_confirmed_at = now
                tenancy.landlord_confirmed_at = None

            tenancy.status = Tenancy.STATUS_PROPOSED

            # clear schedule fields (recomputed on final confirm)
            tenancy.review_open_at = None
            tenancy.review_deadline_at = None
            tenancy.still_living_check_at = None
            tenancy.still_living_confirmed_at = None

            tenancy.save()

        return tenancy


class TenancyRespondSerializer(serializers.Serializer):
    """
    Handles actions on an existing tenancy proposal:
    - confirm: sets the confirmer's confirmed_at timestamp. If both confirmed, locks schedule + sets review dates.
    - propose_changes: updates move_in_date/duration_months, resets confirmations, clears schedule fields.
    - cancel: cancels the tenancy proposal.

    Expected by tests in propertylist_app/tests/tenancies/test_tenancy_proposal_flow.py
    """

    action = serializers.ChoiceField(choices=["confirm", "propose_changes", "cancel"])
    move_in_date = serializers.DateField(required=False)
    duration_months = serializers.IntegerField(min_value=1, max_value=12, required=False)

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user
        tenancy = self.context.get("tenancy")

        if tenancy is None:
            raise serializers.ValidationError("Tenancy context is required.")

        # only landlord or tenant can respond
        if user.id not in (tenancy.landlord_id, tenancy.tenant_id):
            raise serializers.ValidationError("You are not a party to this tenancy.")

        action = attrs["action"]

        if action == "propose_changes":
            if "move_in_date" not in attrs or "duration_months" not in attrs:
                raise serializers.ValidationError(
                    {"non_field_errors": "move_in_date and duration_months are required for propose_changes."}
                )

            # basic sanity: cannot propose a move-in date in the past
            if attrs["move_in_date"] < timezone.localdate():
                raise serializers.ValidationError({"move_in_date": "Move-in date cannot be in the past."})

        return attrs

    @transaction.atomic
    def save(self, **kwargs):
        request = self.context["request"]
        user = request.user
        tenancy = self.context["tenancy"]

        action = self.validated_data["action"]
        now = timezone.now()

        TenancyModel = tenancy.__class__
        STATUS_PROPOSED = getattr(TenancyModel, "STATUS_PROPOSED", "proposed")
        STATUS_CONFIRMED = getattr(TenancyModel, "STATUS_CONFIRMED", "confirmed")
        STATUS_ACTIVE = getattr(TenancyModel, "STATUS_ACTIVE", "active")
        STATUS_CANCELLED = getattr(TenancyModel, "STATUS_CANCELLED", "cancelled")

        def _compute_end_date(move_in_date, duration_months):
            # accurate month math
            return move_in_date + relativedelta(months=+int(duration_months))

        def _set_schedule_fields():
            end_date = _compute_end_date(tenancy.move_in_date, tenancy.duration_months)
            # review opens end + 7 days (your rule)
            tenancy.review_open_at = timezone.make_aware(
                timezone.datetime.combine(end_date, timezone.datetime.min.time())
            ) + timedelta(days=7)

            # optional deadline: end + 60 days (safe default)
            tenancy.review_deadline_at = tenancy.review_open_at + timedelta(days=60)

            # still living check: end - 7 days
            tenancy.still_living_check_at = timezone.make_aware(
                timezone.datetime.combine(end_date, timezone.datetime.min.time())
            ) - timedelta(days=7)

        if action == "cancel":
            tenancy.status = STATUS_CANCELLED
            tenancy.save(update_fields=["status", "updated_at"] if hasattr(tenancy, "updated_at") else ["status"])
            return tenancy

        if action == "propose_changes":
            tenancy.move_in_date = self.validated_data["move_in_date"]
            tenancy.duration_months = self.validated_data["duration_months"]
            tenancy.proposed_by = user

            # reset confirmations
            tenancy.landlord_confirmed_at = None
            tenancy.tenant_confirmed_at = None
            tenancy.status = STATUS_PROPOSED

            # clear schedule-related fields (will be recomputed on confirm)
            tenancy.review_open_at = None
            tenancy.review_deadline_at = None
            tenancy.still_living_check_at = None
            tenancy.still_living_confirmed_at = None

            tenancy.save()
            return tenancy

        # action == "confirm"
        if user.id == tenancy.landlord_id and tenancy.landlord_confirmed_at is None:
            tenancy.landlord_confirmed_at = now
        if user.id == tenancy.tenant_id and tenancy.tenant_confirmed_at is None:
            tenancy.tenant_confirmed_at = now

        # if both confirmed â†’ lock schedule + set status
        if tenancy.landlord_confirmed_at and tenancy.tenant_confirmed_at:
            today = timezone.localdate()
            tenancy.status = STATUS_ACTIVE if tenancy.move_in_date <= today else STATUS_CONFIRMED
            _set_schedule_fields()
        else:
            tenancy.status = STATUS_PROPOSED

        tenancy.save()
        return tenancy




class TenancyDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenancy
        fields = [
            "id", "room", "landlord", "tenant", "proposed_by",
            "move_in_date", "duration_months",
            "landlord_confirmed_at", "tenant_confirmed_at",
            "status",
            "review_open_at", "review_deadline_at",
            "still_living_check_at", "still_living_confirmed_at",
            "created_at", "updated_at",
        ]
        read_only_fields = fields




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
    allow_search_indexing_effective = serializers.SerializerMethodField(read_only=True)

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
            raise serializers.ValidationError("Description must be at least 25 words.")

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
        # normalise_price handles strings like "Â£200" or "200.00"
        value = normalise_price(value)
        # allow zero, but cap it to something sensible
        return validate_price(value, min_val=0.0, max_val=50000.0)

    def validate_location(self, value):
        text = str(value or "").strip()
        if not text:
            raise serializers.ValidationError("Location is required.")

        parts = text.split()

        # Accept both "... SW1A2AA" and "... SW1A 2AA"
        if len(parts) >= 2 and len(parts[-1]) <= 3:
            # last token looks like inward code ("2AA"), so combine last two tokens
            candidate = f"{parts[-2]} {parts[-1]}"
        else:
            candidate = parts[-1]

        normalize_uk_postcode(candidate)
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

        # ----- Minimum / maximum rental period (months, 1â€“12) -----
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
                {
                    "min_stay_months": "Minimum rental period cannot be greater than maximum rental period."
                }
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
                    {
                        "preferred_flatmate_min_age": "Minimum preferred age cannot be greater than maximum preferred age."
                    }
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
                    {
                        "view_available_custom_dates": "Provide at least one date when using custom mode."
                    }
                )
        else:
            attrs["view_available_custom_dates"] = []

        return attrs

    # ---------------------------
    # SerializerMethodField getters (schema-typed)
    # ---------------------------

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_saved(self, obj) -> bool:
        annotated = getattr(obj, "_is_saved", None)
        if annotated is not None:
            return bool(annotated)

        request = self.context.get("request")
        user = getattr(request, "user", None) if request is not None else None
        if not user or not user.is_authenticated:
            return False

        return SavedRoom.objects.filter(user=user, room=obj).exists()

    @extend_schema_field(OpenApiTypes.NUMBER)
    def get_distance_miles(self, obj) -> float | None:
        val = getattr(obj, "distance_miles", None)
        if val is None:
            return None
        try:
            return round(float(val), 2)
        except (TypeError, ValueError):
            return None

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_allow_search_indexing_effective(self, obj) -> bool:
        val = getattr(obj, "allow_search_indexing_effective", None)
        if val is not None:
            return bool(val)

        override = getattr(obj, "allow_search_indexing_override", None)
        if override is not None:
            return bool(override)

        owner = getattr(obj, "property_owner", None)
        profile = getattr(owner, "profile", None) if owner else None
        default = getattr(profile, "allow_search_indexing_default", True)

        return bool(default)

    @extend_schema_field(OpenApiTypes.STR)
    def get_owner_name(self, obj) -> str:
        user = getattr(obj, "property_owner", None)
        if not user:
            return ""
        full_name = (user.get_full_name() or "").strip()
        return full_name or user.username

    @extend_schema_field(OpenApiTypes.URI)
    def get_owner_avatar(self, obj) -> str | None:
        user = getattr(obj, "property_owner", None)
        if not user:
            return None

        profile = getattr(user, "profile", None)
        avatar = getattr(profile, "avatar", None) if profile else None
        if not avatar:
            return None

        request = self.context.get("request")
        url = avatar.url
        if request is not None:
            return request.build_absolute_uri(url)
        return url

    @extend_schema_field(OpenApiTypes.URI)
    def get_main_photo(self, obj) -> str | None:
        approved_images = getattr(obj, "prefetched_approved_images", None)

        if approved_images is not None:
            first_image = approved_images[0] if approved_images else None
        else:
            first_image = (
                obj.roomimage_set.filter(status="approved")
                .order_by("id")
                .first()
            )

        if first_image and first_image.image:
            url = first_image.image.url
        elif getattr(obj, "image", None):
            url = obj.image.url
        else:
            return None

        request = self.context.get("request")
        if request is not None:
            return request.build_absolute_uri(url)
        return url

        request = self.context.get("request")
        if request is not None:
            return request.build_absolute_uri(url)
        return url

    @extend_schema_field(OpenApiTypes.INT)
    def get_photo_count(self, obj):
        val = getattr(obj, "photo_count", None)
        if val is not None:
            return val

        approved_images = getattr(obj, "prefetched_approved_images", None)
        if approved_images is not None:
            approved = len(approved_images)
        else:
            approved = obj.roomimage_set.filter(status="approved").count()

        legacy = 1 if getattr(obj, "image", None) else 0
        return approved + legacy

    @extend_schema_field(OpenApiTypes.STR)
    def get_listing_state(self, obj) -> str:
        """
        Returns one of: 'draft', 'active', 'expired', 'hidden'.
        Used by the 'My Listings' page to group into tabs.
        """
        # If the queryset annotated a listing_state, reuse it.
        state = getattr(obj, "listing_state", None)
        if state:
            return str(state)

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
    room = serializers.SerializerMethodField()
    photos = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_room(self, obj) -> Dict[str, Any]:
        return RoomSerializer(obj, context=self.context).data

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_photos(self, obj) -> List[Dict[str, Any]]:
        # keep your existing logic exactly as-is
        request = self.context.get("request")
        photos = []

        qs = obj.roomimage_set.filter(status="approved").order_by("id")
        for img in qs:
            if not img.image:
                continue
            url = img.image.url
            if request is not None:
                url = request.build_absolute_uri(url)
            photos.append({"id": img.id, "url": url, "status": img.status})

        if not photos and obj.image:
            url = obj.image.url
            if request is not None:
                url = request.build_absolute_uri(url)
            photos.append({"id": None, "url": url, "status": "legacy"})

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
    min_rating = serializers.FloatField(required=False)
    max_rating = serializers.FloatField(required=False)
    postcode = serializers.CharField(required=False)
    street = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=False, allow_blank=True)
    radius_miles = serializers.FloatField(required=False)
    limit = serializers.IntegerField(required=False)
    page = serializers.IntegerField(required=False)
    offset = serializers.IntegerField(required=False)
    ordering = serializers.CharField(required=False)

    def validate_q(self, value):
        return sanitize_search_text(value, max_len=200)

    def validate_postcode(self, value):
        value = sanitize_plain_text(value, max_len=20).upper()
        return normalize_uk_postcode(value)

    def validate_street(self, value):
        return sanitize_plain_text(value, max_len=120)

    def validate_city(self, value):
        return sanitize_plain_text(value, max_len=80)

    # property type filters (basic & advanced)
    property_types = serializers.ListField(
        child=serializers.ChoiceField(choices=["flat", "house", "studio"]),
        required=False,
        allow_empty=True,
    )
    ALLOWED_ORDER_FIELDS = {"price_per_month", "available_from", "created_at"}

    # ========== Advanced search filters ==========
    # â€œRooms in existing sharesâ€
    include_shared = serializers.BooleanField(required=False)

    # â€œRooms suitable for agesâ€
    min_age = serializers.IntegerField(required=False)
    max_age = serializers.IntegerField(required=False)

    # â€œLength of stayâ€
    min_stay_months = serializers.IntegerField(required=False)
    max_stay_months = serializers.IntegerField(required=False)

    # â€œRooms forâ€
    room_for = serializers.ChoiceField(
        choices=["any", "females", "males", "couples"],
        required=False,
    )

    # â€œRoom sizesâ€
    room_size = serializers.ChoiceField(
        choices=["dont_mind", "single", "double"],
        required=False,
    )



    ALLOWED_ORDER_FIELDS = {"price_per_month", "available_from", "created_at", "updated_at"}

    # -----------------------------
    # Advanced Search II - Step 2/3
    # -----------------------------

    move_in_date = serializers.DateField(required=False)

    bathroom_type = serializers.ChoiceField(
        choices=["private", "shared", "no_preference"],
        required=False,
    )

    shared_living_space = serializers.ChoiceField(
        choices=["yes", "no", "no_preference"],
        required=False,
    )


    suitable_for = serializers.ChoiceField(
        choices=["one_person", "couple", "max_occupants", "no_preference"],
        required=False,
    )

    max_occupants = serializers.IntegerField(required=False, min_value=1, max_value=10)

    household_bedrooms_min = serializers.IntegerField(required=False, min_value=0)
    household_bedrooms_max = serializers.IntegerField(required=False, min_value=0)

    household_type = serializers.ChoiceField(
        choices=["professional", "student", "mixed", "no_preference"],
        required=False,
    )

    household_environment = serializers.ChoiceField(
        choices=["quiet", "sociable", "mixed", "no_preference"],
        required=False,
    )

    pets_allowed = serializers.ChoiceField(
        choices=["yes", "no", "no_preference"],
        required=False,
    )

    inclusive_household = serializers.ChoiceField(
        choices=["yes", "no", "no_preference"],
        required=False,
    )

    accessible_entry = serializers.ChoiceField(
        choices=["yes", "no", "no_preference"],
        required=False,
    )

    free_to_contact = serializers.BooleanField(required=False)

    photos_only = serializers.BooleanField(required=False)
    verified_advertisers_only = serializers.BooleanField(required=False)
    advert_by_household = serializers.ChoiceField(
        choices=[
            "live_in_landlord",
            "live_out_landlord",
            "current_flatmate",
            "no_preference",
        ],
        required=False,
    )
    posted_within_days = serializers.IntegerField(required=False, min_value=1, max_value=365)
    # make â€œfalseâ€ meaningful (currently view only filters when true)
    furnished = serializers.BooleanField(required=False)
    bills_included = serializers.BooleanField(required=False)
    parking_available = serializers.BooleanField(required=False)





    def validate(self, attrs):
        # existing price / pagination rules
        validate_numeric_range(attrs.get("min_price"), attrs.get("max_price"))
        validate_pagination(attrs.get("limit"), attrs.get("page"), attrs.get("offset"))

        # radius must have postcode
        if attrs.get("radius_miles") and not attrs.get("postcode"):
            raise serializers.ValidationError(
                {"postcode": "Postcode is required when using radius search."}
            )

        # ages range sanity
        if attrs.get("min_age") is not None or attrs.get("max_age") is not None:
            validate_numeric_range(attrs.get("min_age"), attrs.get("max_age"))

        # stay length range sanity
        if attrs.get("min_stay_months") is not None or attrs.get("max_stay_months") is not None:
            validate_numeric_range(attrs.get("min_stay_months"), attrs.get("max_stay_months"))

        # rating range sanity (1â€“5)
        if attrs.get("min_rating") is not None or attrs.get("max_rating") is not None:
            validate_numeric_range(attrs.get("min_rating"), attrs.get("max_rating"))

            for f in ("min_rating", "max_rating"):
                v = attrs.get(f)
                if v is None:
                    continue
                if v < 1 or v > 5:
                    raise serializers.ValidationError({f: "Must be between 1 and 5."})

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

    def create(self, validated_data):
        validated_data.pop("password2", None)
        role = validated_data.pop("role")
        terms_accepted = validated_data.pop("terms_accepted")
        terms_version = validated_data.pop("terms_version")
        marketing = validated_data.pop("marketing_consent", False)

        password = validated_data.pop("password")
        user = User.objects.create_user(**validated_data, password=password)

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = role
        profile.marketing_consent = bool(marketing)
        profile.terms_accepted_at = timezone.now()
        profile.terms_version = terms_version
        profile.email_verified = False
        profile.save()

        code = get_random_string(6, allowed_chars="0123456789")
        EmailOTP.objects.filter(user=user, used_at__isnull=True).update(
            used_at=timezone.now()
        )
        EmailOTP.create_for(user, code, ttl_minutes=10)

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
            + "â€¢â€¢â€¢@"
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


class LoginTokensSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    access_expires_at = serializers.DateTimeField()
    refresh_expires_at = serializers.DateTimeField()


class UserSerializer(serializers.ModelSerializer):
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "has_password"]

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_has_password(self, obj) -> bool:
        return bool(obj.has_usable_password())


class UserProfileSerializer(serializers.ModelSerializer):
    # tests expect "user" in response
    user = serializers.IntegerField(source="user_id", read_only=True)
    avg_tenant_rating = serializers.FloatField(read_only=True)
    number_tenant_ratings = serializers.IntegerField(read_only=True)
    avg_landlord_rating = serializers.FloatField(read_only=True)
    number_landlord_ratings = serializers.IntegerField(read_only=True)

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
            "avg_tenant_rating",
            "number_tenant_ratings",
            "avg_landlord_rating",
            "number_landlord_ratings",


        )
        read_only_fields = (
            "id",
            "user",
            "avatar",
            "email_verified",
        )

    # ---------- address placeholders (until you implement structured address fields) ----------
    @extend_schema_field(OpenApiTypes.STR)
    def get_address_line_1(self, obj) -> str:
        return ""

    @extend_schema_field(OpenApiTypes.STR)
    def get_address_line_2(self, obj) -> str:
        return ""

    @extend_schema_field(OpenApiTypes.STR)
    def get_city(self, obj) -> str:
        return ""

    @extend_schema_field(OpenApiTypes.STR)
    def get_county(self, obj) -> str:
        return ""

    @extend_schema_field(OpenApiTypes.STR)
    def get_country(self, obj) -> str:
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



class LoginSuccessDataSerializer(serializers.Serializer):
    tokens = LoginTokensSerializer()
    user = UserSerializer()
    profile = UserProfileSerializer()


class LoginResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    data = LoginSuccessDataSerializer()

class TokenPairWithExpirySerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    access_expires_at = serializers.DateTimeField()
    refresh_expires_at = serializers.DateTimeField()


class TokenRefreshRequestSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class TokenRefreshDataSerializer(serializers.Serializer):
    access = serializers.CharField()
    access_expires_at = serializers.DateTimeField()
    refresh_expires_at = serializers.DateTimeField()

    # only present if you ever rotate refresh tokens
    refresh = serializers.CharField(required=False)



class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    email = serializers.EmailField()
    token = serializers.CharField()  # we will use the 6-digit OTP code
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        pw1 = attrs.get("new_password") or ""
        pw2 = attrs.get("confirm_password") or ""
        if pw1 != pw2:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})

        # Reuse Django validators (strong password rules)
        password_validation.validate_password(pw1)
        return attrs




class AccountDeleteRequestSerializer(serializers.Serializer):
    confirm = serializers.BooleanField()
    current_password = serializers.CharField(required=False, allow_blank=True, write_only=True)

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        if not attrs.get("confirm"):
            raise serializers.ValidationError({"confirm": "You must confirm account deletion."})

        # if user has a password, require it (extra safety)
        if user and user.has_usable_password():
            pw = (attrs.get("current_password") or "").strip()
            if not pw:
                raise serializers.ValidationError({"current_password": "This field is required."})

            authed = authenticate(username=user.username, password=pw)
            if not authed:
                raise serializers.ValidationError({"current_password": "Password is incorrect."})

        return attrs


class AccountDeleteCancelSerializer(serializers.Serializer):
    confirm = serializers.BooleanField()

    def validate(self, attrs):
        if not attrs.get("confirm"):
            raise serializers.ValidationError({"confirm": "You must confirm cancellation."})
        return attrs










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

    @extend_schema_field(OpenApiTypes.URI)
    def get_reviewer_avatar(self, obj) -> Optional[str]:
        reviewer = getattr(obj, "reviewer", None) or getattr(obj, "reviewer_user", None)
        if not reviewer:
            return None

        profile = getattr(reviewer, "profile", None)
        avatar = getattr(profile, "avatar", None) if profile else None
        if not avatar:
            return None

        request = self.context.get("request")
        url = avatar.url
        if request is not None:
            return request.build_absolute_uri(url)
        return url


class ProfilePageSerializer(serializers.Serializer):
        # header/user
        id = serializers.IntegerField()
        email = serializers.EmailField()
        username = serializers.CharField()
        date_joined = serializers.DateTimeField()

        # profile fields
        avatar = serializers.URLField(allow_blank=True, allow_null=True, required=False)
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


class MessageCreateSerializer(serializers.Serializer):
    body = serializers.CharField(allow_blank=False, trim_whitespace=True)

    def validate_body(self, value):
        value = sanitize_plain_text(value, max_len=5000)
        if not value:
            raise serializers.ValidationError("Message body cannot be empty.")
        return value

    def create(self, validated_data):
        return Message.objects.create(**validated_data)



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

    def validate_name(self, value):
        value = normalise_name(value)
        return validate_person_name(value)

    def validate_email(self, value):
        return normalise_email(value)

    def validate_subject(self, value):
        value = sanitize_plain_text(value, max_len=200)
        if not value:
            raise serializers.ValidationError("Subject is required.")
        return value

    def validate_message(self, value):
        value = sanitize_plain_text(value, max_len=5000)
        if not value:
            raise serializers.ValidationError("Message is required.")
        return value


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
            from propertylist_app.services.image import (
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


class AvatarUploadResponseSerializer(serializers.Serializer):
    avatar = serializers.URLField(allow_null=True)


class SavedCardSerializer(serializers.Serializer):
    id = serializers.CharField()
    brand = serializers.CharField(allow_null=True, required=False)
    last4 = serializers.CharField(allow_null=True, required=False)
    exp_month = serializers.IntegerField(allow_null=True, required=False)
    exp_year = serializers.IntegerField(allow_null=True, required=False)


class SavedCardsListResponseSerializer(serializers.Serializer):
    cards = SavedCardSerializer(many=True)


class DetailResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


class SetupIntentResponseSerializer(serializers.Serializer):
    clientSecret = serializers.CharField()
    publishableKey = serializers.CharField()


class NotificationMarkReadResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()


class NotificationMarkAllReadResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()


class ThreadRestoreResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    in_bin = serializers.BooleanField()


class ThreadStateResponseSerializer(serializers.Serializer):
    thread = serializers.IntegerField()
    label = serializers.CharField(allow_null=True, required=False)
    in_bin = serializers.BooleanField()


class OpsTopCategorySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    room_count = serializers.IntegerField()


class OpsStatsResponseSerializer(serializers.Serializer):
    total_rooms = serializers.IntegerField()
    active_rooms = serializers.IntegerField()
    hidden_rooms = serializers.IntegerField()
    deleted_rooms = serializers.IntegerField()
    total_users = serializers.IntegerField(allow_null=True)
    bookings_7d = serializers.IntegerField()
    bookings_30d = serializers.IntegerField()
    upcoming_viewings = serializers.IntegerField()
    payments_30d_count = serializers.IntegerField()
    payments_30d_sum_gbp = serializers.FloatField()
    messages_7d = serializers.IntegerField()
    threads_total = serializers.IntegerField()
    reports_open = serializers.IntegerField()
    reports_in_review = serializers.IntegerField()
    top_categories = OpsTopCategorySerializer(many=True)


class StripeCheckoutSessionCreateRequestSerializer(serializers.Serializer):
    payment_method_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional saved Stripe PaymentMethod ID for future use."
    )


class StripeCheckoutRedirectDataSerializer(serializers.Serializer):
    checkout_url = serializers.URLField()
    session_id = serializers.CharField(allow_null=True)


class StripeCheckoutRedirectResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    data = StripeCheckoutRedirectDataSerializer()

class RoomPhotoUploadRequestSerializer(serializers.Serializer):
    image = serializers.ImageField(required=True)


class AvatarUploadRequestSerializer(serializers.Serializer):
    avatar = serializers.ImageField(required=True)


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


    @extend_schema_field(MessageSerializer(allow_null=True))
    def get_last_message(self, obj):
        prefetched_messages = getattr(obj, "_prefetched_objects_cache", {}).get("messages")

        if prefetched_messages is not None:
            msg = max(prefetched_messages, key=lambda m: m.created, default=None)
        else:
            msg = obj.messages.order_by("-created").first()

        return MessageSerializer(msg).data if msg else None

    @extend_schema_field(serializers.IntegerField())
    def get_unread_count(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return 0
        if hasattr(obj, "unread_count"):
            return obj.unread_count

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

    @extend_schema_field(serializers.CharField(allow_null=True, required=False))
    def get_label(self, obj):
        st = self._get_state_for_user(obj)
        if not st or not st.label:
            return None
        return st.label

    @extend_schema_field(serializers.BooleanField())
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



#  INSERT: simple request serializers for thread actions (Spectacular needs these)

class ThreadSetLabelRequestSerializer(serializers.Serializer):
    label = serializers.ChoiceField(
        choices=[
            "viewing_scheduled",
            "viewing_done",
            "good_fit",
            "unsure",
            "not_a_fit",
            "paperwork_pending",
            "no_status",  # clears label
        ]
    )


class ThreadMoveToBinRequestSerializer(serializers.Serializer):
    in_bin = serializers.BooleanField()


class ThreadMarkReadRequestSerializer(serializers.Serializer):
    is_read = serializers.BooleanField(default=True)




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


class BookingCreateRequestSerializer(serializers.Serializer):
    room = serializers.IntegerField(required=False)
    slot = serializers.IntegerField(required=False)
    start = serializers.DateTimeField(required=False)
    end = serializers.DateTimeField(required=False)

    def create(self, validated_data):
        return Booking.objects.create(**validated_data)


class BookingResponseEnvelopeSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    data = BookingSerializer()


class AvailabilitySlotSerializer(serializers.ModelSerializer):
    is_full = serializers.SerializerMethodField()

    class Meta:
        model = AvailabilitySlot
        fields = ["id", "room", "start", "end", "max_bookings", "is_full"]
        read_only_fields = ["room", "is_full"]

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_full(self, obj) -> bool:
            return bool(obj.is_full)



class StripeSuccessDataSerializer(serializers.Serializer):
    detail = serializers.CharField()
    session_id = serializers.CharField(required=False, allow_null=True)
    payment_id = serializers.CharField(required=False, allow_null=True)

class StripeCancelDataSerializer(serializers.Serializer):
    detail = serializers.CharField()
    payment_id = serializers.CharField(required=False, allow_null=True)

class StripeSuccessResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    data = StripeSuccessDataSerializer()

class StripeCancelResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    data = StripeCancelDataSerializer()



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




class PaymentTransactionListSerializer(serializers.ModelSerializer):
    listing_title = serializers.CharField(source="room.title", read_only=True)
    transaction_id = serializers.CharField(source="stripe_payment_intent_id", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "listing_title",
            "transaction_id",
            "status",
            "amount",
            "currency",
            "created_at",
        ]

class WebhookAckSerializer(serializers.Serializer):
    ok = serializers.BooleanField(required=False)
    detail = serializers.CharField(required=False)


class StripeWebhookEventRequestSerializer(serializers.Serializer):
    id = serializers.CharField(required=False)
    type = serializers.CharField(required=False)
    created = serializers.IntegerField(required=False)
    livemode = serializers.BooleanField(required=False)
    data = serializers.JSONField(required=False)
    object = serializers.CharField(required=False)


class StripeWebhookAckDataSerializer(serializers.Serializer):
    detail = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    event_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    event_type = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    payment_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class StripeWebhookAckResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    data = StripeWebhookAckDataSerializer()


class StripeWebhookErrorResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


class PaymentTransactionDetailSerializer(serializers.ModelSerializer):
    listing_title = serializers.CharField(source="room.title", read_only=True)
    transaction_id = serializers.CharField(source="stripe_payment_intent_id", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "listing_title",
            "transaction_id",
            "status",
            "amount",
            "currency",
            "created_at",
            "stripe_checkout_session_id",
        ]




class NotificationSerializer(serializers.ModelSerializer):
    deep_link = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "type",
            "title",
            "body",
            "thread",
            "message",
            "target_type",
            "target_id",
            "deep_link",
            "is_read",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.STR)
    def get_deep_link(self, obj) -> str:
        """
        Returns app route path only.
        Emails can prepend FRONTEND_BASE_URL.
        Mobile app uses this path for navigation.
        """

        # 1) Message thread notification
        if getattr(obj, "thread_id", None):
            return f"/app/threads/{obj.thread_id}"

        # 2) Generic targets
        if getattr(obj, "target_type", None) and getattr(obj, "target_id", None):
            t = obj.target_type

            if t == "booking":
                return f"/app/bookings/{obj.target_id}"

            if t == "tenancy":
                return f"/app/tenancies/{obj.target_id}"

            if t == "tenancy_review":
                return f"/app/tenancies/{obj.target_id}/reviews"

            if t == "tenancy_extension":
                return f"/app/tenancies/{obj.target_id}?tab=extension"

            if t == "still_living_check":
                return f"/app/tenancies/{obj.target_id}?tab=still-living"

        # fallback
        return "/app/inbox"


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

    # serializers.py

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

        # Policy: reporting your own room
        # - allowed only for reasons: appeal, spam
        # - blocked for abuse (and anything else)
        if attrs["target_type"] == "room":
            request = self.context.get("request")
            if request and request.user and request.user.is_authenticated:
                room = Room.objects.filter(pk=attrs["object_id"]).first()

                # NEW: policy guard â€” you cannot file an appeal for a room that is already active
                # Reason: appeals are meant for hidden/removed listings; appealing an active listing is meaningless noise.
                reason = (attrs.get("reason") or "").strip().lower()
                if room and reason == "appeal" and getattr(room, "status", None) == "active":
                    raise serializers.ValidationError(
                        {"reason": "You cannot file an appeal for an active room."}
                    )

                if room and room.property_owner_id == request.user.id:
                    reason = (attrs.get("reason") or "").strip().lower()
                    allowed_self_reasons = {"appeal", "spam"}
                    if reason not in allowed_self_reasons:
                        raise serializers.ValidationError(
                            {"object_id": "You cannot report your own room."}
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


class PrivacyPreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = (
            "read_receipts_enabled",
            "allow_search_indexing_default",
            "preferred_language",
        )


        # And ensure it's included in Meta.fields, e.g.
        # fields = ("read_receipts_enabled", "allow_search_indexing_default", "preferred_language", ...)



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
    confirm = serializers.BooleanField()


class OnboardingCompleteSerializer(serializers.Serializer):
    confirm = serializers.BooleanField()



class PhoneOTPStartSerializer(serializers.Serializer):
    phone = serializers.CharField()

    def validate_phone(self, value):
        v = normalise_phone(value)
        if v == "":
            raise serializers.ValidationError("Phone number is required.")
        if len(v.replace("+", "")) < 8:
            raise serializers.ValidationError("Phone number looks too short.")
        return v


class PhoneOTPVerifySerializer(serializers.Serializer):
    phone = serializers.CharField()
    code = serializers.CharField()

    def validate_phone(self, value):
        v = normalise_phone(value)
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



class BookingPreflightRequestSerializer(serializers.Serializer):
    room = serializers.IntegerField()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()

class BookingPreflightResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


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


class ProviderWebhookRequestSerializer(serializers.Serializer):
    payload = serializers.JSONField()

class ProviderWebhookResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


class ChangePasswordRequestSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_password = serializers.CharField()
    confirm_password = serializers.CharField()

class CreatePasswordRequestSerializer(serializers.Serializer):
    new_password = serializers.CharField()
    confirm_password = serializers.CharField()


class ChangeEmailRequestSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_email = serializers.EmailField()

    def validate_new_email(self, value):
        return normalise_email(value)


class LogoutRequestSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class LogoutDataSerializer(serializers.Serializer):
    detail = serializers.CharField()


class LogoutResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    data = LogoutDataSerializer()

