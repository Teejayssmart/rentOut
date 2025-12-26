from django.contrib import admin, messages
from django.utils import timezone

from propertylist_app.models import (
    # Core listings
    Room,
    RoomCategorie,
    RoomImage,
    AvailabilitySlot,
    Booking,
    Review,
    SavedRoom,

    # Users / profiles
    UserProfile,

    # Messaging
    MessageThread,
    MessageThreadState,
    Message,
    MessageRead,
    Notification,

    # Payments
    Payment,
    IdempotencyKey,
    WebhookReceipt,

    # Support / moderation
    ContactMessage,
    Report,
    AuditLog,

    # GDPR / ops
    DataExport,
    GDPRTombstone,

    # Auth / verification
    EmailOTP,
    PhoneOTP,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ---------- Inlines ----------

class RoomImageInline(admin.TabularInline):
    model = RoomImage
    extra = 0
    fields = ("image", "uploaded_at")
    readonly_fields = ("uploaded_at",)


# ---------- Actions (soft delete / restore) ----------

@admin.action(description="Soft delete selected rooms")
def soft_delete_selected(modeladmin, request, queryset):
    for obj in queryset:
        if hasattr(obj, "soft_delete"):
            obj.soft_delete()


@admin.action(description="Restore selected rooms")
def restore_selected(modeladmin, request, queryset):
    for obj in queryset:
        if hasattr(obj, "restore"):
            obj.restore()


@admin.action(description="Approve selected rooms (set status=active)")
def approve_rooms(modeladmin, request, queryset):
    updated = queryset.update(status="active")
    # audit (best-effort)
    try:
        for r_id in queryset.values_list("id", flat=True):
            AuditLog.objects.create(
                actor=request.user,
                action="room.approve",
                object_type="room",
                object_id=str(r_id),
                meta={"via_admin_action": True, "at": timezone.now().isoformat()},
            )
    except Exception:
        pass
    messages.success(request, f"{updated} room(s) approved.")


@admin.action(description="Hide selected rooms (set status=hidden)")
def hide_rooms(modeladmin, request, queryset):
    updated = queryset.update(status="hidden")
    # audit (best-effort)
    try:
        for r_id in queryset.values_list("id", flat=True):
            AuditLog.objects.create(
                actor=request.user,
                action="room.hide",
                object_type="room",
                object_id=str(r_id),
                meta={"via_admin_action": True, "at": timezone.now().isoformat()},
            )
    except Exception:
        pass
    messages.success(request, f"{updated} room(s) hidden.")


# ---------- ModelAdmins ----------

@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "property_owner",
        "category",
        "price_per_month",
        "status",
        "is_available",
        "paid_until",
        "is_deleted",
    )

    list_filter = (
        "status",
        "category",
        "property_type",
        "furnished",
        "bills_included",
        "parking_available",
        "is_deleted",
    )

    search_fields = ("title", "location", "property_owner__username")

    readonly_fields = ("created_at", "updated_at", "avg_rating", "number_rating")

    inlines = [RoomImageInline]

    actions = [
        soft_delete_selected,
        restore_selected,
        approve_rooms,
        hide_rooms,
    ]

    fieldsets = (
        ("Core listing", {
            "fields": (
                "title",
                "description",
                "category",
                "status",
                "property_owner",
            )
        }),

        ("Pricing", {
            "fields": (
                "price_per_month",
                "security_deposit",
                "bills_included",
                "paid_until",
            )
        }),

        ("Location", {
            "fields": (
                "location",
                "latitude",
                "longitude",
            )
        }),

        ("Property details", {
            "fields": (
                "property_type",
                "number_of_bedrooms",
                "number_of_bathrooms",
                "furnished",
                "parking_available",
            )
        }),

        ("Availability", {
            "fields": (
                "is_available",
                "available_from",
                "availability_from_time",
                "availability_to_time",
                "view_available_days_mode",
                "view_available_custom_dates",
            )
        }),

        ("Search & matching", {
            "classes": ("collapse",),
            "fields": (
                "is_shared_room",
                "room_for",
                "room_size",
                "min_age",
                "max_age",
                "min_stay_months",
                "max_stay_months",
            )
        }),

        ("Existing flatmates", {
            "classes": ("collapse",),
            "fields": (
                "existing_flatmate_age",
                "existing_flatmate_gender",
                "existing_flatmate_occupation",
                "existing_flatmate_nationality",
                "existing_flatmate_language",
                "existing_flatmate_smoking",
                "existing_flatmate_pets",
                "existing_flatmate_lgbtqia_household",
            )
        }),

        ("Preferred flatmate", {
            "classes": ("collapse",),
            "fields": (
                "preferred_flatmate_min_age",
                "preferred_flatmate_max_age",
                "preferred_flatmate_gender",
                "preferred_flatmate_occupation",
                "preferred_flatmate_language",
                "preferred_flatmate_nationality",
                "preferred_flatmate_smoking",
                "preferred_flatmate_pets",
                "preferred_flatmate_partners_allowed",
                "preferred_flatmate_lgbtqia",
                "preferred_flatmate_vegan_vegetarian",
            )
        }),

        ("System", {
            "classes": ("collapse",),
            "fields": (
                "avg_rating",
                "number_rating",
                "is_deleted",
                "created_at",
                "updated_at",
            )
        }),
    )



@admin.register(RoomCategorie)
class RoomCategorieAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "slug", "active", "website")
    list_editable = ("active",)
    search_fields = ("name", "key", "slug")
    list_filter = ("active",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "role",
        "booking",
        "reviewer",
        "reviewee",
        "overall_rating",
        "submitted_at",
        "reveal_at",
        "active",
    )
    list_filter = ("role", "active")
    search_fields = ("reviewer__username", "reviewee__username")
    readonly_fields = ("submitted_at", "reveal_at", "overall_rating")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone")
    search_fields = ("user__username", "phone")


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("user", "room", "start", "end", "created_at")
    list_filter = ("room", "user")
    search_fields = ("user__username", "room__title")
    readonly_fields = ("created_at",)


@admin.register(SavedRoom)
class SavedRoomAdmin(admin.ModelAdmin):
    list_display = ("user", "room", "created_at")
    search_fields = ("user__username", "room__title")
    list_filter = ("user", "room")
    readonly_fields = ("created_at",)


@admin.register(RoomImage)
class RoomImageAdmin(admin.ModelAdmin):
    list_display = ("id", "room", "image", "uploaded_at")
    list_filter = ("room",)
    search_fields = ("room__title",)
    readonly_fields = ("uploaded_at",)


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    list_display = ("user_id", "key", "action", "created_at")
    list_filter = ("action",)
    search_fields = ("user_id", "key")
    readonly_fields = ("created_at",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    # Your AuditLog model clearly does NOT have "actor"
    # Use "user" (the common field name in AuditLog models)
    list_display = ("timestamp", "user", "action", "ip_address")
    list_filter = ("action", "user")
    search_fields = ("user__username", "action", "ip_address")
    readonly_fields = ("timestamp",)




# ---------- Messaging ----------

@admin.register(MessageThread)
class MessageThreadAdmin(admin.ModelAdmin):
    list_display = ("id", "participants_list", "created_at")
    search_fields = ("participants__username",)
    filter_horizontal = ("participants",)
    readonly_fields = ("created_at",)

    @admin.display(description="Participants")
    def participants_list(self, obj):
        usernames = list(obj.participants.values_list("username", flat=True))
        return ", ".join(usernames)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "thread", "sender", "short_body", "created")
    readonly_fields = ("created",)
    search_fields = ("body", "sender__username", "thread__id")
    list_select_related = ("thread", "sender")
    ordering = ("-created",)

    @admin.display(description="Body")
    def short_body(self, obj):
        text = obj.body or ""
        return (text[:60] + "…") if len(text) > 60 else text


@admin.register(MessageThreadState)
class MessageThreadStateAdmin(admin.ModelAdmin):
    list_display = ("user", "thread", "label", "in_bin", "updated_at")
    list_filter = ("label", "in_bin")
    search_fields = ("user__username",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "type", "is_read", "created_at")
    list_filter = ("type", "is_read")
    search_fields = ("user__username", "title", "body")
    readonly_fields = ("created_at",)


# Read receipts data is usually sensitive -> read-only in admin
@admin.register(MessageRead)
class MessageReadAdmin(ReadOnlyAdmin):
    list_display = ("message", "user", "read_at")
    search_fields = ("user__username",)
    readonly_fields = ("message", "user", "read_at")


# ---------- Availability ----------

@admin.register(AvailabilitySlot)
class AvailabilitySlotAdmin(admin.ModelAdmin):
    list_display = ("room", "start", "end", "max_bookings")
    list_filter = ("room",)
    search_fields = ("room__title",)


# ---------- Payments ----------

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "room", "amount", "currency", "status", "created_at")
    # NOTE: only include "provider" if it truly exists on Payment model
    list_filter = ("status", "currency")
    search_fields = (
        "user__username",
        "room__title",
        "stripe_checkout_session_id",
        "stripe_payment_intent_id",
    )
    readonly_fields = ("created_at",)


@admin.register(WebhookReceipt)
class WebhookReceiptAdmin(ReadOnlyAdmin):
    list_display = ("source", "event_id", "received_at")
    search_fields = ("event_id", "source")
    readonly_fields = ("source", "event_id", "received_at")


# ---------- Support / moderation ----------

@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("email", "subject", "is_resolved", "created_at")
    list_filter = ("is_resolved",)
    search_fields = ("email", "subject", "message")
    readonly_fields = ("created_at",)


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("id", "target_type", "status", "reporter", "created_at")
    list_filter = ("status", "target_type")
    search_fields = ("reason", "details")
    readonly_fields = ("created_at", "updated_at")


# ---------- GDPR / ops ----------

@admin.register(DataExport)
class DataExportAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "created_at", "expires_at")
    list_filter = ("status",)
    readonly_fields = ("created_at",)


@admin.register(GDPRTombstone)
class GDPRTombstoneAdmin(ReadOnlyAdmin):
    list_display = ("user_id_hash", "anonymised_at", "note")
    readonly_fields = ("user_id_hash", "anonymised_at", "note")


# ---------- OTP / verification (read-only) ----------

@admin.register(EmailOTP)
class EmailOTPAdmin(ReadOnlyAdmin):
    list_display = ("user", "code", "created_at", "expires_at", "used_at", "attempts")
    readonly_fields = list_display


@admin.register(PhoneOTP)
class PhoneOTPAdmin(ReadOnlyAdmin):
    list_display = ("user", "phone", "code", "created_at", "expires_at", "used_at", "attempts")
    readonly_fields = list_display
