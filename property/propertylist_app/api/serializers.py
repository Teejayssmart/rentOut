from django.contrib.auth import get_user_model, password_validation,authenticate
User = get_user_model()
from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType
import re
from django.db.models import Q
from dateutil.relativedelta import relativedelta
from datetime import date, datetime, time, timedelta
from datetime import date as _date  # add if not already present
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.shortcuts import get_object_or_404
from django.db import transaction
from django.conf import settings

from typing import Optional, Any, Dict, List
from drf_spectacular.types import OpenApiTypes


from drf_spectacular.utils import extend_schema_field
from propertylist_app.models import Room, Booking, Tenancy  # ensure Booking + Tenancy imported
from propertylist_app.models import (
    Room, RoomCategorie, Review, UserProfile, RoomImage,
    SavedRoom, MessageThread, Message, Booking,
    AvailabilitySlot, Payment, Report, Notification, EmailOTP,
    MessageThreadState, ContactMessage,PhoneOTP,Tenancy,LandlordVerificationRequest,
    IdentityVerificationRequest,

)
from propertylist_app.validators import (
    validate_person_name, validate_age_18_plus, validate_avatar_image,
    normalize_uk_postcode, validate_listing_title, sanitize_html_description,
    validate_price, validate_available_from, validate_choice,
    validate_listing_photos, sanitize_search_text, validate_numeric_range,
    validate_radius_miles, validate_pagination, validate_ordering,
    normalise_price, normalise_phone, normalise_name, normalise_email,
    sanitize_plain_text, validate_plain_text,
    assert_not_duplicate_listing, assert_no_duplicate_files,
    enforce_user_caps,
    )
from propertylist_app.services.geo import geocode_postcode_cached

from django.utils import timezone
from django.core import mail
from django.utils.crypto import get_random_string
import re


from notifications.services import send_security_code_email




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
    review_location = serializers.SerializerMethodField()
    display_summary = serializers.SerializerMethodField()
    positive_labels = serializers.SerializerMethodField()
    negative_labels = serializers.SerializerMethodField()
    room_id = serializers.SerializerMethodField()
    room_title = serializers.SerializerMethodField()
    reviewer_name = serializers.SerializerMethodField()
    reviewer_username = serializers.SerializerMethodField()
    reviewer_avatar = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = [
            "id",
            "tenancy",
            "reviewer",
            "reviewer_name",
            "reviewer_username",
            "reviewer_avatar",
            "reviewee",
            "role",
            "review_flags",
            "overall_rating",
            "notes",
            "display_summary",
            "review_mode",
            "review_location",
            "positive_labels",
            "negative_labels",
            "submitted_at",
            "reveal_at",
            "active",
            "room_id",
            "room_title",
        ]
        read_only_fields = fields

    # --- keep the same flag sets as models.py save() logic (must match exactly) ---
    TENANT_TO_LANDLORD_POS = {
        "responsive",
        "maintenance_good",
        "accurate_listing",
        "respectful_fair",
    }
    TENANT_TO_LANDLORD_NEG = {
        "unresponsive",
        "maintenance_poor",
        "misleading_listing",
        "unfair_treatment",
    }

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
    def get_reviewer_name(self, obj) -> str:
        """
        Human-friendly reviewer name.

        Prefer first_name + last_name where available.
        Fall back to username if no real name is stored.
        """
        reviewer = obj.reviewer

        full_name = reviewer.get_full_name().strip()
        if full_name:
            return full_name

        return reviewer.username or ""

    @extend_schema_field(OpenApiTypes.STR)
    def get_reviewer_username(self, obj) -> str:
        reviewer = obj.reviewer
        return reviewer.username or ""

    @extend_schema_field(OpenApiTypes.STR)
    def get_reviewer_avatar(self, obj) -> str:
        """
        Return the reviewer's profile avatar URL when available.
        """
        try:
            profile = obj.reviewer.profile
        except (AttributeError, UserProfile.DoesNotExist):
            return ""

        avatar = profile.avatar

        if not avatar:
            return ""

        try:
            url = avatar.url
        except (AttributeError, ValueError):
            return ""

        request = self.context.get("request")
        if request is not None:
            return request.build_absolute_uri(url)

        return url
    
    
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

        return [
            self.FLAG_LABELS.get(k, k)
            for k in sorted(pos)
        ]
        
        
    @extend_schema_field(OpenApiTypes.INT)
    def get_room_id(self, obj):
        tenancy = getattr(obj, "tenancy", None)
        return getattr(tenancy, "room_id", None)

    
    @extend_schema_field(OpenApiTypes.STR)
    def get_review_location(self, obj) -> str:
        tenancy = getattr(obj, "tenancy", None)
        room = getattr(tenancy, "room", None)

        if not room:
            return ""

        location = (getattr(room, "location", "") or "").strip()
        if not location:
            return ""

        import re

        compact = location.upper().replace(" ", "")

        match = re.search(
            r"([A-Z]{1,2}\d[A-Z\d]?)\d[A-Z]{2}$",
            compact,
        )

        if not match:
            return ""

        return f"{match.group(1)} area"



    @extend_schema_field(OpenApiTypes.STR)
    def get_room_title(self, obj) -> str:
        tenancy = getattr(obj, "tenancy", None)
        room = getattr(tenancy, "room", None)
        return getattr(room, "title", "") or ""    
        

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_negative_labels(self, obj) -> List[str]:
        flags = set(obj.review_flags or [])

        if obj.role == Review.ROLE_TENANT_TO_LANDLORD:
            neg = flags.intersection(self.TENANT_TO_LANDLORD_NEG)
        else:
            neg = flags.intersection(self.LANDLORD_TO_TENANT_NEG)

        return [
            self.FLAG_LABELS.get(k, k)
            for k in sorted(neg)
        ]

    @extend_schema_field(OpenApiTypes.STR)
    def get_display_summary(self, obj) -> str:
        """
        Hard rule:
        - If notes exist (text option), return notes EXACTLY as stored.
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
            parts.append(
                "However: " + ", ".join(neg)
            )

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
    TENANT_TO_LANDLORD_FLAGS = {
    "responsive",
    "maintenance_good",
    "accurate_listing",
    "respectful_fair",
    "unresponsive",
    "maintenance_poor",
    "misleading_listing",
    "unfair_treatment",
    }

    LANDLORD_TO_TENANT_FLAGS = {
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

        if tenancy.status != Tenancy.STATUS_ENDED:
            raise serializers.ValidationError(
                "A review can only be left after the tenancy has ended."
            )

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

        # Review attributes are role-specific.
        # A tenant reviews landlord behaviour; a landlord reviews tenant behaviour.
        if role == Review.ROLE_TENANT_TO_LANDLORD:
            allowed_flags = self.TENANT_TO_LANDLORD_FLAGS
        else:
            allowed_flags = self.LANDLORD_TO_TENANT_FLAGS

        invalid_flags = [
            flag
            for flag in flags
            if flag not in allowed_flags
        ]

        if invalid_flags:
            raise serializers.ValidationError(
                {
                    "review_flags": [
                        (
                            f"Invalid review flag(s) for {role}: "
                            f"{', '.join(sorted(set(invalid_flags)))}"
                        )
                    ]
                }
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

        # Tenancy reviews are double-blind until reveal_at.
        # The reveal sweep activates them and then queues the
        # tenancy.review_revealed notification/email.
        validated_data["active"] = False

        return Review.objects.create(**validated_data)


class StillLivingConfirmResponseSerializer(serializers.Serializer):
    tenancy_id = serializers.IntegerField()
    landlord_confirmed = serializers.BooleanField()
    tenant_confirmed = serializers.BooleanField()
    still_living_confirmed_at = serializers.DateTimeField(allow_null=True)


class TenancyExtensionCreateSerializer(serializers.Serializer):
    proposed_start_date = serializers.DateField()

    proposed_duration_months = serializers.IntegerField(
        min_value=1,
        max_value=24,
    )

    def validate_proposed_start_date(self, value):
        if value < timezone.localdate():
            raise serializers.ValidationError(
                "The renewal start date cannot be in the past."
            )

        return value


class TenancyExtensionRespondSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=[
            "accept",
            "reject",
        ]
    )


class TenancyExtensionResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    tenancy_id = serializers.IntegerField()
    proposed_by_user_id = serializers.IntegerField()
    proposed_start_date = serializers.DateField()
    proposed_duration_months = serializers.IntegerField()
    status = serializers.CharField()
    responded_at = serializers.DateTimeField(
        allow_null=True,
    )
    created_at = serializers.DateTimeField()

class TenancyExtensionHistoryItemSerializer(
    serializers.Serializer
):
    id = serializers.IntegerField()
    tenancy_id = serializers.IntegerField()

    proposed_by_user_id = serializers.IntegerField()
    proposed_by_name = serializers.CharField(
        allow_blank=True,
    )
    proposed_by_role = serializers.ChoiceField(
        choices=[
            "landlord",
            "tenant",
        ]
    )

    proposed_start_date = serializers.DateField(
        allow_null=True,
    )
    proposed_duration_months = serializers.IntegerField()

    status = serializers.CharField()

    responded_at = serializers.DateTimeField(
        allow_null=True,
    )
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
        completion_cutoff = timezone.now() - timedelta(minutes=10)

        return Booking.objects.filter(
            room=room,
            user=user,
            is_deleted=False,
            status=Booking.STATUS_ACTIVE,
            canceled_at__isnull=True,
            start__lte=completion_cutoff,
        ).exists()

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user

        room = (
            Room.objects.select_related("property_owner")
            .filter(id=attrs["room_id"], is_deleted=False)
            .first()
        )

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

        existing_tenancies = list(
            Tenancy.objects
            .select_for_update()
            .filter(
                room=room,
                tenant=tenant,
            )
            .order_by("-created_at")
        )

        # Only one live tenancy submission may exist for the same
        # room, landlord and tenant at any time.
        live_statuses = {
            Tenancy.STATUS_PROPOSED,
            Tenancy.STATUS_CONFIRMED,
            Tenancy.STATUS_ACTIVE,
        }

        live_tenancy = next(
            (
                existing
                for existing in existing_tenancies
                if existing.status in live_statuses
            ),
            None,
        )

        if live_tenancy is not None:
            other_party = (
                "tenant"
                if user.id == landlord.id
                else "landlord"
            )

            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        (
                            f"Your {other_party} has already created the tenancy "
                            "information for this room. Please review the existing "
                            "tenancy information instead."
                        )
                    ]
                }
            )

        # A tenant-created claim that expired or was rejected must not
        # be repeatedly resubmitted by the tenant.
        #
        # The landlord may, however, create fresh tenancy information
        # for the same tenant if the tenancy is genuine.
        expired_or_rejected_tenant_claim = next(
            (
                existing
                for existing in existing_tenancies
                if (
                    existing.status == Tenancy.STATUS_CANCELLED
                    and existing.proposed_by_id == tenant.id
                )
            ),
            None,
        )

        if (
            user.id == tenant.id
            and expired_or_rejected_tenant_claim is not None
        ):
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        (
                            "Your previous tenancy submission for this room "
                            "has expired or was not confirmed. Please contact "
                            "the landlord and ask them to submit the tenancy "
                            "information."
                        )
                    ]
                }
            )

        # The party submitting the original tenancy information
        # automatically confirms their own side.
        landlord_confirmed_at = now if user.id == landlord.id else None
        tenant_confirmed_at = now if user.id == tenant.id else None

        tenancy = Tenancy.objects.create(
            room=room,
            landlord=landlord,
            tenant=tenant,
            proposed_by=user,
            move_in_date=validated_data["move_in_date"],
            duration_months=validated_data["duration_months"],
            landlord_confirmed_at=landlord_confirmed_at,
            tenant_confirmed_at=tenant_confirmed_at,
            status=Tenancy.STATUS_PROPOSED,
        )

        # The landlord owns the listing, so a landlord-created tenancy
        # immediately removes the room from availability.
        #
        # A tenant-created tenancy claim must first be verified by the
        # landlord, so the room remains in its existing availability state.
        if user.id == landlord.id and room.is_available:
            room.is_available = False
            room.save(update_fields=["is_available", "updated_at"])

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
            # Once the one permitted correction has been used,
            # neither party may edit the tenancy information again.
            if tenancy.tenant_has_edited:
                raise serializers.ValidationError(
                    {
                        "action": (
                            "Further changes are not allowed because the one "
                            "permitted correction has already been used."
                        )
                    }
                )

            # Only the party reviewing the current proposal may edit it.
            # The person who submitted the current proposal cannot edit
            # their own tenancy information.
            if user.id == tenancy.proposed_by_id:
                raise serializers.ValidationError(
                    {
                        "action": (
                            "You submitted the current tenancy information. "
                            "The other party must review it before changes "
                            "can be proposed."
                        )
                    }
                )

            if (
                "move_in_date" not in attrs
                or "duration_months" not in attrs
            ):
                raise serializers.ValidationError(
                    {
                        "non_field_errors": (
                            "move_in_date and duration_months are required "
                            "for propose_changes."
                        )
                    }
                )

            if attrs["move_in_date"] < timezone.localdate():
                raise serializers.ValidationError(
                    {
                        "move_in_date": (
                            "Move-in date cannot be in the past."
                        )
                    }
                )

        if action == "cancel":
            # "Not my tenant" is only available to the landlord
            # when the tenant submitted the initial tenancy claim.
            if not (
                user.id == tenancy.landlord_id
                and tenancy.proposed_by_id == tenancy.tenant_id
            ):
                raise serializers.ValidationError(
                    {
                        "action": (
                            "Only the landlord can reject tenancy information "
                            "submitted first by the tenant."
                        )
                    }
                )
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
            # tenancy.review_open_at = timezone.make_aware(
            #     timezone.datetime.combine(end_date, timezone.datetime.min.time())
            # ) + timedelta(days=7)

            # Temporary frontend testing rule: review opens 30 minutes after tenancy ends.
            tenancy.review_open_at = timezone.make_aware(
                timezone.datetime.combine(end_date, timezone.datetime.min.time())
            ) + timedelta(minutes=10)

            # optional deadline: end + 60 days (safe default)
            tenancy.review_deadline_at = tenancy.review_open_at + timedelta(days=60)

            # # still living check: end - 7 days
            # tenancy.still_living_check_at = timezone.make_aware(
            #     timezone.datetime.combine(end_date, timezone.datetime.min.time())
            # ) - timedelta(days=7)


            # TEMPORARY QA RULE:
            # Timer 2 becomes due 10 minutes after both parties confirm
            # the tenancy information.
            #
            # Production must revert to 7 days before the tenancy end date.
            tenancy.still_living_check_at = now + timedelta(minutes=10)




        if action == "cancel":
            # Landlord rejected a tenant-created tenancy claim.
            # The room availability is deliberately not changed here:
            # tenant-created claims never take the listing offline.
            tenancy.status = STATUS_CANCELLED
            tenancy.review_open_at = None
            tenancy.review_deadline_at = None
            tenancy.still_living_check_at = None
            tenancy.still_living_confirmed_at = None
            tenancy.save()

            return tenancy



        if action == "propose_changes":
            tenancy.move_in_date = self.validated_data["move_in_date"]
            tenancy.duration_months = self.validated_data["duration_months"]
            tenancy.proposed_by = user

            # The one permitted correction becomes the final tenancy
            # information. No further Agree/Edit cycle is required.
            tenancy.landlord_confirmed_at = now
            tenancy.tenant_confirmed_at = now
            tenancy.tenant_has_edited = True

            today = timezone.localdate()
            tenancy.status = (
                STATUS_ACTIVE
                if tenancy.move_in_date <= today
                else STATUS_CONFIRMED
            )

            # Temporary QA schedule:
            # Timer 2 becomes due 10 minutes after this correction.
            _set_schedule_fields()
            tenancy.still_living_confirmed_at = None

            room = tenancy.room
            if room.is_available:
                room.is_available = False
                room.save(update_fields=["is_available", "updated_at"])

            tenancy.save()
            return tenancy

        # action == "confirm"
        if user.id == tenancy.landlord_id and tenancy.landlord_confirmed_at is None:
            tenancy.landlord_confirmed_at = now
        if user.id == tenancy.tenant_id and tenancy.tenant_confirmed_at is None:
            tenancy.tenant_confirmed_at = now

        # if both confirmed â†’ lock schedule + set status
        # If both parties have confirmed, lock the tenancy schedule and
        # remove the room from active availability.
        if tenancy.landlord_confirmed_at and tenancy.tenant_confirmed_at:
            today = timezone.localdate()
            tenancy.status = (
                STATUS_ACTIVE
                if tenancy.move_in_date <= today
                else STATUS_CONFIRMED
            )
            _set_schedule_fields()

            room = tenancy.room
            if room.is_available:
                room.is_available = False
                room.save(update_fields=["is_available", "updated_at"])
        else:
            tenancy.status = STATUS_PROPOSED

        tenancy.save()
        return tenancy



class TenancyDetailSerializer(serializers.ModelSerializer):
    can_leave_review = serializers.SerializerMethodField()
    review_button_reason = serializers.SerializerMethodField()
    profile_image = serializers.SerializerMethodField()
    tenant_name = serializers.SerializerMethodField()
    landlord_name = serializers.SerializerMethodField()

    can_agree = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    available_actions = serializers.SerializerMethodField()
    tenancy_action_reason = serializers.SerializerMethodField()

    class Meta:
        model = Tenancy
        fields = [
                "id",
                "room",
                "landlord",
                "landlord_name",
                "tenant",
                "tenant_name",
                "profile_image",
                "proposed_by",
                "move_in_date",
                "duration_months",
                "landlord_confirmed_at",
                "tenant_confirmed_at",
                "status",
                "can_agree",
                "can_edit",
                "available_actions",
                "tenancy_action_reason",
                "review_open_at",
                "review_deadline_at",
                "can_leave_review",
                "review_button_reason",
                "still_living_check_at",
                "still_living_confirmed_at",
                "created_at",
                "updated_at",
            ]

        read_only_fields = fields


    @extend_schema_field(OpenApiTypes.STR)
    def get_tenant_name(self, obj):
        tenant = getattr(obj, "tenant", None)

        if tenant is None:
            return None

        full_name = tenant.get_full_name().strip()

        return full_name or tenant.username


    @extend_schema_field(OpenApiTypes.STR)
    def get_landlord_name(self, obj):
        landlord = getattr(obj, "landlord", None)

        if landlord is None:
            return None

        full_name = landlord.get_full_name().strip()

        return full_name or landlord.username




    @extend_schema_field(OpenApiTypes.URI)
    def get_profile_image(self, obj):
        tenant = getattr(obj, "tenant", None)
        profile = getattr(tenant, "profile", None) if tenant else None
        avatar = getattr(profile, "avatar", None) if profile else None

        if not avatar:
            return None

        try:
            url = avatar.url
        except (ValueError, AttributeError):
            return None

        request = self.context.get("request")
        if request is not None:
            return request.build_absolute_uri(url)

        return url



    def _get_tenancy_action_permissions(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        if not user or not user.is_authenticated:
            return {
                "can_agree": False,
                "can_edit": False,
                "available_actions": [],
                "reason": "You must be signed in to respond.",
            }

        if user.id not in {obj.landlord_id, obj.tenant_id}:
            return {
                "can_agree": False,
                "can_edit": False,
                "available_actions": [],
                "reason": "You are not part of this tenancy.",
            }

        if obj.status != Tenancy.STATUS_PROPOSED:
            return {
                "can_agree": False,
                "can_edit": False,
                "available_actions": [],
                "reason": "This tenancy information is no longer awaiting review.",
            }

        # The person who submitted the current terms must wait for
        # the other party to review them.
        if user.id == obj.proposed_by_id:
            return {
                "can_agree": False,
                "can_edit": False,
                "available_actions": [],
                "reason": "Waiting for the other party to review the tenancy information.",
            }

        can_edit = not obj.tenant_has_edited

        available_actions = ["confirm"]

        if can_edit:
            available_actions.append("propose_changes")

        # When the tenant submitted the tenancy information first,
        # the landlord may reject the claim if the room was not
        # actually rented to that tenant.
        landlord_reviewing_tenant_claim = (
            user.id == obj.landlord_id
            and obj.proposed_by_id == obj.tenant_id
        )

        if landlord_reviewing_tenant_claim:
            available_actions.append("cancel")

        if landlord_reviewing_tenant_claim and can_edit:
            reason = (
                "Confirm that you actually rented this room to the tenant. "
                "You can agree, correct the information once, or reject the claim."
            )
        elif landlord_reviewing_tenant_claim:
            reason = (
                "Confirm that you actually rented this room to the tenant. "
                "You can agree or reject the claim."
            )
        elif can_edit:
            reason = (
                "You can agree to the tenancy information or correct it once."
            )
        else:
            reason = (
                "The one-time correction has already been used. "
                "You can now agree to the tenancy information."
            )

        return {
            "can_agree": True,
            "can_edit": can_edit,
            "available_actions": available_actions,
            "reason": reason,
        }


    @extend_schema_field(OpenApiTypes.BOOL)
    def get_can_agree(self, obj):
        return self._get_tenancy_action_permissions(obj)["can_agree"]


    @extend_schema_field(OpenApiTypes.BOOL)
    def get_can_edit(self, obj):
        return self._get_tenancy_action_permissions(obj)["can_edit"]


    @extend_schema_field(
        serializers.ListField(
            child=serializers.CharField(),
        )
    )
    def get_available_actions(self, obj):
        return self._get_tenancy_action_permissions(obj)["available_actions"]


    @extend_schema_field(OpenApiTypes.STR)
    def get_tenancy_action_reason(self, obj):
        return self._get_tenancy_action_permissions(obj)["reason"]






    def _get_review_eligibility(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        if not user or not user.is_authenticated:
            return False, "You must be signed in to leave a review."

        if user.id == obj.tenant_id:
            review_role = Review.ROLE_TENANT_TO_LANDLORD
        elif user.id == obj.landlord_id:
            review_role = Review.ROLE_LANDLORD_TO_TENANT
        else:
            return False, "You are not part of this tenancy."

        if obj.status != "ended":
            return False, "A review can only be left after the tenancy has ended."

        if Review.objects.filter(
            tenancy=obj,
            role=review_role,
        ).exists():
            return False, "You have already submitted a review for this tenancy."

        now = timezone.now()

        if not obj.review_open_at:
            return False, "Review window is not open yet."

        if now < obj.review_open_at:
            return False, "Review will be available later."

        if obj.review_deadline_at and now > obj.review_deadline_at:
            return False, "Review window has closed."

        return True, "Review is available."

    def get_can_leave_review(self, obj):
        can_leave_review, _ = self._get_review_eligibility(obj)
        return can_leave_review

    def get_review_button_reason(self, obj):
        _, reason = self._get_review_eligibility(obj)
        return reason

class UserReviewSummarySerializer(serializers.Serializer):
    landlord_count = serializers.IntegerField()
    landlord_average = serializers.FloatField(allow_null=True)

    tenant_count = serializers.IntegerField()
    tenant_average = serializers.FloatField(allow_null=True)

    total_reviews_count = serializers.IntegerField()
    overall_rating_average = serializers.FloatField(allow_null=True)


class CreateViewingBookingSerializer(serializers.Serializer):
    slot_id = serializers.IntegerField(required=False)
    room_id = serializers.IntegerField(required=False)
    start = serializers.DateTimeField(required=False)




class RoomPhotoResponseSerializer(serializers.Serializer):
    """
    Schema and response structure for a photo embedded in RoomSerializer.
    """

    id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
    )
    image = serializers.URLField(
        read_only=True,
        allow_null=True,
    )
    url = serializers.URLField(
        read_only=True,
        allow_null=True,
    )
    original_image = serializers.URLField(
        read_only=True,
        allow_null=True,
    )

    status = serializers.CharField(
        read_only=True,
    )
    is_main = serializers.BooleanField(
        read_only=True,
    )







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

    cover_photo = serializers.PrimaryKeyRelatedField(
    queryset=RoomImage.objects.all(),
    required=False,
    allow_null=True,
    write_only=True,
    )
    avg_rating = serializers.SerializerMethodField()
    is_saved = serializers.SerializerMethodField(read_only=True)
    distance_miles = serializers.SerializerMethodField(read_only=True)
    allow_search_indexing_effective = serializers.SerializerMethodField(read_only=True)

    # extra fields for Find a Room cards
    owner_name = serializers.SerializerMethodField(read_only=True)
    owner_username = serializers.SerializerMethodField(read_only=True)
    owner_avatar = serializers.SerializerMethodField(read_only=True)
    cover_image = serializers.SerializerMethodField(read_only=True)
    other_images = serializers.SerializerMethodField(read_only=True)
    image_status = serializers.SerializerMethodField(read_only=True)
    listing_state = serializers.SerializerMethodField(read_only=True)
    landlord_type = serializers.SerializerMethodField(read_only=True)
    landlord_type_label = serializers.SerializerMethodField(read_only=True)
    landlord_verified = serializers.SerializerMethodField(read_only=True)



    # Amenity keys matching the Step 2/5 chips
    AMENITY_CHOICES = {
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
        "smoke_alarm",
        "first_aid_kit",
        "security_system",
        "carbon_monoxide",
        "fire_extinguisher",
        "disabled_accessible",
        "must_climb_stairs",
    }





    def validate_price_per_month(self, value):
        try:
            value = normalise_price(value)
        except serializers.ValidationError as exc:
            raise serializers.ValidationError(exc.detail)

        if value < 0:
            raise serializers.ValidationError("Monthly rent cannot be negative.")

        return validate_price(value, min_val=50.0, max_val=20000.0)


    def validate_security_deposit(self, value):
        try:
            value = normalise_price(value)
        except serializers.ValidationError as exc:
            raise serializers.ValidationError(exc.detail)

        if value < 0:
            raise serializers.ValidationError("Security deposit cannot be negative.")

        return validate_price(value, min_val=0.0, max_val=50000.0)



    def validate_view_available_custom_dates(self, value):
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
                    parsed = datetime.strptime(item, "%Y-%m-%d")
                except ValueError:
                    raise serializers.ValidationError(
                        "Invalid date format. Use YYYY-MM-DD."
                    )

                normalised.append(parsed.date().isoformat())
                continue

            raise serializers.ValidationError(
                "Invalid date format. Use YYYY-MM-DD."
            )

        return normalised



    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_avg_rating(self, obj):
        value = getattr(obj, "avg_rating", 0) or 0
        return round(float(value), 1)


    def validate(self, attrs):
        attrs = super().validate(attrs)

        price = attrs.get("price_per_month")
        bills_included = attrs.get("bills_included")
        available_from = attrs.get("available_from")

        if self.instance is not None:
            if "price_per_month" not in attrs:
                price = getattr(self.instance, "price_per_month", None)

            if "bills_included" not in attrs:
                bills_included = getattr(self.instance, "bills_included", None)

            if "available_from" not in attrs:
                available_from = getattr(self.instance, "available_from", None)

        if price is not None:
            attrs["price_per_month"] = self.validate_price_per_month(price)

        if available_from is not None:
            try:
                validate_available_from(available_from)
            except serializers.ValidationError as exc:
                raise serializers.ValidationError(
                    {"available_from": exc.detail}
                )

        min_stay = attrs.get("min_stay_months")
        max_stay = attrs.get("max_stay_months")

        if self.instance is not None:
            if "min_stay_months" not in attrs:
                min_stay = getattr(self.instance, "min_stay_months", None)

            if "max_stay_months" not in attrs:
                max_stay = getattr(self.instance, "max_stay_months", None)

        if (
            min_stay is not None
            and max_stay is not None
            and min_stay > max_stay
        ):
            raise serializers.ValidationError(
                {
                    "min_stay_months":
                    "Minimum stay cannot be greater than maximum stay."
                }
            )

        min_age = attrs.get("preferred_flatmate_min_age")
        max_age = attrs.get("preferred_flatmate_max_age")

        if self.instance is not None:
            if "preferred_flatmate_min_age" not in attrs:
                min_age = getattr(self.instance, "preferred_flatmate_min_age", None)

            if "preferred_flatmate_max_age" not in attrs:
                max_age = getattr(self.instance, "preferred_flatmate_max_age", None)

        if (
            min_age is not None
            and max_age is not None
            and min_age > max_age
        ):
            raise serializers.ValidationError(
                {
                    "preferred_flatmate_min_age":
                    "Minimum age cannot be greater than maximum age."
                }
            )

        if bills_included and price is not None and float(price) < 100.0:
            raise serializers.ValidationError(
                {
                    "bills_included":
                    "Bills cannot be included for such a low price."
                }
            )

        mode = attrs.get("view_available_days_mode")
        custom_dates = attrs.get("view_available_custom_dates")

        if self.instance is not None:
            if "view_available_days_mode" not in attrs:
                mode = getattr(self.instance, "view_available_days_mode", "everyday")

            if "view_available_custom_dates" not in attrs:
                custom_dates = getattr(self.instance, "view_available_custom_dates", [])

        if mode == "custom":
            if not custom_dates:
                raise serializers.ValidationError(
                    {
                        "view_available_custom_dates":
                        "Provide at least one date when using custom mode."
                    }
                )
        else:
            attrs["view_available_custom_dates"] = []

        start_time = attrs.get("availability_from_time")
        end_time = attrs.get("availability_to_time")

        if self.instance is not None:
            if "availability_from_time" not in attrs:
                start_time = getattr(self.instance, "availability_from_time", None)

            if "availability_to_time" not in attrs:
                end_time = getattr(self.instance, "availability_to_time", None)

        if start_time and not end_time:
            raise serializers.ValidationError(
                {"availability_to_time": "Please provide an end time as well."}
            )

        if end_time and not start_time:
            raise serializers.ValidationError(
                {"availability_from_time": "Please provide a start time as well."}
            )

        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError(
                {"availability_to_time": "End time must be after start time."}
            )

        cover_photo = attrs.get("cover_photo")

        if cover_photo:
            room = self.instance

            if room and cover_photo.room_id != room.id:
                raise serializers.ValidationError(
                    {
                        "cover_photo":
                        "Selected cover photo does not belong to this listing."
                    }
                )


        return attrs

    preferred_flatmate_min_age = serializers.IntegerField(required=False, allow_null=True)
    preferred_flatmate_max_age = serializers.IntegerField(required=False, allow_null=True)



    class Meta:
        model = Room
        fields = "__all__"
        read_only_fields = (
            "avg_rating",
            "number_rating",
            "paid_until",
            "is_deleted",
            "deleted_at",
        )

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_saved(self, obj) -> bool:
        annotated = getattr(obj, "_is_saved", None)
        if annotated is not None:
            return bool(annotated)

        request = self.context.get("request")
        user = getattr(request, "user", None) if request is not None else None

        if not user or not getattr(user, "is_authenticated", False):
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

    @extend_schema_field(OpenApiTypes.STR)
    def get_owner_username(self, obj) -> str:
        user = getattr(obj, "property_owner", None)
        if not user:
            return ""

        return user.username or ""

    @extend_schema_field(OpenApiTypes.STR)
    def get_owner_avatar(self, obj) -> str:
        user = getattr(obj, "property_owner", None)
        profile = getattr(user, "profile", None) if user else None
        avatar = getattr(profile, "avatar", None)

        if not avatar:
            return ""

        request = self.context.get("request")
        url = avatar.url

        if request is not None:
            return request.build_absolute_uri(url)

        return url



    @extend_schema_field(OpenApiTypes.STR)
    def get_listing_state(self, obj) -> str:
        """
        Returns one of: 'draft', 'active', 'expired', 'hidden', 'rented'.

        'active' means the room is currently live/listed:
        - status == active
        - is_available == True
        - paid_until exists
        - paid_until has not expired
        """
        
        today = date.today()

        # Rented / unavailable always takes priority.
        if not getattr(obj, "is_available", True):
            return "rented"

        # If the queryset annotated a listing_state, reuse it.
        state = getattr(obj, "listing_state", None)
        if state:
            return str(state)

        # Explicit draft status must remain draft.
        if obj.status == "draft":
            return "draft"

        # Never paid / not yet listed.
        if obj.paid_until is None:
            return "draft"

        # Paid period has ended.
        if obj.paid_until < today:
            return "expired"

        # Explicitly unpublished / hidden while payment is still valid.
        if obj.status == "hidden":
            return "hidden"

        # Only explicitly active + available + currently paid is live.
        if obj.status == "active":
            return "active"

        # Any unknown/non-live lifecycle state must not be presented as active.
        return "draft"

    @extend_schema_field(OpenApiTypes.STR)
    def get_landlord_type(self, obj) -> str:
        user = getattr(obj, "property_owner", None)
        profile = getattr(user, "profile", None) if user else None
        return getattr(profile, "role_detail", "") or ""

    @extend_schema_field(OpenApiTypes.STR)
    def get_landlord_type_label(self, obj) -> str:
        value = self.get_landlord_type(obj)

        labels = {
            "live_in_landlord": "Live-in landlord",
            "live_out_landlord": "Live-out landlord",
            "agent_broker": "Agency",
        }

        return labels.get(value, "")

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_landlord_verified(self, obj) -> bool:
        user = getattr(obj, "property_owner", None)
        profile = getattr(user, "profile", None) if user else None
        return bool(getattr(profile, "advertiser_verified", False))



    def _apply_geocode(self, room):
        """
        Populate latitude/longitude from the room location postcode.

        Safe behaviour:
        - silently skips if postcode/geocoding fails
        - never blocks room creation/update
        """
        location = (room.location or "").strip()

        if not location:
            return

        try:
            parts = location.split()

            if len(parts) >= 2 and len(parts[-1]) <= 3:
                postcode = f"{parts[-2]} {parts[-1]}"
            else:
                postcode = parts[-1]

            lat, lon = geocode_postcode_cached(postcode)

            room.latitude = lat
            room.longitude = lon

        except Exception:
            # Do not block listing save if geocoder fails.
            return


    def _sync_availability_slots(self, room):
        """
        Convert landlord-selected viewing availability into consecutive
        30-minute bookable slots.

        Rules:
        - The start time is rounded up to the nearest quarter hour.
        - The end time is rounded down to the nearest quarter hour.
        - Times already on a 00, 15, 30 or 45 minute boundary are unchanged.
        - Each viewing lasts 30 minutes.
        - A slot is created only when its full 30 minutes finishes on or
        before the rounded end time.
        - Recurring modes generate slots for the next 30 calendar days.
        - Custom mode uses only the landlord-selected dates.
        - Existing future slots with active bookings are preserved.

        Example:
        17:13-21:18 becomes a usable window of 17:15-21:15 and creates:

        17:15-17:45
        17:45-18:15
        18:15-18:45
        18:45-19:15
        19:15-19:45
        19:45-20:15
        20:15-20:45
        20:45-21:15

        The next slot, 21:15-21:45, is not created because it would
        finish after the rounded end time of 21:15."""

        def round_up_to_quarter(value):
            """
            Round a time upward to the next 00, 15, 30 or 45 minute boundary.

            Examples:
            09:00 -> 09:00
            09:02 -> 09:15
            09:15 -> 09:15
            09:16 -> 09:30
            09:46 -> 10:00
            """
            total_minutes = (value.hour * 60) + value.minute

            if value.second or value.microsecond:
                total_minutes += 1

            return ((total_minutes + 14) // 15) * 15

        def round_down_to_quarter(value):
            """
            Round a time downward to the previous 00, 15, 30 or 45
            minute boundary.

            Examples:
            09:00 -> 09:00
            09:02 -> 09:00
            09:15 -> 09:15
            09:18 -> 09:15
            09:59 -> 09:45
            """
            total_minutes = (value.hour * 60) + value.minute
            return (total_minutes // 15) * 15

        mode = room.view_available_days_mode
        start_time = room.availability_from_time
        end_time = room.availability_to_time

        valid_modes = {
            "everyday",
            "weekdays",
            "weekends",
            "custom",
        }

        if mode not in valid_modes:
            return

        if not start_time or not end_time:
            return

        slot_minutes = 30
        today = timezone.localdate()

        available_from = getattr(room, "available_from", None)

        # Viewing availability must never begin before the room's advertised
        # available-from date. If that date has already passed, begin today.
        start_date = max(
            today,
            available_from or today,
        )

        desired_dates = []

        if mode == "custom":
            for selected_date in room.view_available_custom_dates or []:
                if isinstance(selected_date, str):
                    try:
                        selected_date = datetime.fromisoformat(
                            selected_date
                        ).date()
                    except (TypeError, ValueError):
                        continue

                if selected_date >= start_date:
                    desired_dates.append(selected_date)

        else:
            # Generate the first valid availability date plus the following
            # 29 calendar days.
            for day_offset in range(30):
                selected_date = start_date + timedelta(days=day_offset)

                if (
                    mode == "weekdays"
                    and selected_date.weekday() >= 5
                ):
                    continue

                if (
                    mode == "weekends"
                    and selected_date.weekday() < 5
                ):
                    continue

                desired_dates.append(selected_date)

        desired_slots = []

        start_minutes = round_up_to_quarter(start_time)
        end_minutes = round_down_to_quarter(end_time)

        # The rounded end is an availability boundary, not a valid slot
        # start by itself. A complete 30-minute viewing must fit inside it.
        if end_minutes <= start_minutes:
            return

        for selected_date in desired_dates:
            day_start = datetime.combine(selected_date, time.min)

            rounded_start = day_start + timedelta(
                minutes=start_minutes
            )

            rounded_end = day_start + timedelta(
                minutes=end_minutes
            )

            if timezone.is_naive(rounded_start):
                rounded_start = timezone.make_aware(
                    rounded_start,
                    timezone.get_current_timezone(),
                )

            if timezone.is_naive(rounded_end):
                rounded_end = timezone.make_aware(
                    rounded_end,
                    timezone.get_current_timezone(),
                )

            current = rounded_start

            while True:
                slot_end = current + timedelta(
                    minutes=slot_minutes
                )

                # A complete viewing must finish on or before the
                # landlord's rounded availability end boundary.
                if slot_end > rounded_end:
                    break

                # Do not create a slot which has already ended.
                if slot_end > timezone.now():
                    desired_slots.append((current, slot_end))

                current = slot_end

        desired_set = set(desired_slots)

        # Remove only future unbooked slots that no longer match the
        # landlord's current availability selection.
        future_slots = AvailabilitySlot.objects.filter(
            room=room,
            end__gt=timezone.now(),
        )

        for slot in future_slots:
            # Never delete a slot referenced by any booking.
            # Booking.slot uses PROTECT, including for old/cancelled bookings.
            has_booking = Booking.objects.filter(
                slot=slot,
            ).exists()

            if has_booking:
                continue

            if (slot.start, slot.end) not in desired_set:
                slot.delete()

        existing_set = set(
            AvailabilitySlot.objects.filter(
                room=room
            ).values_list(
                "start",
                "end",
            )
        )

        new_slots = [
            AvailabilitySlot(
                room=room,
                start=slot_start,
                end=slot_end,
                max_bookings=1,
            )
            for slot_start, slot_end in desired_slots
            if (
                slot_start,
                slot_end,
            ) not in existing_set
        ]

        AvailabilitySlot.objects.bulk_create(
            new_slots,
            ignore_conflicts=True,
        )

    def create(self, validated_data):
        room = super().create(validated_data)

        self._apply_geocode(room)

        room.save(update_fields=["latitude", "longitude"])

        self._sync_availability_slots(room)

        return room


    def update(self, instance, validated_data):
        old_location = (instance.location or "").strip()

        room = super().update(instance, validated_data)

        new_location = (room.location or "").strip()

        if old_location != new_location or not room.latitude or not room.longitude:
            self._apply_geocode(room)

            room.save(update_fields=["latitude", "longitude"])

        self._sync_availability_slots(room)

        return room


    def validate_title(self, value):
        return validate_listing_title(value)

    def validate_description(self, value):
        """
        Draft listings can have incomplete descriptions.
        Completed listings must have at least 25 words.
        """
        clean = sanitize_html_description(value or "")

        # Allow incomplete wizard saves while listing is still a draft.
        if self.initial_data.get("status") == "draft":
            return clean

        words = [w for w in clean.split() if w.strip()]
        if len(words) < 25:
            raise serializers.ValidationError(
                "Description must be at least 25 words."
            )

        return clean



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

    def _viewer_is_room_owner(self, obj) -> bool:
        """
        Return True only when the authenticated requester owns this room.

        Public seekers must only receive approved photos.
        The room owner may also see pending and rejected photos so they can
        understand the moderation state of every upload.
        """
        request = self.context.get("request")
        user = getattr(request, "user", None)

        return bool(
            user
            and user.is_authenticated
            and obj.property_owner_id == user.id
        )

    def _room_images(self, obj):
        """
        Return all uploaded images so the serializer can calculate one
        overall public image-verification status.
        """
        return list(
            obj.roomimage_set.filter(
                status__in=["approved", "pending", "rejected"]
            ).order_by("id")
        )

    def _absolute_media_url(self, file_field) -> str | None:
        """
        Convert an ImageField into a frontend-ready absolute URL.
        """
        if not file_field:
            return None

        try:
            url = file_field.url
        except (ValueError, AttributeError):
            return None

        request = self.context.get("request")

        if request is not None:
            return request.build_absolute_uri(url)

        return url

    def _image_payload(self, obj) -> dict:
        """
        Return the correct room image payload for the requester.

        Owner:
        - can see approved, pending and rejected uploads
        - receives the first uploaded image as cover_image
        - receives the remaining uploads as other_images

        Public:
        - can only see approved images
        - images remain hidden until at least 3 are approved
        """
        images = self._room_images(obj)


        selected_cover_id = getattr(obj, "cover_photo_id", None)

        if selected_cover_id:
            selected_cover = next(
                (
                    image
                    for image in images
                    if image.id == selected_cover_id
                ),
                None,
            )

            if selected_cover:
                images = [
                    selected_cover,
                    *[
                        image
                        for image in images
                        if image.id != selected_cover_id
                    ],
                ]



        if not images:
            legacy_url = self._absolute_media_url(
                getattr(obj, "image", None)
            )

            if legacy_url:
                return {
                    "cover_image": legacy_url,
                    "other_images": [],
                    "image_status": "approved",
                }

            return {
                "cover_image": None,
                "other_images": None,
                "image_status": None,
            }

        approved_count = sum(
            1 for image in images if image.status == "approved"
        )
        pending_count = sum(
            1 for image in images if image.status == "pending"
        )

        if approved_count >= 3:
            image_status = "approved"
        elif pending_count > 0:
            image_status = "pending"
        else:
            image_status = "rejected"

        # The authenticated room owner can see every uploaded image,
        # including pending and rejected uploads.
        if self._viewer_is_room_owner(obj):
            owner_urls = [
                self._absolute_media_url(image.image)
                for image in images
                if image.image
            ]
            owner_urls = [url for url in owner_urls if url]

            return {
                "cover_image": owner_urls[0] if owner_urls else None,
                "other_images": owner_urls[1:],
                "image_status": image_status,
            }

        # Public users must not see images until the room has at least
        # three approved photos.
        if image_status != "approved":
            return {
                "cover_image": None,
                "other_images": None,
                "image_status": image_status,
            }

        approved_urls = [
            self._absolute_media_url(image.image)
            for image in images
            if image.status == "approved" and image.image
        ]
        approved_urls = [url for url in approved_urls if url]

        return {
            "cover_image": approved_urls[0] if approved_urls else None,
            "other_images": approved_urls[1:],
            "image_status": "approved",
        }

    @extend_schema_field(OpenApiTypes.URI)
    def get_cover_image(self, obj) -> str | None:
        return self._image_payload(obj)["cover_image"]

    @extend_schema_field(
        serializers.ListField(
            child=serializers.URLField(),
            allow_null=True,
        )
    )
    def get_other_images(self, obj) -> list[str] | None:
        return self._image_payload(obj)["other_images"]



    @extend_schema_field(OpenApiTypes.STR)
    def get_image_status(self, obj) -> str | None:
        return self._image_payload(obj)["image_status"]

    @extend_schema_field(OpenApiTypes.STR)
    def get_listing_state(self, obj) -> str:
        """
        Authoritative state used by My Listings.

        Returns one of:
        draft, active, pending_review, expired, hidden, rented.

        Lifecycle states take priority over image moderation:
        a rented, draft, expired, or hidden listing must remain in that
        lifecycle bucket regardless of its image status.
        """
        # MyListingsView calculates the authoritative state at queryset level.
        # Reuse it when present so filtering and serialized output can never
        # disagree.
        annotated_state = getattr(obj, "listing_state", None)
        if annotated_state:
            return str(annotated_state)
        
        
        
        if not getattr(obj, "is_available", True):
            return "rented"

        today = date.today()

        if obj.status == "draft":
            return "draft"

        if obj.paid_until is None:
            return "draft"

        if obj.paid_until < today:
            return "expired"

        if obj.status == "hidden":
            return "hidden"

        # Only otherwise-live listings are classified by image moderation.
        image_status = self._image_payload(obj)["image_status"]

        if image_status != "approved":
            return "pending_review"

        if obj.status == "active" and obj.paid_until >= today:
            return "active"

        # Fail closed: an unknown combination must never be exposed as active.
        return "draft"

class MyListingRoomSerializer(RoomSerializer):
    viewing_summary = serializers.SerializerMethodField()

    class Meta(RoomSerializer.Meta):
                fields = "__all__"

    def get_viewing_summary(self, obj):
        now = timezone.now()

        qs = Booking.objects.filter(
            room=obj,
            is_deleted=False,
            canceled_at__isnull=True,
            start__gte=now,
        ).order_by("start")

        next_booking = qs.first()

        return {
            "upcoming_count": qs.count(),
            "next_viewing_at": next_booking.start if next_booking else None,
            "next_booking_id": next_booking.id if next_booking else None,
        }







# --------------------
# Room Preview Serializer (Step 5/5)
# --------------------
class RoomPreviewSerializer(serializers.Serializer):
    room = serializers.SerializerMethodField()
    photos = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_room(self, obj) -> Dict[str, Any]:
        return RoomSerializer(obj, context=self.context).data

    @extend_schema_field(
    RoomPhotoResponseSerializer(many=True)
    )
    def get_photos(self, obj) -> List[Dict[str, Any]]:
        """
        Return all owner-visible photos for the room preview endpoint.

        Approved images use the original image.

        """
        request = self.context.get("request")
        photos = []

        qs = obj.roomimage_set.filter(
            status__in=["approved", "pending", "rejected"]
        ).order_by("id")

        for index, img in enumerate(qs):
            original_url = None


            if img.image:
                try:
                    original_url = img.image.url
                except (ValueError, AttributeError):
                    original_url = None



            if request is not None:
                if original_url:
                    original_url = request.build_absolute_uri(original_url)

            display_url = original_url

            if not display_url:
                continue

            photos.append(
                {
                    "id": img.id,
                    "image": display_url,
                    "url": display_url,
                    "original_image": original_url,
                    "status": img.status,
                    "moderation_state": get_room_image_moderation_state(img),
                    "user_message": get_room_image_user_message(img),
                    "can_replace": (
                        img.status != RoomImage.STATUS_APPROVED
                    ),
                    "is_main": index == 0,
                }
            )
        legacy_image = getattr(obj, "image", None)

        if not photos and legacy_image:
            try:
                legacy_url = legacy_image.url
            except (ValueError, AttributeError):
                legacy_url = None

            if legacy_url and request is not None:
                legacy_url = request.build_absolute_uri(legacy_url)

            if legacy_url:
                photos.append(
                    {
                        "id": None,
                        "image": legacy_url,
                        "url": legacy_url,
                        "original_image": legacy_url,

                        "status": "legacy",
                        "is_main": True,
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
            "agent_broker",
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


    def validate_email(self, value):
                email = normalise_email(value)

                if User.objects.filter(email__iexact=email).exists():
                    raise serializers.ValidationError(
                        "Unable to complete registration with the provided credentials."
                    )

                return email


    def validate_username(self, value):
        username = (value or "").strip()

        if User.objects.filter(username=username).exists():
            raise serializers.ValidationError(
                "Unable to complete registration with the provided credentials."
            )

        return username




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

        send_security_code_email(
            to_email=user.email,
            subject="Welcome to RentCrib – Verify your email",
            first_name=user.first_name,
            title="Verify your email",
            intro="Welcome to RentCrib. Please use the verification code below to confirm your email address.",
            code=code,
            expiry_minutes=settings.OTP_EXPIRY_MINUTES,
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
            "advertiser_verified",
            "marketing_consent",
            "preferred_timezone",
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
            "advertiser_verified",
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


    def validate_occupation(self, value):
        if value is None:
            return ""

        value = validate_plain_text(value)

        if not value:
            return ""

        return value

    def validate_about_you(self, value):
        if value is None:
            return ""

        value = validate_plain_text(value)

        if not value:
            return ""

        return value


    def validate_preferred_timezone(self, value):
        value = (value or "").strip()

        if not value:
            raise serializers.ValidationError(
                "Timezone is required."
            )

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise serializers.ValidationError(
                "Enter a valid IANA timezone, for example Europe/London."
            )

        return value



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



class LandlordVerificationRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = LandlordVerificationRequest
        fields = (
            "id",
            "status",
            "document",
            "notes",
            "reviewed_at",
            "rejection_reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "status",
            "reviewed_at",
            "rejection_reason",
            "created_at",
            "updated_at",
        )

    def validate_document(self, value):
        max_size_mb = 10
        if value and value.size > max_size_mb * 1024 * 1024:
            raise serializers.ValidationError("Verification document must not exceed 10MB.")
        return value


class IdentityVerificationRequestSerializer(serializers.ModelSerializer):

    class Meta:
        model = IdentityVerificationRequest
        fields = [
            "id",
            "document",
            "status",
            "notes",
            "rejection_reason",
            "reviewed_at",
            "created_at",
        ]

        read_only_fields = [
            "status",
            "rejection_reason",
            "reviewed_at",
            "created_at",
        ]

    def validate_document(self, value):
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError(
                "Verification document must not exceed 10MB."
            )

        return value





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
    otp = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if not attrs.get("confirm"):
            raise serializers.ValidationError({"confirm": "You must confirm account deletion."})

        otp = (attrs.get("otp") or "").strip()
        if not otp:
            raise serializers.ValidationError({"otp": "OTP is required."})

        attrs["otp"] = otp
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

        landlord_verified = serializers.BooleanField()

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
        value = validate_plain_text(value, max_len=200)

        if not value:
            raise serializers.ValidationError("Subject is required.")

        return value

    def validate_message(self, value):
        value = validate_plain_text(value, max_len=5000)

        if not value:
            raise serializers.ValidationError("Message is required.")

        return value



def get_room_image_moderation_state(image) -> str:
    """
    Return a frontend-facing moderation state for one room photo.

    This is separate from the database status because a pending photo
    may either still be checking, need manual review, or require retry.
    """
    reason = getattr(image, "moderation_reason", None)

    if image.status == RoomImage.STATUS_APPROVED:
        return "approved"

    if image.status == RoomImage.STATUS_REJECTED:
        return "rejected"

    if reason == RoomImage.MODERATION_AWAITING_CHECK:
        return "checking"

    if reason in {
        RoomImage.MODERATION_NOT_PROPERTY_PHOTO,
        RoomImage.MODERATION_UNSAFE_CONTENT,
    }:
        return "rejected"

    if reason in {
        RoomImage.MODERATION_TIMEOUT,
        RoomImage.MODERATION_SERVICE_UNAVAILABLE,
        RoomImage.MODERATION_VALIDATION_FAILED,
    }:
        return "retry_required"

    return "manual_review"


def get_room_image_user_message(image) -> str:
    """
    Return a safe message suitable for landlords.

    Provider names, raw errors and internal moderation notes must not be
    exposed through the public API.
    """
    state = get_room_image_moderation_state(image)
    reason = getattr(image, "moderation_reason", None)

    if state == "approved":
        return "Photo approved."

    if reason == RoomImage.MODERATION_AWAITING_CHECK:
        return "We are checking this photo."

    if reason == RoomImage.MODERATION_UNSAFE_CONTENT:
        return "This photo is inappropriate and cannot be used."

    if reason == RoomImage.MODERATION_NOT_PROPERTY_PHOTO:
        return "This is not a property photo. Please replace it."

    if reason == RoomImage.MODERATION_LOW_CONFIDENCE:
        return (
            "We could not clearly verify this as a property photo. Please "
            "upload a clearer photo or wait for review."
        )

    if reason == RoomImage.MODERATION_VALIDATION_FAILED:
        return (
            "This file could not be processed as a valid photo. Please "
            "replace it with a supported image."
        )

    if reason == RoomImage.MODERATION_TIMEOUT:
        return (
            "We could not finish checking this photo. Please replace it "
            "and try again."
        )

    if reason == RoomImage.MODERATION_SERVICE_UNAVAILABLE:
        return (
            "We could not process this photo because of a temporary "
            "system issue. Please replace it and try again."
        )

    if image.status == RoomImage.STATUS_REJECTED:
        return "This photo was not accepted. Please replace it."

    return "This photo requires review."




# --------------------
# Room Images / Messages / Bookings / Slots / Payments / Reports
# --------------------
class RoomImageSerializer(serializers.ModelSerializer):
    # Return a frontend-ready absolute image URL.
    image = serializers.SerializerMethodField()

    moderation_state = serializers.SerializerMethodField()
    user_message = serializers.SerializerMethodField()
    can_replace = serializers.SerializerMethodField()

    class Meta:
        model = RoomImage
        fields = [
            "id",
            "room",
            "image",
            "status",
            "moderation_state",
            "user_message",
            "can_replace",
        ]
        read_only_fields = [
            "room",
            "status",
            "moderation_state",
            "user_message",
            "can_replace",
        ]

    def get_image(self, obj):
        """
        Return image URL based on visibility rules.

        Approved:
            - visible to everyone.

        Pending/rejected:
            - visible only to the listing owner.
            - hidden from public users.
        """
        if not obj.image:
            return None

        request = self.context.get("request")

        if obj.status == RoomImage.STATUS_APPROVED:
            try:
                url = obj.image.url
            except (ValueError, AttributeError):
                return None

            if request is not None:
                return request.build_absolute_uri(url)

            return url

        if request and request.user.is_authenticated:
            if obj.room.property_owner_id == request.user.id:
                try:
                    url = obj.image.url
                except (ValueError, AttributeError):
                    return None

                return request.build_absolute_uri(url)

        return None

    def get_moderation_state(self, obj):
        return get_room_image_moderation_state(obj)

    def get_user_message(self, obj):
        return get_room_image_user_message(obj)

    def get_can_replace(self, obj):
        return obj.status != RoomImage.STATUS_APPROVED



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
    sender = serializers.SerializerMethodField()
    body = serializers.SerializerMethodField()
    is_read = serializers.SerializerMethodField()
    read_at = serializers.SerializerMethodField()
    available_actions = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id",
            "thread",
            "sender",
            "body",
            "message_type",
            "metadata",
            "available_actions",
            "created",
            "updated",
            "is_read",
            "read_at",
        ]
        read_only_fields = [
                "thread",
                "sender",
                "message_type",
                "metadata",
                "available_actions",
                "created",
                "updated",
                "is_read",
                "read_at",
            ]

    
    @extend_schema_field(serializers.CharField())
    def get_sender(self, obj):
        metadata = obj.metadata or {}

        if metadata.get("system_event") is True:
            return "RentCrib"

        return str(obj.sender)
    
    
    
    @extend_schema_field(serializers.CharField())
    def get_body(self, obj):
        metadata = obj.metadata or {}

        # Only tenancy proposal messages need viewer-specific wording.
        if (
            obj.message_type != Message.TYPE_TENANCY_PROPOSAL
            or metadata.get("event_type") != "proposed"
        ):
            return obj.body

        request = self.context.get("request")
        user = getattr(request, "user", None)

        if not user or not user.is_authenticated:
            return obj.body

        # The other party must continue to receive the existing
        # actionable proposal copy.
        if user.id != obj.sender_id:
            return obj.body

        # The person who submitted the tenancy information must not see
        # instructions telling them to review/respond to their own proposal.
        room_title = (
            metadata.get("room_title")
            or "this property"
        )

        move_in_date = metadata.get("move_in_date")
        duration_months = metadata.get("duration_months")
        monthly_rent = metadata.get("monthly_rent")
        
        formatted_duration = (
            f"{duration_months} months"
            if duration_months is not None
            else "Not provided"
        )

        formatted_rent = (
            f"£{monthly_rent}"
            if monthly_rent not in (None, "")
            else "Not provided"
        )

        # Make the stored ISO date human-readable where possible.
        formatted_move_in = move_in_date or "Not provided"

        if move_in_date:
            try:
                from datetime import date

                parsed_date = date.fromisoformat(
                    str(move_in_date)
                )
                formatted_move_in = (
                    f"{parsed_date.day} "
                    f"{parsed_date.strftime('%B %Y')}"
                )
            except (TypeError, ValueError):
                pass

        details = [
            (
                "You submitted tenancy information for "
                f"{room_title}."
            ),
            "",
            "The details you submitted are:",
            "",
            f"Move-in date: {formatted_move_in}",
            f"Duration: {formatted_duration}",
            f"Monthly rent: {formatted_rent}",
            "",
        ]

        # Mirror the acknowledgement depending on who submitted.
        try:
            tenancy_id = metadata.get("tenancy_id")
            tenancy = Tenancy.objects.only(
                "id",
                "landlord_id",
                "tenant_id",
            ).get(id=tenancy_id)
        except (Tenancy.DoesNotExist, TypeError, ValueError):
            tenancy = None

        if tenancy and user.id == tenancy.tenant_id:
            details.append(
                "Your landlord has been asked to review these details. "
                "You will be notified when they respond."
            )
        elif tenancy and user.id == tenancy.landlord_id:
            details.append(
                "Your tenant has been asked to review these details. "
                "You will be notified when they respond."
            )
        else:
            details.append(
                "The other party has been asked to review these details. "
                "You will be notified when they respond."
            )

        return "\n".join(details)
        
        
        

    @extend_schema_field(
        serializers.ListField(
            child=serializers.CharField(),
        )
    )
    def get_available_actions(self, obj):
        metadata = obj.metadata or {}
        event_type = metadata.get("event_type")
        
        if event_type == "booking_completed":
            booking_id = metadata.get("booking_id")
            if not booking_id:
                return []

            request = self.context.get("request")
            user = getattr(request, "user", None)

            if not user or not user.is_authenticated:
                return []

            try:
                booking = Booking.objects.select_related(
                    "room__property_owner"
                ).get(id=booking_id)
            except Booking.DoesNotExist:
                return []

            owner_id = booking.room.property_owner_id

            if user.id not in {
                booking.user_id,
                owner_id,
            }:
                return []

            return ["update_tenancy"]
                
                
                
                
                

        # Timer 2 thread message.
        if event_type == "still_living_check":
            tenancy_id = metadata.get("tenancy_id")

            if not tenancy_id:
                return []

            try:
                tenancy = Tenancy.objects.get(id=tenancy_id)
            except Tenancy.DoesNotExist:
                return []

            request = self.context.get("request")
            user = getattr(request, "user", None)

            if (
                not user
                or not user.is_authenticated
                or user.id not in {
                    tenancy.landlord_id,
                    tenancy.tenant_id,
                }
            ):
                return []

            now = timezone.now()

            if tenancy.status not in {
                Tenancy.STATUS_CONFIRMED,
                Tenancy.STATUS_ACTIVE,
            }:
                return []

            if tenancy.still_living_confirmed_at is not None:
                return []

            if (
                tenancy.review_open_at is not None
                and now >= tenancy.review_open_at
            ):
                return []

            return ["update_tenancy"]

        # Timer 3 thread message.
        if event_type == "review_available":
            tenancy_id = metadata.get("tenancy_id")

            if not tenancy_id:
                return []

            try:
                tenancy = Tenancy.objects.get(id=tenancy_id)
            except Tenancy.DoesNotExist:
                return []

            serializer = TenancyDetailSerializer(
                tenancy,
                context=self.context,
            )
            can_leave_review, _ = (
                serializer._get_review_eligibility(
                    tenancy
                )
            )

            if can_leave_review:
                return ["leave_review"]

            return []

        # Existing tenancy proposal/update actions.
        if obj.message_type not in {
            Message.TYPE_TENANCY_PROPOSAL,
            Message.TYPE_TENANCY_UPDATED,
        }:
            return []

        tenancy_id = metadata.get("tenancy_id")

        if not tenancy_id:
            return []

        try:
            tenancy = (
                Tenancy.objects
                .select_related("landlord", "tenant", "room")
                .get(id=tenancy_id)
            )
        except Tenancy.DoesNotExist:
            return []

        serializer = TenancyDetailSerializer(
            tenancy,
            context=self.context,
        )
        permissions = (
            serializer._get_tenancy_action_permissions(
                tenancy
            )
        )
        return permissions["available_actions"]
    
    
    
    def _get_read_for_user(self, obj):
        request = self.context.get("request")

        if not request or not request.user.is_authenticated:
            return None

        user = request.user

        if obj.sender_id == user.id:
            return None

        cached_user_id = getattr(
            obj,
            "_read_cache_user_id",
            None,
        )

        if cached_user_id == user.id:
            return getattr(obj, "_read_cache_value", None)

        prefetched_reads = getattr(
            obj,
            "_prefetched_objects_cache",
            {},
        ).get("reads")

        if prefetched_reads is not None:
            read = next(
                (
                    item
                    for item in prefetched_reads
                    if item.user_id == user.id
                ),
                None,
            )
        else:
            read = obj.reads.filter(user=user).first()

        obj._read_cache_user_id = user.id
        obj._read_cache_value = read

        return read


    def get_is_read(self, obj):
        request = self.context.get("request")

        if not request or not request.user.is_authenticated:
            return False

        metadata = obj.metadata or {}

        # RentCrib system messages do not have a meaningful human
        # sender/recipient read receipt.
        if metadata.get("system_event") is True:
            return self._get_read_for_user(obj) is not None

        # Recipient viewing an inbound human message:
        # report whether THIS user has read it.
        if obj.sender_id != request.user.id:
            return self._get_read_for_user(obj) is not None

        # Sender viewing their own human message:
        # it is only "read" if another participant has actually created
        # a MessageRead row for this message.
        prefetched_reads = getattr(
            obj,
            "_prefetched_objects_cache",
            {},
        ).get("reads")

        if prefetched_reads is not None:
            return any(
                read.user_id != obj.sender_id
                for read in prefetched_reads
            )

        return obj.reads.exclude(
            user_id=obj.sender_id,
        ).exists()


    def get_read_at(self, obj):
        request = self.context.get("request")

        if not request or not request.user.is_authenticated:
            return None

        metadata = obj.metadata or {}

        if metadata.get("system_event") is True:
            read = self._get_read_for_user(obj)
            return read.read_at if read else None

        # Recipient sees their own read timestamp.
        if obj.sender_id != request.user.id:
            read = self._get_read_for_user(obj)
            return read.read_at if read else None

        # Sender sees when the recipient actually read the message.
        prefetched_reads = getattr(
            obj,
            "_prefetched_objects_cache",
            {},
        ).get("reads")

        if prefetched_reads is not None:
            recipient_reads = [
                read
                for read in prefetched_reads
                if read.user_id != obj.sender_id
            ]

            if not recipient_reads:
                return None

            return min(
                read.read_at
                for read in recipient_reads
            )

        read = (
            obj.reads
            .exclude(user_id=obj.sender_id)
            .order_by("read_at")
            .first()
        )

        return read.read_at if read else None


class MessageThreadSerializer(serializers.ModelSerializer):
    participants = serializers.SlugRelatedField(
        slug_field="username", many=True, queryset=User.objects.all()
    )
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    other_user = serializers.SerializerMethodField(read_only=True)
    
    participant_role = serializers.SerializerMethodField()
    relationship_type = serializers.SerializerMethodField()
    inbox_side = serializers.SerializerMethodField()
    relationship_id = serializers.SerializerMethodField()
    property_id = serializers.SerializerMethodField()

    room_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
    )
    landlord_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
    )
    seeker_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
    )

    # NEW: per-user state fields
    label = serializers.SerializerMethodField()
    in_bin = serializers.SerializerMethodField()

    class Meta:
        model = MessageThread
        fields = [
            "id",
            "participants",
            "other_user",
            "participant_role",
            "relationship_type",
            "room_id",
            "landlord_id",
            "seeker_id",
            "inbox_side",
            "relationship_id",
            "property_id",
            "created_at",
            "last_message",
            "unread_count",
            "label",
            "in_bin",
        ]



  
    
    
    @extend_schema_field(
        serializers.ChoiceField(
            choices=[
                ("landlord", "Landlord"),
                ("seeker", "Seeker"),
                ("unscoped", "Unscoped"),
            ],
            allow_null=True,
        )
    )
    def get_participant_role(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        if not user or not user.is_authenticated:
            return None

        matching_roles = []

        if obj.landlord_id == user.id:
            matching_roles.append("landlord")

        if obj.seeker_id == user.id:
            matching_roles.append("seeker")

        if len(matching_roles) == 1:
            return matching_roles[0]

        # Historical roomless or malformed threads are explicitly unscoped.
        # Never infer their role from message order, sender or message text.
        return "unscoped"



    @extend_schema_field(
    serializers.ChoiceField(
        choices=[
            ("landlord", "Landlord"),
            ("seeker", "Seeker"),
            ("unscoped", "Unscoped"),
        ],
        allow_null=True,
    )
    )
    def get_inbox_side(self, obj):
        return self.get_participant_role(obj)



    @extend_schema_field(
        serializers.ChoiceField(
            choices=[
                ("room_enquiry", "Room enquiry"),
                ("legacy_direct", "Legacy direct"),
            ],
        )
    )
    def get_relationship_type(self, obj):
        if obj.room_id:
            return "room_enquiry"

        return "legacy_direct"
    
    
    
    @extend_schema_field(
        serializers.IntegerField(
            read_only=True,
            allow_null=True,
        )
    )
    def get_relationship_id(self, obj):
        # A conversation is scoped to its room/property lifecycle.
        # Booking and tenancy IDs remain event-specific message metadata.
        return obj.room_id


    @extend_schema_field(
        serializers.IntegerField(
            read_only=True,
            allow_null=True,
        )
    )
    def get_property_id(self, obj):
        return obj.room_id
    
    
    @extend_schema_field(
    serializers.DictField(
            child=serializers.CharField(allow_null=True),
            allow_null=True,
        )
    )
    
    
    def get_other_user(self, obj):
        request = self.context.get("request")
        current_user = getattr(request, "user", None)

        if not current_user or not current_user.is_authenticated:
            return None

        participants = getattr(obj, "_prefetched_objects_cache", {}).get("participants")

        if participants is not None:
            other_user = next(
                (user for user in participants if user.id != current_user.id),
                None,
            )
        else:
            other_user = obj.participants.exclude(id=current_user.id).first()

        if not other_user:
            return None

        profile = getattr(other_user, "profile", None)
        avatar = getattr(profile, "avatar", None) if profile else None

        avatar_url = None
        if avatar:
            try:
                avatar_url = avatar.url
                if request is not None:
                    avatar_url = request.build_absolute_uri(avatar_url)
            except (ValueError, AttributeError):
                avatar_url = None

        return {
            "id": other_user.id,
            "username": other_user.username,
            "profile_image": avatar_url,
        }


    @extend_schema_field(MessageSerializer(allow_null=True))
    def get_last_message(self, obj):
        prefetched_messages = getattr(
            obj,
            "_prefetched_last_messages",
            None,
        )

        if prefetched_messages is not None:
            msg = (
                prefetched_messages[0]
                if prefetched_messages
                else None
            )
        else:
            msg = (
                obj.messages
                .select_related("sender")
                .prefetch_related("reads")
                .order_by("-created")
                .first()
            )

        return (
            MessageSerializer(
                msg,
                context={
                    "request": self.context.get("request"),
                },
            ).data
            if msg
            else None
        )

    @extend_schema_field(serializers.IntegerField())
    def get_unread_count(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return 0
        if hasattr(obj, "unread_count"):
            return obj.unread_count

        return (
            obj.messages
            .filter(
                Q(metadata__system_event=True)
                | ~Q(sender=request.user)
            )
            .exclude(reads__user=request.user)
            .distinct()
            .count()
        )

    def _get_state_for_user(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        if not user or not user.is_authenticated:
            return None

        if hasattr(obj, "_state_for_user"):
            return obj._state_for_user

        return MessageThreadState.objects.filter(
            user=user,
            thread=obj,
        ).first()

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
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user_name = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "room",
            "user_id",
            "user_name",
            "slot",
            "room_title",
            "start",
            "end",
            "status",
            "created_at",
            "canceled_at",
        ]
        read_only_fields = [
            "user_id",
            "user_name",
            "created_at",
            "canceled_at",
        ]
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




class BookingRescheduleSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()

    def validate(self, attrs):
        start = attrs["start"]
        end = attrs["end"]

        if start >= end:
            raise serializers.ValidationError(
                {"end": "End time must be after start time."}
            )

        if start <= timezone.now():
            raise serializers.ValidationError(
                {"start": "Cannot reschedule a viewing into the past."}
            )

        return attrs


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
        active_bookings = obj.bookings.filter(
            canceled_at__isnull=True,
            is_deleted=False,
        ).count()
        return active_bookings >= obj.max_bookings



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
    cta_url = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "type",
            "title",
            "audience",
            "body",
            "thread",
            "message",
            "target_type",
            "target_id",
            "deep_link",
            "cta_url",
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
    
    
    
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_cta_url(self, obj) -> str:
        """
        Returns the web/Vercel route for browser navigation.
        Mobile continues to use deep_link.
        """

        notification_type = getattr(obj, "type", None)
        target_type = getattr(obj, "target_type", None)
        target_id = getattr(obj, "target_id", None)
        
        
        

        # Viewing-completed notifications open the Completed tab.
        if notification_type in {
            "booking_completed",
            "booking_completed_landlord",
        }:
            return "/viewings?tab=completed"

        # Tenancy expiry / still-living reminders must open the tenancy itself.
        # Both tenant and landlord can act on the same tenancy record.
        if target_type == "still_living_check" and target_id:
            return f"/tenancies/{target_id}"

        # Other tenancy notifications should also prefer their tenancy target
        # over the associated message thread.
        if target_type == "tenancy" and target_id:
            return f"/tenancies/{target_id}"

        if target_type == "tenancy_extension" and target_id:
            return f"/tenancies/{target_id}"

        if target_type == "tenancy_review" and target_id:
            return f"/leave-a-review?tenancy={target_id}"

        # Message notifications/conversation-driven events can use the thread.
        if getattr(obj, "thread_id", None):
            return f"/messages?thread={obj.thread_id}"

        # Generic booking target.
        if target_type == "booking" and target_id:
            return f"/viewings/{target_id}"

        return self.get_deep_link(obj)


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
            # Consent
            "marketing_consent",

            # Display and regional preferences
            "theme",
            "date_format",
            "time_format",

            # Delivery channels
            "notify_email",
            "notify_push",
            "notify_sms",

            # Existing RentCrib notification categories
            "notify_rentout_updates",
            "notify_reminders",
            "notify_messages",
            "notify_confirmations",

            # Admin dashboard reports and alerts
            "notify_weekly_reports",
            "notify_monthly_reports",
            "notify_system_alerts",
            "notify_user_reports",
            "notify_payment_alerts",
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


