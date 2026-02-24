import pytest
from django.utils import timezone
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.models import RoomCategorie, Room, Tenancy, TenancyExtension


User = get_user_model()


@pytest.mark.django_db
def test_tenancy_proposed_queues_email():
    # template exists
    NotificationTemplate.objects.create(
        key="tenancy.proposed",
        channel="email",
        subject="x",
        body="Open: {{ cta_url }}",
        is_active=True,
    )

    landlord = User.objects.create_user(username="land", email="l@example.com", password="x")
    tenant = User.objects.create_user(username="ten", email="t@example.com", password="x")

    cat = RoomCategorie.objects.create(name="Any", active=True)
    room = Room.objects.create(
        title="Room 1",
        description="desc",
        price_per_month=500,
        location="SW1A 1AA",
        category=cat,
    )

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today(),
        duration_months=6,
        status=Tenancy.STATUS_PROPOSED,
    )

    from propertylist_app.tasks import task_send_tenancy_notification
    task_send_tenancy_notification(tenancy.id, "proposed")

    # target should be tenant (because landlord proposed)
    assert OutboundNotification.objects.filter(
        user=tenant,
        template_key="tenancy.proposed",
    ).exists()


@pytest.mark.django_db
def test_still_living_check_queues_email_for_missing_side():
    NotificationTemplate.objects.create(
        key="tenancy.still_living_check",
        channel="email",
        subject="x",
        body="Open: {{ cta_url }}",
        is_active=True,
    )

    landlord = User.objects.create_user(username="land2", email="l2@example.com", password="x")
    tenant = User.objects.create_user(username="ten2", email="t2@example.com", password="x")

    cat = RoomCategorie.objects.create(name="Any2", active=True)
    room = Room.objects.create(
        title="Room 2",
        description="desc",
        price_per_month=600,
        location="SW1A 1AB",
        category=cat,
    )

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=30),
        duration_months=1,
        status=Tenancy.STATUS_ACTIVE,
        still_living_check_at=timezone.now() - timedelta(minutes=1),
        still_living_landlord_confirmed_at=None,
        still_living_tenant_confirmed_at=None,
        still_living_confirmed_at=None,
    )

    from propertylist_app.tasks import task_tenancy_prompts_sweep
    task_tenancy_prompts_sweep()

    assert OutboundNotification.objects.filter(
        user=landlord,
        template_key="tenancy.still_living_check",
    ).exists()
    assert OutboundNotification.objects.filter(
        user=tenant,
        template_key="tenancy.still_living_check",
    ).exists()


@pytest.mark.django_db
def test_review_available_queues_email():
    NotificationTemplate.objects.create(
        key="tenancy.review_available",
        channel="email",
        subject="x",
        body="Open: {{ cta_url }}",
        is_active=True,
    )

    landlord = User.objects.create_user(username="land3", email="l3@example.com", password="x")
    tenant = User.objects.create_user(username="ten3", email="t3@example.com", password="x")

    cat = RoomCategorie.objects.create(name="Any3", active=True)
    room = Room.objects.create(
        title="Room 3",
        description="desc",
        price_per_month=700,
        location="SW1A 1AC",
        category=cat,
    )

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=200),
        duration_months=6,
        status=Tenancy.STATUS_ENDED,
        review_open_at=timezone.now() - timedelta(minutes=1),
    )

    from propertylist_app.tasks import task_tenancy_prompts_sweep
    task_tenancy_prompts_sweep()

    assert OutboundNotification.objects.filter(user=landlord, template_key="tenancy.review_available").exists()
    assert OutboundNotification.objects.filter(user=tenant, template_key="tenancy.review_available").exists()


@pytest.mark.django_db
def test_tenancy_extension_proposed_queues_email():
    NotificationTemplate.objects.create(
        key="tenancy.extension.proposed",
        channel="email",
        subject="x",
        body="Open: {{ cta_url }}",
        is_active=True,
    )

    landlord = User.objects.create_user(username="land4", email="l4@example.com", password="x")
    tenant = User.objects.create_user(username="ten4", email="t4@example.com", password="x")

    cat = RoomCategorie.objects.create(name="Any4", active=True)
    room = Room.objects.create(
        title="Room 4",
        description="desc",
        price_per_month=800,
        location="SW1A 1AD",
        category=cat,
    )

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today(),
        duration_months=6,
        status=Tenancy.STATUS_CONFIRMED,
    )

    # proposer is landlord -> other party is tenant
    TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_duration_months=3,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    assert OutboundNotification.objects.filter(
        user=tenant,
        template_key="tenancy.extension.proposed",
    ).exists()