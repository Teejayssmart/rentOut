from django.db import models

# Create your models here.

from django.conf import settings
from django.db import models
from django.utils import timezone

class NotificationTemplate(models.Model):
    CHANNEL_EMAIL = "email"
    CHANNEL_PUSH = "push"
    CHANNEL_CHOICES = [(CHANNEL_EMAIL, "Email"), (CHANNEL_PUSH, "Push")]

    key = models.CharField(max_length=100, unique=True)
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default=CHANNEL_EMAIL)
    subject = models.CharField(max_length=200, blank=True, default="")
    body = models.TextField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.key} ({self.channel})"

class NotificationPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_pref")
    email_enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"Prefs for {self.user_id}"

class OutboundNotification(models.Model):
    STATUS_QUEUED = "queued"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"

    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
        (STATUS_SKIPPED, "Skipped"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="outbound_notifications")
    channel = models.CharField(max_length=10, default=NotificationTemplate.CHANNEL_EMAIL)
    template_key = models.CharField(max_length=100)
    context = models.JSONField(default=dict, blank=True)
    scheduled_for = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["status", "scheduled_for"])]

class DeliveryAttempt(models.Model):
    notification = models.ForeignKey(OutboundNotification, on_delete=models.CASCADE, related_name="attempts")
    provider = models.CharField(max_length=50, default="email")
    success = models.BooleanField(default=False)
    response = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

