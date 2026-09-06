import pytest
from unittest.mock import patch
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from propertylist_app.models import (
    MessageThread,
    Message,
    MessageRead,
    MessageThreadState,
    Room,
    RoomCategorie,
    Notification as InAppNotification,
)
from notifications.models import NotificationTemplate, OutboundNotification
from django.utils import timezone
from datetime import timedelta

pytestmark = pytest.mark.django_db

def make_users(n=2):
    U = get_user_model()
    return [U.objects.create_user(username=f"u{i}", email=f"u{i}@ex.com", password="x", first_name=f"U{i}") for i in range(n)]

def test_new_message_signal_queues_emails_and_inapp():
    sender, recipient = make_users(2)
    t = MessageThread.objects.create()
    t.participants.add(sender, recipient)

    # Email template for message.new
    NotificationTemplate.objects.create(
        key="message.new", channel="email", subject="New from {{ sender.name }}", body="Hi {{ user.first_name }}", is_active=True
    )

    # Avoid actually sending emails when the task runs later
    with patch("notifications.services.send_mail", return_value=1):
        msg = Message.objects.create(thread=t, sender=sender, body="Hello there")

    # Outbound for recipient (not sender)
    queued = OutboundNotification.objects.filter(template_key="message.new", user=recipient)
    assert queued.count() == 1

    # In-app notification created
    assert InAppNotification.objects.filter(user=recipient, thread=t, message=msg).exists()
    
    
def test_new_message_signal_emits_realtime_message_and_notification():
    sender, recipient = make_users(2)

    thread = MessageThread.objects.create()
    thread.participants.add(sender, recipient)

    NotificationTemplate.objects.create(
        key="message.new",
        channel="email",
        subject="New message",
        body="Message",
        is_active=True,
    )

    with patch(
        "propertylist_app.signals.push_user_realtime_event"
    ) as realtime:
        msg = Message.objects.create(
            thread=thread,
            sender=sender,
            body="Realtime test message",
            message_type=Message.TYPE_TEXT,
        )

    realtime.assert_any_call(
        recipient.id,
        "new_message",
        {
            "message_id": msg.id,
            "thread_id": thread.id,
            "sender_id": sender.id,
        },
    )

    realtime.assert_any_call(
        recipient.id,
        "unread_count_changed",
        {
            "thread_id": thread.id,
            "thread_unread_count": 1,
            "account_unread_total": 1,
        },
    )

    realtime.assert_any_call(
        recipient.id,
        "new_notification",
        {
            "kind": "message",
            "message_id": msg.id,
            "thread_id": thread.id,
        },
    )

    assert realtime.call_count == 3

    assert InAppNotification.objects.filter(
        user=recipient,
        thread=thread,
        message=msg,
    ).exists()

    assert OutboundNotification.objects.filter(
        user=recipient,
        template_key="message.new",
    ).count() == 1
    
    
def test_new_message_realtime_delivery_ignores_notification_preference():
    from propertylist_app.models import UserProfile

    sender, recipient = make_users(2)

    thread = MessageThread.objects.create()
    thread.participants.add(sender, recipient)

    profile, _ = UserProfile.objects.get_or_create(
        user=recipient
    )
    profile.notify_messages = False
    profile.save(update_fields=["notify_messages"])

    with patch(
        "propertylist_app.signals.push_user_realtime_event"
    ) as realtime:
        msg = Message.objects.create(
            thread=thread,
            sender=sender,
            body="Realtime delivery must remain enabled",
            message_type=Message.TYPE_TEXT,
        )

    realtime.assert_any_call(
        recipient.id,
        "new_message",
        {
            "message_id": msg.id,
            "thread_id": thread.id,
            "sender_id": sender.id,
        },
    )

    realtime.assert_any_call(
        recipient.id,
        "unread_count_changed",
        {
            "thread_id": thread.id,
            "thread_unread_count": 1,
            "account_unread_total": 1,
        },
    )

    assert realtime.call_count == 2

    assert not InAppNotification.objects.filter(
        user=recipient,
        thread=thread,
        message=msg,
    ).exists()

    assert not OutboundNotification.objects.filter(
        user=recipient,
        template_key="message.new",
    ).exists()
    

def test_new_booking_signal_queues_owner_and_booker_emails():
    owner, booker = make_users(2)
    cat = RoomCategorie.objects.create(name="General", key="general", slug="general", active=True)
    room = Room.objects.create(
        title="Room A", description="d", price_per_month=500, location="SO14", category=cat,
        property_owner=owner, property_type="flat"
    )

    for key in ("booking.new", "booking.confirmation"):
        NotificationTemplate.objects.create(key=key, channel="email", subject="S", body="B", is_active=True)

    from propertylist_app.models import Booking
    with patch("notifications.services.send_mail", return_value=1):
            start = timezone.now()
            end = start + timedelta(hours=1)

            booking = Booking.objects.create(
                user=booker,
                room=room,
                start=start,
                end=end,
            )
            
    thread = (
        MessageThread.objects
        .filter(room=room)
        .filter(participants=owner)
        .filter(participants=booker)
        .distinct()
        .get()
    )

    assert thread.landlord_id == owner.id
    assert thread.seeker_id == booker.id        

    assert OutboundNotification.objects.filter(template_key="booking.new", user=owner).exists()
    assert OutboundNotification.objects.filter(template_key="booking.confirmation", user=booker).exists()
    
    
def test_new_message_restores_recipient_binned_thread_and_returns_it_in_messages_api():
    sender, recipient = make_users(2)

    thread = MessageThread.objects.create()
    thread.participants.add(sender, recipient)

    MessageThreadState.objects.create(
        user=recipient,
        thread=thread,
        in_bin=True,
    )

    # Confirm the thread starts in the recipient's bin.
    state = MessageThreadState.objects.get(
        user=recipient,
        thread=thread,
    )
    assert state.in_bin is True

    # A genuine incoming message should restore the conversation.
    Message.objects.create(
        thread=thread,
        sender=sender,
        body="Fresh incoming message",
        message_type=Message.TYPE_TEXT,
    )

    state.refresh_from_db()

    # The thread must automatically leave the recipient's bin.
    assert state.in_bin is False

    # It must also be returned by the normal Messages API again.
    client = APIClient()
    client.force_authenticate(user=recipient)

    response = client.get(
        "/api/v1/messages/threads/",
        {"limit": 100},
    )

    assert response.status_code == 200

    payload = response.data.get("data", [])

    assert any(
        item["id"] == thread.id
        for item in payload
    )
    
    
def test_new_message_restores_permanently_deleted_thread_without_old_history():
    sender, recipient = make_users(2)

    thread = MessageThread.objects.create()
    thread.participants.add(sender, recipient)

    old_message = Message.objects.create(
        thread=thread,
        sender=sender,
        body="Old message before permanent delete",
        message_type=Message.TYPE_TEXT,
    )

    state, _ = MessageThreadState.objects.get_or_create(
        user=recipient,
        thread=thread,
    )
    state.deleted_at = timezone.now()
    state.in_bin = False
    state.save(update_fields=["deleted_at", "in_bin", "updated_at"])

    client = APIClient()
    client.force_authenticate(user=recipient)

    response = client.get(
        "/api/v1/messages/threads/",
        {"limit": 100},
    )

    assert response.status_code == 200

    payload = response.data.get("data", [])

    assert not any(
        item["id"] == thread.id
        for item in payload
    )

    new_message = Message.objects.create(
        thread=thread,
        sender=sender,
        body="Fresh message after permanent delete",
        message_type=Message.TYPE_TEXT,
    )

    state.refresh_from_db()

    assert state.deleted_at is not None
    assert state.in_bin is False

    response = client.get(
        "/api/v1/messages/threads/",
        {"limit": 100},
    )

    assert response.status_code == 200

    payload = response.data.get("data", [])

    assert any(
        item["id"] == thread.id
        for item in payload
    )

    response = client.get(
        f"/api/v1/messages/threads/{thread.id}/messages/",
        {"limit": 100},
    )

    assert response.status_code == 200

    payload = response.data.get("data", [])

    message_ids = {
        item["id"]
        for item in payload
    }

    assert new_message.id in message_ids
    assert old_message.id not in message_ids    
    
    
    
def test_thread_mark_read_emits_realtime_read_and_unread_count(
    django_assert_max_num_queries,
):
    sender, reader = make_users(2)

    thread = MessageThread.objects.create()
    thread.participants.add(sender, reader)

    msg1 = Message.objects.create(
        thread=thread,
        sender=sender,
        body="First unread",
        message_type=Message.TYPE_TEXT,
    )
    msg2 = Message.objects.create(
        thread=thread,
        sender=sender,
        body="Second unread",
        message_type=Message.TYPE_TEXT,
    )

    client = APIClient()
    client.force_authenticate(user=reader)

    with django_assert_max_num_queries(10):
        with patch(
            "propertylist_app.api.views.messaging.push_user_realtime_event"
        ) as realtime:
            response = client.post(
                f"/api/v1/messages/threads/{thread.id}/read/"
            )

    assert response.status_code == 200

    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["marked"] == 2
    
    assert payload["data"]["thread_unread_count"] == 0
    assert payload["data"]["account_unread_total"] == 0

    assert MessageRead.objects.filter(
        user=reader,
        message__in=[msg1, msg2],
    ).count() == 2

    realtime.assert_any_call(
        sender.id,
        "message_read",
        {
            "thread_id": thread.id,
            "reader_id": reader.id,
            "message_ids": [msg1.id, msg2.id],
        },
    )

    realtime.assert_any_call(
        reader.id,
        "unread_count_changed",
        {
            "thread_id": thread.id,
            "thread_unread_count": 0,
            "account_unread_total": 0,
        },
    )

    assert realtime.call_count == 2    
    
    
def test_bulk_thread_mark_read_updates_realtime_and_account_total(
    django_assert_max_num_queries,
):
    sender, reader = make_users(2)

    first_thread = MessageThread.objects.create()
    first_thread.participants.add(sender, reader)

    second_thread = MessageThread.objects.create()
    second_thread.participants.add(sender, reader)

    remaining_thread = MessageThread.objects.create()
    remaining_thread.participants.add(sender, reader)

    first_messages = [
        Message.objects.create(
            thread=first_thread,
            sender=sender,
            body=f"First thread {index}",
            message_type=Message.TYPE_TEXT,
        )
        for index in range(2)
    ]

    second_messages = [
        Message.objects.create(
            thread=second_thread,
            sender=sender,
            body=f"Second thread {index}",
            message_type=Message.TYPE_TEXT,
        )
        for index in range(2)
    ]

    remaining_message = Message.objects.create(
        thread=remaining_thread,
        sender=sender,
        body="Must remain unread",
        message_type=Message.TYPE_TEXT,
    )

    client = APIClient()
    client.force_authenticate(user=reader)

    with django_assert_max_num_queries(12):
        with patch(
            "propertylist_app.api.views.messaging.push_user_realtime_event"
        ) as realtime:
            response = client.post(
                "/api/v1/messages/threads/read/",
                {
                    "thread_ids": [
                        first_thread.id,
                        second_thread.id,
                    ],
                },
                format="json",
            )

    assert response.status_code == 200

    payload = response.json()
    data = payload["data"]

    assert data["marked"] == 4
    assert set(data["thread_ids"]) == {
        first_thread.id,
        second_thread.id,
    }
    assert data["account_unread_total"] == 1

    assert MessageRead.objects.filter(
        user=reader,
        message__in=first_messages + second_messages,
    ).count() == 4

    assert not MessageRead.objects.filter(
        user=reader,
        message=remaining_message,
    ).exists()

    realtime.assert_any_call(
        reader.id,
        "unread_count_changed",
        {
            "thread_ids": data["thread_ids"],
            "thread_unread_counts": {
                str(thread_id): 0
                for thread_id in data["thread_ids"]
            },
            "account_unread_total": 1,
        },
    )  
    
def test_new_message_realtime_is_partitioned_by_active_role():
    from propertylist_app.models import UserProfile

    sender, recipient = make_users(2)

    thread = MessageThread.objects.create(
        landlord=recipient,
        seeker=sender,
    )
    thread.participants.add(sender, recipient)

    NotificationTemplate.objects.create(
        key="message.new",
        channel="email",
        subject="New message",
        body="Message",
        is_active=True,
    )

    profile, _ = UserProfile.objects.get_or_create(
        user=recipient
    )

    # Recipient is the landlord in this thread but is
    # currently using RentCrib in seeker mode.
    profile.role = "seeker"
    profile.save(update_fields=["role"])

    with patch(
        "propertylist_app.signals.push_user_realtime_event"
    ) as realtime:
        hidden_message = Message.objects.create(
            thread=thread,
            sender=sender,
            body="Landlord message while seeker mode is active",
            message_type=Message.TYPE_TEXT,
        )

    # The message and notification must still be stored.
    assert Message.objects.filter(
        pk=hidden_message.pk,
    ).exists()

    hidden_notification = InAppNotification.objects.get(
        user=recipient,
        thread=thread,
        message=hidden_message,
    )

    assert (
        hidden_notification.audience
        == InAppNotification.Audience.LANDLORD
    )

    # Email remains independent of the currently selected role.
    assert OutboundNotification.objects.filter(
        user=recipient,
        template_key="message.new",
    ).count() == 1

    # But no landlord realtime event may leak into seeker mode.
    assert realtime.call_count == 0

    # Switch the same account back to landlord mode.
    profile.role = "landlord"
    profile.save(update_fields=["role"])

    with patch(
        "propertylist_app.signals.push_user_realtime_event"
    ) as realtime:
        visible_message = Message.objects.create(
            thread=thread,
            sender=sender,
            body="Landlord message while landlord mode is active",
            message_type=Message.TYPE_TEXT,
        )

    realtime.assert_any_call(
        recipient.id,
        "new_message",
        {
            "message_id": visible_message.id,
            "thread_id": thread.id,
            "sender_id": sender.id,
        },
    )

    realtime.assert_any_call(
        recipient.id,
        "unread_count_changed",
        {
            "thread_id": thread.id,
            "thread_unread_count": 2,
            "account_unread_total": 2,
        },
    )

    realtime.assert_any_call(
        recipient.id,
        "new_notification",
        {
            "kind": "message",
            "message_id": visible_message.id,
            "thread_id": thread.id,
        },
    )

    assert realtime.call_count == 3

    # Switching roles did not delete the first message.
    assert Message.objects.filter(
        id__in=[
            hidden_message.id,
            visible_message.id,
        ]
    ).count() == 2      
    
    
def test_delete_forever_endpoint_sets_per_user_deleted_at():
    user, other = make_users(2)

    thread = MessageThread.objects.create()
    thread.participants.add(user, other)

    Message.objects.create(
        thread=thread,
        sender=other,
        body="Message before delete",
        message_type=Message.TYPE_TEXT,
    )

    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        f"/api/v1/messages/threads/{thread.id}/delete/",
        {},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["thread_id"] == thread.id
    assert response.data["deleted"] is True

    state = MessageThreadState.objects.get(
        user=user,
        thread=thread,
    )

    assert state.deleted_at is not None
    assert state.in_bin is False

    assert not MessageThreadState.objects.filter(
        user=other,
        thread=thread,
        deleted_at__isnull=False,
    ).exists()


def test_bulk_delete_forever_endpoint_sets_cutoff_for_selected_threads():
    user, other = make_users(2)

    thread_one = MessageThread.objects.create()
    thread_one.participants.add(user, other)

    thread_two = MessageThread.objects.create()
    thread_two.participants.add(user, other)

    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/v1/messages/threads/delete/",
        {
            "thread_ids": [
                thread_one.id,
                thread_two.id,
            ]
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["deleted"] == 2

    states = MessageThreadState.objects.filter(
        user=user,
        thread_id__in=[
            thread_one.id,
            thread_two.id,
        ],
    )

    assert states.count() == 2
    assert all(
        state.deleted_at is not None
        for state in states
    )

    assert not MessageThreadState.objects.filter(
        user=other,
        thread_id__in=[
            thread_one.id,
            thread_two.id,
        ],
        deleted_at__isnull=False,
    ).exists()  
    
    
    
def test_system_message_does_not_restore_permanently_deleted_thread():
    sender, recipient = make_users(2)

    thread = MessageThread.objects.create()
    thread.participants.add(sender, recipient)

    state = MessageThreadState.objects.create(
        user=recipient,
        thread=thread,
        deleted_at=timezone.now(),
        in_bin=False,
    )

    Message.objects.create(
        thread=thread,
        sender=sender,
        body="System event after delete",
        message_type=Message.TYPE_TEXT,
        metadata={"system_event": True},
    )

    state.refresh_from_db()

    assert state.deleted_at is not None

    client = APIClient()
    client.force_authenticate(user=recipient)

    response = client.get(
        "/api/v1/messages/threads/",
        {"limit": 100},
    )

    assert response.status_code == 200

    payload = response.data.get("data", [])

    assert not any(
        item["id"] == thread.id
        for item in payload
    )      
    
    

    
    
def test_delete_forever_does_not_hide_history_from_other_participant():
    user, other = make_users(2)

    thread = MessageThread.objects.create()
    thread.participants.add(user, other)

    message = Message.objects.create(
        thread=thread,
        sender=other,
        body="Shared history remains for other participant",
        message_type=Message.TYPE_TEXT,
    )

    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        f"/api/v1/messages/threads/{thread.id}/delete/",
        {},
        format="json",
    )

    assert response.status_code == 200

    client.force_authenticate(user=other)

    response = client.get(
        f"/api/v1/messages/threads/{thread.id}/messages/",
        {"limit": 100},
    )

    assert response.status_code == 200

    payload = response.data.get("data", [])

    assert any(
        item["id"] == message.id
        for item in payload
    )     
    
    
def test_system_message_after_delete_does_not_increase_hidden_thread_unread_total():
    sender, recipient = make_users(2)

    thread = MessageThread.objects.create()
    thread.participants.add(sender, recipient)

    state = MessageThreadState.objects.create(
        user=recipient,
        thread=thread,
        deleted_at=timezone.now(),
        in_bin=False,
    )

    Message.objects.create(
        thread=thread,
        sender=sender,
        body="Hidden system event",
        message_type=Message.TYPE_TEXT,
        metadata={"system_event": True},
    )

    state.refresh_from_db()
    assert state.deleted_at is not None

    client = APIClient()
    client.force_authenticate(user=recipient)

    response = client.get("/api/v1/messages/stats/")

    assert response.status_code == 200
    assert response.data["total_unread"] == 0
    
    
def test_mark_read_after_delete_does_not_count_hidden_system_message_in_account_total():
    sender, recipient = make_users(2)

    thread = MessageThread.objects.create()
    thread.participants.add(sender, recipient)

    MessageThreadState.objects.create(
        user=recipient,
        thread=thread,
        deleted_at=timezone.now(),
        in_bin=False,
    )

    Message.objects.create(
        thread=thread,
        sender=sender,
        body="Hidden system event after permanent delete",
        message_type=Message.TYPE_TEXT,
        metadata={"system_event": True},
    )

    client = APIClient()
    client.force_authenticate(user=recipient)

    response = client.post(
        f"/api/v1/messages/threads/{thread.id}/read/",
        {},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["data"]["account_unread_total"] == 0       