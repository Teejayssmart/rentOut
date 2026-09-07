import pytest
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.api.serializers import MessageSerializer, NotificationSerializer
from propertylist_app.models import Booking, Message, Notification, Tenancy
from propertylist_app.notifications.tasks import notify_completed_viewings
from propertylist_app.services.message_threads import get_or_create_canonical_thread


pytestmark = pytest.mark.django_db


FORBIDDEN_LIFECYCLE_ACTIONS = {
    "still_living",
    "renew",
    "extend",
    "leave_review",
}


def _request_for(user):
    request = APIRequestFactory().get("/")
    request.user = user
    return request


def _serialize_message_for(message, user):
    return MessageSerializer(
        message,
        context={"request": _request_for(user)},
    ).data


def _serialize_notification_for(notification, user):
    return NotificationSerializer(
        notification,
        context={"request": _request_for(user)},
    ).data


def _make_completed_booking(*, seeker, room):
    now = timezone.now()
    return Booking.objects.create(
        user=seeker,
        room=room,
        start=now - timezone.timedelta(minutes=11),
        end=now - timezone.timedelta(minutes=1),
        status=Booking.STATUS_ACTIVE,
        is_deleted=False,
        canceled_at=None,
    )


def _seed_completed_templates():
    NotificationTemplate.objects.create(
        key="booking.completed",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        subject="Viewing completed",
        body="Open: {{ cta_url }}",
        is_active=True,
    )
    NotificationTemplate.objects.create(
        key="booking.completed_landlord",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        subject="Viewing completed",
        body="Open: {{ cta_url }}",
        is_active=True,
    )


def test_viewing_completed_exposes_only_update_tenancy_to_landlord_and_seeker(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="viewing_completed_landlord")
    seeker = user_factory(username="viewing_completed_seeker")
    room = room_factory(property_owner=landlord)

    booking = _make_completed_booking(
        seeker=seeker,
        room=room,
    )

    # Booking creation already establishes/reuses the canonical room thread.
    # Reuse that same application contract instead of creating a duplicate
    # landlord/seeker/room thread in the fixture.
    thread = get_or_create_canonical_thread(
        landlord=landlord,
        seeker=seeker,
        room=room,
    )

    message = Message.objects.create(
        thread=thread,
        sender=landlord,
        body="Viewing completed",
        message_type=Message.TYPE_TEXT,
        metadata={
            "system_event": True,
            "event_type": "booking_completed",
            "booking_id": booking.id,
            "room_id": room.id,
        },
    )

    for user in (landlord, seeker):
        payload = _serialize_message_for(message, user)

        assert payload["available_actions"] == ["update_tenancy"]
        assert FORBIDDEN_LIFECYCLE_ACTIONS.isdisjoint(
            payload["available_actions"]
        )


def test_viewing_completed_email_bell_and_envelope_stay_in_timer_one_contract(
    user_factory,
    room_factory,
):
    """
    Timer 1 is the viewing-completed workflow only.

    It may offer Update tenancy information, but it must not create or expose
    Timer 2 (still-living/renewal) or Timer 3 (review) actions/notifications.
    The intentionally accelerated 10-minute QA tenancy timers are separate and
    are not changed by this regression fixture.
    """
    landlord = user_factory(username="viewing_channels_landlord")
    seeker = user_factory(username="viewing_channels_seeker")
    room = room_factory(property_owner=landlord)
    booking = _make_completed_booking(
        seeker=seeker,
        room=room,
    )

    # A tenancy can already exist in QA while we exercise Timer 1. Give it a
    # future QA Timer-2 value so this test proves notify_completed_viewings()
    # does not mutate or shortcut that separate lifecycle.
    timer_two_before = timezone.now() + timezone.timedelta(minutes=10)
    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=seeker,
        proposed_by=landlord,
        move_in_date=timezone.localdate(),
        duration_months=6,
        status=Tenancy.STATUS_ACTIVE,
        landlord_confirmed_at=timezone.now(),
        tenant_confirmed_at=timezone.now(),
        still_living_check_at=timer_two_before,
        review_open_at=timezone.now() + timezone.timedelta(minutes=20),
        review_deadline_at=timezone.now() + timezone.timedelta(days=60),
    )

    _seed_completed_templates()

    # This task's contract is its notification side effects; it does not
    # currently return a processed-count value. Do not change production
    # behaviour merely to satisfy a fixture assumption.
    notify_completed_viewings()

    tenancy.refresh_from_db()
    assert tenancy.still_living_check_at == timer_two_before

    envelope = Message.objects.get(
        metadata__event_type="booking_completed",
        metadata__booking_id=booking.id,
    )
    assert envelope.metadata["booking_id"] == booking.id
    assert envelope.metadata["room_id"] == room.id

    for user in (landlord, seeker):
        message_payload = _serialize_message_for(envelope, user)
        assert message_payload["available_actions"] == ["update_tenancy"]
        assert FORBIDDEN_LIFECYCLE_ACTIONS.isdisjoint(
            message_payload["available_actions"]
        )

    seeker_bell = Notification.objects.get(
        user=seeker,
        type="booking_completed",
    )
    landlord_bell = Notification.objects.get(
        user=landlord,
        type="booking_completed_landlord",
    )

    seeker_bell_payload = _serialize_notification_for(seeker_bell, seeker)
    landlord_bell_payload = _serialize_notification_for(
        landlord_bell,
        landlord,
    )

    assert seeker_bell_payload["type"] == "booking_completed"
    assert landlord_bell_payload["type"] == "booking_completed_landlord"

    # Bell rows are viewing-completed events, never later tenancy lifecycle
    # notifications.
    assert not Notification.objects.filter(
        user__in=[landlord, seeker],
        type__in=[
            "tenancy_still_living_check",
            "tenancy_extension_proposed",
            "review_available",
        ],
    ).exists()

    seeker_email = OutboundNotification.objects.get(
        user=seeker,
        template_key="booking.completed",
        context__booking_id=booking.id,
    )
    landlord_email = OutboundNotification.objects.get(
        user=landlord,
        template_key="booking.completed_landlord",
        context__booking_id=booking.id,
    )

    assert seeker_email.context["booking_id"] == booking.id
    assert landlord_email.context["booking_id"] == booking.id

    # Both emails must remain Timer-1 emails. They must not masquerade as a
    # still-living, renewal or review delivery.
    assert seeker_email.template_key == "booking.completed"
    assert landlord_email.template_key == "booking.completed_landlord"
