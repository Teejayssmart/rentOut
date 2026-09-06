import pytest
from django.utils import timezone
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.models import (
    Notification,
    Review,
    Room,
    RoomCategorie,
    Tenancy,
    TenancyExtension,
)


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
        property_owner=landlord,
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
    
    NotificationTemplate.objects.create(
        key="tenancy.still_living_check_landlord",
        channel="email",
        subject="x",
        body="Open: {{ cta_url }}",
        is_active=True,
    )

    landlord = User.objects.create_user(username="land2", email="l2@example.com", password="x")
    tenant = User.objects.create_user(username="ten2", email="t2@example.com", password="x")

    cat = RoomCategorie.objects.create(name="Any2", active=True)
    room = Room.objects.create(
        property_owner=landlord,
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
        template_key="tenancy.still_living_check_landlord",
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
        property_owner=landlord,
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
def test_review_available_not_queued_twice():
    NotificationTemplate.objects.create(
        key="tenancy.review_available",
        channel="email",
        subject="Review available",
        body="Open: {{ cta_url }}",
        is_active=True,
    )

    landlord = User.objects.create_user(
        username="landlord_dup",
        email="landlord_dup@example.com",
        password="password123",
    )
    tenant = User.objects.create_user(
        username="tenant_dup",
        email="tenant_dup@example.com",
        password="password123",
    )

    cat = RoomCategorie.objects.create(
        name="Duplicate Review Category",
        active=True,
    )

    room = Room.objects.create(
        property_owner=landlord,
        title="Duplicate Review Test Room",
        description="desc",
        price_per_month=800,
        location="SW1A 1AE",
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
    task_tenancy_prompts_sweep()

    assert Notification.objects.filter(
        user=landlord,
        type="review_available",
        target_type="tenancy_review",
        target_id=tenancy.id,
    ).count() == 1

    assert Notification.objects.filter(
        user=tenant,
        type="review_available",
        target_type="tenancy_review",
        target_id=tenancy.id,
    ).count() == 1

    assert OutboundNotification.objects.filter(
        user=landlord,
        template_key="tenancy.review_available",
    ).count() == 1

    assert OutboundNotification.objects.filter(
        user=tenant,
        template_key="tenancy.review_available",
    ).count() == 1







@pytest.mark.django_db
def test_tenancy_extension_proposed_queues_email():
    NotificationTemplate.objects.create(
        key="tenancy.extension.proposed",
        channel="email",
        subject="x",
        body="Open: {{ cta_url }}",
        is_active=True,
    )

    landlord = User.objects.create_user(
        username="land4",
        first_name="Landlord",
        email="l4@example.com",
        password="x",
    )
    tenant = User.objects.create_user(
        username="ten4",
        first_name="Tenant",
        email="t4@example.com",
        password="x",
    )

    cat = RoomCategorie.objects.create(
        name="Any4",
        active=True,
    )
    room = Room.objects.create(
        property_owner=landlord,
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

    renewal_start_date = (
        date.today() + timedelta(days=30)
    )

    extension = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_start_date=renewal_start_date,
        proposed_duration_months=7,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    email = OutboundNotification.objects.get(
        user=tenant,
        template_key="tenancy.extension.proposed",
    )

    assert email.context["tenancy_id"] == tenancy.id
    assert email.context["extension_id"] == extension.id
    assert email.context["room_title"] == room.title
    assert (
        email.context["proposed_start_date"]
        == renewal_start_date.isoformat()
    )
    assert (
        email.context["proposed_duration_months"]
        == 7
    )
    assert email.context["proposer_name"] == "Landlord"
    assert email.context["deep_link"] == (
        f"/app/tenancies/{tenancy.id}"
    )


@pytest.mark.django_db
def test_tenancy_extension_accepted_queues_email_for_both_parties():
    NotificationTemplate.objects.create(
        key="tenancy.extension.proposed",
        channel="email",
        subject="x",
        body="Open: {{ cta_url }}",
        is_active=True,
    )
    NotificationTemplate.objects.create(
        key="tenancy.extension.accepted",
        channel="email",
        subject="x",
        body=(
            "{{ proposed_start_date }} "
            "{{ proposed_duration_months }}"
        ),
        is_active=True,
    )

    landlord = User.objects.create_user(
        username="land_extension_accepted",
        first_name="Landlord",
        email="land-accepted@example.com",
        password="x",
    )
    tenant = User.objects.create_user(
        username="tenant_extension_accepted",
        first_name="Tenant",
        email="tenant-accepted@example.com",
        password="x",
    )

    cat = RoomCategorie.objects.create(
        name="Extension accepted category",
        active=True,
    )
    room = Room.objects.create(
        property_owner=landlord,
        title="Accepted renewal room",
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
        status=Tenancy.STATUS_ACTIVE,
    )

    renewal_start_date = (
        date.today() + timedelta(days=30)
    )

    extension = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_start_date=renewal_start_date,
        proposed_duration_months=7,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    extension.status = (
        TenancyExtension.STATUS_ACCEPTED
    )
    extension.responded_at = timezone.now()
    extension.save(
        update_fields=[
            "status",
            "responded_at",
        ]
    )

    landlord_email = OutboundNotification.objects.get(
        user=landlord,
        template_key="tenancy.extension.accepted",
    )
    tenant_email = OutboundNotification.objects.get(
        user=tenant,
        template_key="tenancy.extension.accepted",
    )

    for email in (
        landlord_email,
        tenant_email,
    ):
        assert (
            email.context["extension_id"]
            == extension.id
        )
        assert (
            email.context["proposed_start_date"]
            == renewal_start_date.isoformat()
        )
        assert (
            email.context["proposed_duration_months"]
            == 7
        )

        # Both landlord and tenant accepted-extension emails must
        # link directly to the updated tenancy information page.
        cta_url = email.context["cta_url"]

        assert f"/tenancies/{tenancy.id}" in cta_url
        assert "/login?next=" not in cta_url
        assert "/app/tenancies/" not in cta_url

    assert OutboundNotification.objects.filter(
        template_key="tenancy.extension.accepted",
    ).count() == 2


@pytest.mark.django_db
def test_tenancy_extension_rejected_queues_email_for_proposer():
    NotificationTemplate.objects.create(
        key="tenancy.extension.proposed",
        channel="email",
        subject="x",
        body="Open: {{ cta_url }}",
        is_active=True,
    )
    NotificationTemplate.objects.create(
        key="tenancy.extension.rejected",
        channel="email",
        subject="x",
        body=(
            "{{ proposed_start_date }} "
            "{{ proposed_duration_months }}"
        ),
        is_active=True,
    )

    landlord = User.objects.create_user(
        username="land_extension_rejected",
        first_name="Landlord",
        email="land-rejected@example.com",
        password="x",
    )
    tenant = User.objects.create_user(
        username="tenant_extension_rejected",
        first_name="Tenant",
        email="tenant-rejected@example.com",
        password="x",
    )

    cat = RoomCategorie.objects.create(
        name="Extension rejected category",
        active=True,
    )
    room = Room.objects.create(
        property_owner=landlord,
        title="Rejected renewal room",
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
        status=Tenancy.STATUS_ACTIVE,
    )

    renewal_start_date = (
        date.today() + timedelta(days=30)
    )

    extension = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_start_date=renewal_start_date,
        proposed_duration_months=7,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    extension.status = (
        TenancyExtension.STATUS_REJECTED
    )
    extension.responded_at = timezone.now()
    extension.save(
        update_fields=[
            "status",
            "responded_at",
        ]
    )

    email = OutboundNotification.objects.get(
        user=landlord,
        template_key="tenancy.extension.rejected",
    )

    assert email.context["extension_id"] == extension.id
    assert (
        email.context["proposed_start_date"]
        == renewal_start_date.isoformat()
    )
    assert (
        email.context["proposed_duration_months"]
        == 7
    )

    assert not OutboundNotification.objects.filter(
        user=tenant,
        template_key="tenancy.extension.rejected",
    ).exists()
    
@pytest.mark.django_db
def test_review_revealed_email_cta_preserves_recipient_role():
    NotificationTemplate.objects.create(
        key="tenancy.review_revealed",
        channel="email",
        subject="Review revealed",
        body="Open: {{ cta_url }}",
        is_active=True,
    )

    landlord = User.objects.create_user(
        username="review_revealed_landlord",
        email="review_revealed_landlord@example.com",
        password="password123",
    )
    tenant = User.objects.create_user(
        username="review_revealed_tenant",
        email="review_revealed_tenant@example.com",
        password="password123",
    )

    cat = RoomCategorie.objects.create(
        name="Review Revealed Category",
        active=True,
    )

    room = Room.objects.create(
        property_owner=landlord,
        title="Review Revealed Room",
        description="desc",
        price_per_month=800,
        location="SW1A 1AA",
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
        review_open_at=timezone.now() - timedelta(days=30),
    )

    landlord_review = Review.objects.create(
        tenancy=tenancy,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        overall_rating=4,
        notes="Landlord review",
        active=False,
        reveal_at=timezone.now() - timedelta(minutes=1),
    )

    tenant_review = Review.objects.create(
        tenancy=tenancy,
        reviewer=landlord,
        reviewee=tenant,
        role=Review.ROLE_LANDLORD_TO_TENANT,
        overall_rating=4,
        notes="Tenant review",
        active=False,
        reveal_at=timezone.now() - timedelta(minutes=1),
    )

    from propertylist_app.tasks import task_tenancy_prompts_sweep

    task_tenancy_prompts_sweep()

    landlord_email = OutboundNotification.objects.get(
        user=landlord,
        template_key="tenancy.review_revealed",
    )
    tenant_email = OutboundNotification.objects.get(
        user=tenant,
        template_key="tenancy.review_revealed",
    )

    assert (
        f"/reviews/{landlord_review.id}?role=landlord"
        in landlord_email.context["cta_url"]
    )
    assert (
        f"/reviews/{tenant_review.id}?role=seeker"
        in tenant_email.context["cta_url"]
    )    