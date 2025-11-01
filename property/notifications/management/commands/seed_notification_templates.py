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
