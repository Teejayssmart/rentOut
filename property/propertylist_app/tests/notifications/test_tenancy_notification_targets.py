import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from propertylist_app.models import RoomCategorie, Room, Tenancy, Notification
from propertylist_app.tasks import task_send_tenancy_notification


User = get_user_model()


@pytest.mark.django_db
def test_task_send_tenancy_notification_sets_target_fields():
    landlord = User.objects.create_user(username="landlord", password="pass")
    tenant = User.objects.create_user(username="tenant", password="pass")

    cat = RoomCategorie.objects.create(name="Any", active=True)
    room = Room.objects.create(
        title="R1",
        description="x",
        price_per_month=500,
        location="SW1A 1AA",
        category=cat,
        property_owner=landlord,
    )

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=tenant,
        move_in_date=timezone.localdate(),
        duration_months=6,
        status=Tenancy.STATUS_CONFIRMED,
    )

    task_send_tenancy_notification(tenancy.id, "proposed")

    notif = Notification.objects.filter(type="tenancy_proposed").first()

    assert notif is not None
    assert notif.target_type == "tenancy"
    assert notif.target_id == tenancy.id