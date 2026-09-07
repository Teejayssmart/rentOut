from unittest.mock import AsyncMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from propertylist_app.models import (
    Message,
    MessageThread,
    MessageThreadState,
    UserProfile,
)
from propertylist_app.services.realtime import push_user_realtime_event


pytestmark = pytest.mark.django_db(transaction=True)


def _users_and_thread():
    User = get_user_model()

    landlord = User.objects.create_user(
        username="envelope_landlord",
        email="envelope_landlord@example.com",
        password="x",
    )
    seeker = User.objects.create_user(
        username="envelope_seeker",
        email="envelope_seeker@example.com",
        password="x",
    )

    UserProfile.objects.update_or_create(
        user=landlord,
        defaults={"role": "landlord"},
    )
    UserProfile.objects.update_or_create(
        user=seeker,
        defaults={"role": "seeker"},
    )

    thread = MessageThread.objects.create(
        landlord=landlord,
        seeker=seeker,
    )
    thread.participants.add(landlord, seeker)

    return landlord, seeker, thread


def _event_types(layer):
    return [
        call.args[1]["event_type"]
        for call in layer.group_send.await_args_list
    ]


def test_system_message_pushes_authoritative_envelope_count_for_seeker_even_when_sender_fk_is_seeker():
    """
    Regression: many viewing/tenancy/review messages are RentCrib system
    messages. They bypass the ordinary human Message signal, and the sender FK
    can legitimately be the same user who must still see the system event as
    unread. A system ``new_message`` therefore has to carry an authoritative
    unread-count companion for the seeker/tenant envelope.
    """
    _landlord, seeker, thread = _users_and_thread()

    message = Message.objects.create(
        thread=thread,
        sender=seeker,
        body="RentCrib workflow update",
        message_type=Message.TYPE_TEXT,
        metadata={
            "system_event": True,
            "event_type": "regression_system_event",
        },
    )

    layer = AsyncMock()

    with patch(
        "propertylist_app.services.realtime.get_channel_layer",
        return_value=layer,
    ):
        push_user_realtime_event(
            seeker.id,
            "new_message",
            {
                "message_id": message.id,
                "thread_id": thread.id,
                "sender_id": seeker.id,
            },
        )

    assert _event_types(layer) == [
        "new_message",
        "unread_count_changed",
    ]

    unread_event = layer.group_send.await_args_list[1].args[1]

    assert unread_event["data"] == {
        "thread_id": thread.id,
        "thread_unread_count": 1,
        "account_unread_total": 1,
    }


def test_system_message_after_permanent_delete_does_not_resurrect_envelope_count():
    """
    Keep realtime aligned with MessageStatsView: a workflow/system event alone
    must not restore a conversation this user permanently deleted.
    """
    landlord, seeker, thread = _users_and_thread()

    MessageThreadState.objects.create(
        user=seeker,
        thread=thread,
        deleted_at=timezone.now(),
        in_bin=False,
    )

    message = Message.objects.create(
        thread=thread,
        sender=landlord,
        body="Hidden RentCrib workflow update",
        message_type=Message.TYPE_TEXT,
        metadata={
            "system_event": True,
            "event_type": "hidden_regression_system_event",
        },
    )

    layer = AsyncMock()

    with patch(
        "propertylist_app.services.realtime.get_channel_layer",
        return_value=layer,
    ):
        push_user_realtime_event(
            seeker.id,
            "new_message",
            {
                "message_id": message.id,
                "thread_id": thread.id,
                "sender_id": landlord.id,
            },
        )

    assert _event_types(layer) == [
        "new_message",
        "unread_count_changed",
    ]

    unread_event = layer.group_send.await_args_list[1].args[1]

    assert unread_event["data"] == {
        "thread_id": thread.id,
        "thread_unread_count": 0,
        "account_unread_total": 0,
    }


def test_human_new_message_is_not_given_a_duplicate_service_level_unread_event():
    """
    Human chat already emits ``unread_count_changed`` from the Message signal.
    The generic realtime service must not duplicate that established path.
    """
    landlord, seeker, thread = _users_and_thread()

    message = Message.objects.create(
        thread=thread,
        sender=landlord,
        body="Ordinary human message",
        message_type=Message.TYPE_TEXT,
        metadata={},
    )

    layer = AsyncMock()

    with patch(
        "propertylist_app.services.realtime.get_channel_layer",
        return_value=layer,
    ):
        push_user_realtime_event(
            seeker.id,
            "new_message",
            {
                "message_id": message.id,
                "thread_id": thread.id,
                "sender_id": landlord.id,
            },
        )

    assert _event_types(layer) == ["new_message"]
