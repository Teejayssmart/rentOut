import pytest
from datetime import timedelta
from django.core import mail
from django.utils import timezone
from django.contrib.auth import get_user_model

from propertylist_app.models import Room, RoomCategorie, MessageThread, Message, Notification
from propertylist_app.services.tasks import expire_paid_listings, send_new_message_email

User = get_user_model()


@pytest.mark.django_db
def test_expire_paid_listings_hides_and_notifies_owner():
    owner = User.objects.create_user(username="landlord", password="pass", email="owner@example.com")
    cat = RoomCategorie.objects.create(name="Flat", active=True)

    # Room whose payment has expired yesterday
    room_old = Room.objects.create(
        title="Old Paid Room",
        description="...",
        price_per_month=800,
        location="SW1A 1AA",
        category=cat,
        property_owner=owner,
        paid_until=timezone.localdate() - timedelta(days=1),
        status="active",
    )
    # Room still paid
    room_ok = Room.objects.create(
        title="Fresh Paid Room",
        description="...",
        price_per_month=900,
        location="SW1A 1AA",
        category=cat,
        property_owner=owner,
        paid_until=timezone.localdate() + timedelta(days=10),
        status="active",
    )

    changed = expire_paid_listings()
    assert changed == 1

    room_old.refresh_from_db()
    room_ok.refresh_from_db()

    assert room_old.status == "hidden"
    assert room_ok.status == "active"

    # A notification is created for the owner
    notif = Notification.objects.filter(user=owner, type="listing_expired").first()
    assert notif is not None
    assert "expired" in notif.title.lower() or "expired" in notif.body.lower()


@pytest.mark.django_db
def test_send_new_message_email_uses_outbox_and_handles_missing_email():
    # Two users; only bob has an email
    alice = User.objects.create_user(username="alice", password="pass", email="")
    bob   = User.objects.create_user(username="bob",   password="pass", email="bob@example.com")

    thread = MessageThread.objects.create()
    thread.participants.set([alice, bob])

    msg = Message.objects.create(thread=thread, sender=alice, body="Hello Bob!")

    # Clear outbox just in case
    mail.outbox.clear()

    sent_count = send_new_message_email(msg.id)
    assert sent_count == 1
    assert len(mail.outbox) == 1
    email = mail.outbox[0]
    assert "New message from alice" in email.subject
    assert "Hello Bob!" in email.body
    assert email.to == ["bob@example.com"]

    # If recipient has no email, nothing is sent
    bob.email = ""
    bob.save(update_fields=["email"])
    mail.outbox.clear()

    sent_count2 = send_new_message_email(msg.id)
    assert sent_count2 == 0
    assert len(mail.outbox) == 0
