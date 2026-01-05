# property/propertylist_app/tests/tenancies/test_tenancy_extension_notifications.py

from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone


pytestmark = pytest.mark.django_db


def _get_model(app_label, model_name):
    return apps.get_model(app_label, model_name)


def _make_tenancy(room, landlord, tenant, *, status):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    now = timezone.now()

    return Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=90),
        duration_months=3,
        status=status,
        landlord_confirmed_at=now - timedelta(days=90),
        tenant_confirmed_at=now - timedelta(days=90),
    )


def test_extension_proposal_creates_notification_to_other_party(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    TenancyExtension = _get_model("propertylist_app", "TenancyExtension")
    Notification = _get_model("propertylist_app", "Notification")

    landlord = user_factory(username="extn_landlord1")
    tenant = user_factory(username="extn_tenant1")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ACTIVE)

    before = Notification.objects.count()

    TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_duration_months=6,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    after = Notification.objects.count()
    assert after == before + 1

    n = Notification.objects.latest("id")
    assert n.user_id == tenant.id
    assert n.type == "tenancy_extension_proposed"


def test_extension_accept_creates_notifications_for_both(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    TenancyExtension = _get_model("propertylist_app", "TenancyExtension")
    Notification = _get_model("propertylist_app", "Notification")

    landlord = user_factory(username="extn_landlord2")
    tenant = user_factory(username="extn_tenant2")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ACTIVE)

    ext = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_duration_months=6,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    before = Notification.objects.filter(type="tenancy_extension_accepted").count()

    ext.status = TenancyExtension.STATUS_ACCEPTED
    ext.save(update_fields=["status"])

    after = Notification.objects.filter(type="tenancy_extension_accepted").count()
    assert after == before + 2

    last_two = Notification.objects.filter(type="tenancy_extension_accepted").order_by("-id")[:2]
    user_ids = {n.user_id for n in last_two}
    assert user_ids == {landlord.id, tenant.id}


def test_extension_reject_notifies_proposer(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    TenancyExtension = _get_model("propertylist_app", "TenancyExtension")
    Notification = _get_model("propertylist_app", "Notification")

    landlord = user_factory(username="extn_landlord3")
    tenant = user_factory(username="extn_tenant3")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ACTIVE)

    # tenant proposes this time
    ext = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=tenant,
        proposed_duration_months=6,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    before = Notification.objects.filter(type="tenancy_extension_rejected").count()

    ext.status = TenancyExtension.STATUS_REJECTED
    ext.save(update_fields=["status"])

    after = Notification.objects.filter(type="tenancy_extension_rejected").count()
    assert after == before + 1

    n = Notification.objects.filter(type="tenancy_extension_rejected").latest("id")
    assert n.user_id == tenant.id



def test_extension_status_save_without_change_does_not_duplicate_notifications(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    TenancyExtension = _get_model("propertylist_app", "TenancyExtension")
    Notification = _get_model("propertylist_app", "Notification")

    landlord = user_factory(username="extn_landlord_dup")
    tenant = user_factory(username="extn_tenant_dup")
    room = room_factory(property_owner=landlord)

    tenancy = _make_tenancy(room, landlord, tenant, status=Tenancy.STATUS_ACTIVE)

    ext = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_duration_months=6,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    before = Notification.objects.filter(type="tenancy_extension_accepted").count()

    ext.status = TenancyExtension.STATUS_ACCEPTED
    ext.save(update_fields=["status"])

    mid = Notification.objects.filter(type="tenancy_extension_accepted").count()
    assert mid == before + 2

    # saving again with same status should NOT create more
    ext.status = TenancyExtension.STATUS_ACCEPTED
    ext.save(update_fields=["status"])

    after = Notification.objects.filter(type="tenancy_extension_accepted").count()
    assert after == mid
