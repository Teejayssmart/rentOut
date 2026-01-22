import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, MessageThread, Message


pytestmark = pytest.mark.django_db


def _mk_user(username: str) -> User:
    return User.objects.create_user(username=username, password="pass12345")


def _mk_room(owner: User, status: str = "active") -> Room:
    cat = RoomCategorie.objects.create(name="General", key=f"general-{owner.username}")
    return Room.objects.create(
        title=f"Room {owner.username}",
        description="desc",
        price_per_month="500.00",
        location="London",
        category=cat,
        property_owner=owner,
        property_type="flat",
        status=status,
    )


def test_start_thread_from_room_happy_path_creates_thread_and_optional_first_message():
    landlord = _mk_user("landlord")
    tenant = _mk_user("tenant")
    room = _mk_room(landlord, status="active")

    client = APIClient()
    client.force_authenticate(user=tenant)

    url = reverse("v1:start-thread-from-room", kwargs={"room_id": room.id})

    r = client.post(url, {"body": "Hello"}, format="json")
    assert r.status_code == 200

    # Thread exists between tenant and landlord
    thread = MessageThread.objects.filter(participants=tenant).filter(participants=landlord).first()
    assert thread is not None

    # First message created because body supplied
    assert Message.objects.filter(thread=thread, sender=tenant, body="Hello").exists()


def test_start_thread_from_room_reuses_existing_thread():
    landlord = _mk_user("landlord2")
    tenant = _mk_user("tenant2")
    room = _mk_room(landlord, status="active")

    # Pre-create thread between them
    thread = MessageThread.objects.create()
    thread.participants.set([tenant, landlord])

    client = APIClient()
    client.force_authenticate(user=tenant)

    url = reverse("v1:start-thread-from-room", kwargs={"room_id": room.id})

    r = client.post(url, {"body": "Hi again"}, format="json")
    assert r.status_code == 200

    # Still only one thread between them
    assert (
        MessageThread.objects.filter(participants=tenant)
        .filter(participants=landlord)
        .distinct()
        .count()
        == 1
    )

    # Message added to existing thread
    assert Message.objects.filter(thread=thread, body="Hi again").exists()


def test_start_thread_from_room_hidden_room_returns_404():
    landlord = _mk_user("landlord3")
    tenant = _mk_user("tenant3")
    room = _mk_room(landlord, status="hidden")  # NOT alive

    client = APIClient()
    client.force_authenticate(user=tenant)

    url = reverse("v1:start-thread-from-room", kwargs={"room_id": room.id})

    r = client.post(url, {"body": "Hello"}, format="json")
    assert r.status_code == 404


def test_start_thread_from_room_anonymous_rejected():
    landlord = _mk_user("landlord4")
    room = _mk_room(landlord, status="active")

    client = APIClient()

    url = reverse("v1:start-thread-from-room", kwargs={"room_id": room.id})

    r = client.post(url, {"body": "Hello"}, format="json")
    assert r.status_code in (401, 403)


def test_start_thread_from_room_owner_cannot_start_thread_with_self():
    landlord = _mk_user("landlord5")
    room = _mk_room(landlord, status="active")

    client = APIClient()
    client.force_authenticate(user=landlord)

    url = reverse("v1:start-thread-from-room", kwargs={"room_id": room.id})

    r = client.post(url, {"body": "Hello"}, format="json")
    assert r.status_code == 400
    assert r.data["detail"] == "You are the owner of this room; no thread needed."
