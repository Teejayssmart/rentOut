import pytest
from django.core.management import call_command
from notifications.models import NotificationTemplate

pytestmark = pytest.mark.django_db

def test_seed_notification_templates_command_idempotent():
    call_command("seed_notification_templates")
    count1 = NotificationTemplate.objects.count()
    call_command("seed_notification_templates")  # run again (should not duplicate)
    count2 = NotificationTemplate.objects.count()
    assert count2 == count1
    # sanity: keys created
    keys = set(NotificationTemplate.objects.values_list("key", flat=True))
    assert {"message.new", "booking.new", "booking.confirmation", "listing.expiring"} <= keys
