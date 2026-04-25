from django.core.management.base import BaseCommand
from notifications.models import NotificationTemplate

TEMPLATES = [
    {
        "key": "message.new",
        "subject": "New message from {{ sender.name }}",
        "body": (
            "Hi {{ user.first_name }},\n\n"
            "You’ve received a new message from {{ sender.name }}:\n"
            "\"{{ snippet }}\"\n\n"
            "Reply here: {{ thread_url }}\n"
        ),
    },
    {
        "key": "booking.new",
        "subject": "New booking request for {{ room.title }}",
        "body": (
            "Hi {{ user.first_name }},\n\n"
            "{{ booker.name }} requested a booking for \"{{ room.title }}\".\n"
            "Booking ID: {{ booking_id }}\n\n"
            "Please review this request in your dashboard.\n"
        ),
    },
    {
        "key": "booking.confirmation",
        "subject": "Booking request placed for {{ room.title }}",
        "body": (
            "Hi {{ user.first_name }},\n\n"
            "Your booking request for \"{{ room.title }}\" has been sent to {{ room.owner_name }}.\n"
            "Booking ID: {{ booking_id }}\n"
        ),
    },
    {
        "key": "listing.expiring",
        "subject": "Your listing \"{{ room.title }}\" expires on {{ room.paid_until }}",
        "body": (
            "Hi {{ user.first_name }},\n\n"
            "Your listing \"{{ room.title }}\" will expire on {{ room.paid_until }}.\n"
            "Renew now: {{ renew_url }}\n"
        ),
    },
    
    
        # -------------------------
    # Tenancy lifecycle
    # -------------------------
    {
        "key": "tenancy.proposed",
        "subject": "Tenancy proposal for {{ room_title }}",
        "body": (
            "Hi {{ user.first_name }},\n\n"
            "A tenancy proposal was sent for: {{ room_title }}.\n\n"
            "Open here: {{ cta_url }}\n"
        ),
    },
    {
        "key": "tenancy.updated",
        "subject": "Tenancy proposal updated for {{ room_title }}",
        "body": (
            "Hi {{ user.first_name }},\n\n"
            "The tenancy proposal was updated for: {{ room_title }}.\n\n"
            "Open here: {{ cta_url }}\n"
        ),
    },
    {
        "key": "tenancy.confirmed",
        "subject": "Tenancy confirmed for {{ room_title }}",
        "body": (
            "Hi {{ user.first_name }},\n\n"
            "Tenancy is confirmed for: {{ room_title }}.\n\n"
            "Open here: {{ cta_url }}\n"
        ),
    },
    {
        "key": "tenancy.cancelled",
        "subject": "Tenancy cancelled for {{ room_title }}",
        "body": (
            "Hi {{ user.first_name }},\n\n"
            "Tenancy was cancelled for: {{ room_title }}.\n\n"
            "Open here: {{ cta_url }}\n"
        ),
    },

    # -------------------------
    # Tenancy prompts
    # -------------------------
    {
        "key": "tenancy.still_living_check",
        "subject": "Tenancy check for {{ room_title }}",
        "body": (
            "Hi {{ user.first_name }},\n\n"
            "Quick check: is the tenant still living at {{ room_title }}?\n\n"
            "Respond here: {{ cta_url }}\n"
        ),
    },
    {
        "key": "tenancy.review_available",
        "subject": "Review available for {{ room_title }}",
        "body": (
            "Hi {{ user.first_name }},\n\n"
            "You can now leave a review for {{ room_title }}.\n\n"
            "Open here: {{ cta_url }}\n"
        ),
    },

    # -------------------------
    # Tenancy extension
    # -------------------------
    {
        "key": "tenancy.extension.proposed",
        "subject": "Tenancy extension proposed for {{ room_title }}",
        "body": (
            "Hi {{ user.first_name }},\n\n"
            "A tenancy extension was proposed for {{ room_title }}.\n\n"
            "Open here: {{ cta_url }}\n"
        ),
    },
    {
        "key": "tenancy.extension.accepted",
        "subject": "Tenancy extension accepted for {{ room_title }}",
        "body": (
            "Hi {{ user.first_name }},\n\n"
            "The tenancy extension was accepted for {{ room_title }}.\n\n"
            "Open here: {{ cta_url }}\n"
        ),
    },
    {
        "key": "tenancy.extension.rejected",
        "subject": "Tenancy extension rejected for {{ room_title }}",
        "body": (
            "Hi {{ user.first_name }},\n\n"
            "The tenancy extension was rejected for {{ room_title }}.\n\n"
            "Open here: {{ cta_url }}\n"
        ),
    },
]

class Command(BaseCommand):
    help = "Seed default notification templates"

    def handle(self, *args, **options):
        created = 0
        for t in TEMPLATES:
            obj, was_created = NotificationTemplate.objects.get_or_create(
                key=t["key"],
                defaults={"subject": t["subject"], "body": t["body"], "channel": "email", "is_active": True},
            )
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Seeded templates. New created: {created}"))
