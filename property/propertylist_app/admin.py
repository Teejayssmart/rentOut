
from django.contrib import admin, messages
from django.utils import timezone
from propertylist_app.models import (
    Room,
    RoomCategorie,
    Review,
    UserProfile,
    AuditLog,
    IdempotencyKey,
    RoomImage,
    Booking,
    WebhookReceipt,
    SavedRoom,
    MessageThread,
    Message,
    AvailabilitySlot,
    Payment,
    
)


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
        "is_available",
        "available_from",
        "avg_rating",
        "latitude",
        "longitude",
        "is_deleted",
    )
    list_filter = (
        "category",
        "is_available",
        "property_type",
        "furnished",
        "bills_included",
        "parking_available",
        "is_deleted",
    )
    search_fields = ("title", "location", "property_owner__username")
    readonly_fields = ("created_at", "updated_at")
    inlines = [RoomImageInline]
    actions = [soft_delete_selected, restore_selected,approve_rooms, hide_rooms]


@admin.register(RoomCategorie)
class RoomCategorieAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "slug", "active", "website")
    list_editable = ("active",)                      # inline toggle
    search_fields = ("name", "key", "slug")
    list_filter = ("active",)
    prepopulated_fields = {"slug": ("name",)}        # auto-fill slug from name



@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("review_user", "room", "rating", "active", "created")
    list_filter = ("active", "rating")
    search_fields = ("review_user__username", "room__title")
    readonly_fields = ("created", "update")


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


@admin.register(WebhookReceipt)
class WebhookReceiptAdmin(admin.ModelAdmin):
    list_display = ("source", "event_id", "received_at")
    list_filter = ("source",)
    search_fields = ("event_id",)
    readonly_fields = ("received_at",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
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
    list_display = ("id", "thread", "sender", "short_body", "created_at")
    list_filter = ("sender", "thread")
    search_fields = ("sender__username", "body")
    readonly_fields = ("created_at",)

    @admin.display(description="Body")
    def short_body(self, obj):
        text = obj.body or ""
        return (text[:60] + "…") if len(text) > 60 else text
    
    
@admin.register(AvailabilitySlot)
class AvailabilitySlotAdmin(admin.ModelAdmin):
    list_display = ("room", "start", "end", "max_bookings")
    list_filter = ("room",)
    search_fields = ("room__title",)
    
    
    
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "room", "amount", "currency", "status", "created_at")
    list_filter  = ("status", "currency", "provider")
    search_fields = ("user__username", "room__title", "stripe_checkout_session_id", "stripe_payment_intent_id")
    readonly_fields = ("created_at",)
    
    
