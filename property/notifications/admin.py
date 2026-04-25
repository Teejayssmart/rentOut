from django.contrib import admin

# Register your models here.
from django.contrib import admin
from notifications.models import NotificationTemplate, OutboundNotification


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ("key", "channel", "subject", "is_active")
    list_filter = ("channel", "is_active")
    search_fields = ("key", "subject")


@admin.register(OutboundNotification)
class OutboundNotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "channel", "template_key", "status", "created_at")
    list_filter = ("channel", "status")
    search_fields = ("user__username", "template_key")