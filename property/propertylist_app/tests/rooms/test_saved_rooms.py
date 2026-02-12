import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, SavedRoom


User = get_user_model()


@pytest.mark.django_db
def test_save_room_requires_authentication():
    cat = RoomCategorie.objects.create(name="Paid", active=True)
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    room = Room.objects.create(
        title="Room 1",
        category=cat,
        price_per_month=500,
        property_owner=owner,
    )

    client = APIClient()
    url = reverse("v1:room-save-toggle", kwargs={"pk": room.pk})

    r = client.post(url, {}, format="json")

    # Depending on your project settings this may be 401 (Unauthenticated) or 403
    assert r.status_code in (401, 403)


@pytest.mark.django_db
def test_toggle_save_creates_savedroom_and_returns_saved_true():
    cat = RoomCategorie.objects.create(name="Paid", active=True)
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    user = User.objects.create_user(username="u1", password="pass123", email="u1@x.com")

    room = Room.objects.create(
        title="Room 1",
        category=cat,
        price_per_month=500,
        property_owner=owner,
    )

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("v1:room-save-toggle", kwargs={"pk": room.pk})
    r = client.post(url, {}, format="json")

    assert r.status_code in (200, 201), r.content
    assert r.data.get("ok") is True
    assert r.data.get("data", {}).get("saved") is True
    
    assert r.data.get("data", {}).get("saved_at") is not None



    assert SavedRoom.objects.filter(user=user, room=room).exists()


@pytest.mark.django_db
def test_toggle_save_again_removes_savedroom_and_returns_saved_false():
    cat = RoomCategorie.objects.create(name="Paid", active=True)
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    user = User.objects.create_user(username="u1", password="pass123", email="u1@x.com")

    room = Room.objects.create(
        title="Room 1",
        category=cat,
        price_per_month=500,
        property_owner=owner,
    )

    SavedRoom.objects.create(user=user, room=room)

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("v1:room-save-toggle", kwargs={"pk": room.pk})
    r = client.post(url, {}, format="json")

    assert r.status_code == 200, r.content
    assert r.data.get("ok") is True
    assert r.data.get("data", {}).get("saved") is False
    
    assert r.data.get("data", {}).get("saved_at") is None



    assert not SavedRoom.objects.filter(user=user, room=room).exists()


@pytest.mark.django_db
def test_my_saved_rooms_returns_only_user_saved_rooms():
    cat = RoomCategorie.objects.create(name="Paid", active=True)
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    user1 = User.objects.create_user(username="u1", password="pass123", email="u1@x.com")
    user2 = User.objects.create_user(username="u2", password="pass123", email="u2@x.com")

    room_a = Room.objects.create(
        title="Room A",
        category=cat,
        price_per_month=500,
        property_owner=owner,
    )
    room_b = Room.objects.create(
        title="Room B",
        category=cat,
        price_per_month=600,
        property_owner=owner,
    )

    SavedRoom.objects.create(user=user1, room=room_a)
    SavedRoom.objects.create(user=user2, room=room_b)

    client = APIClient()
    client.force_authenticate(user=user1)

    url = reverse("v1:my-saved-rooms")
    r = client.get(url)

    assert r.status_code == 200, r.content

    # response is a list of rooms (RoomSerializer)
    items = r.data.get("results", r.data)
    ids = [item["id"] for item in items]

    assert room_a.id in ids
    assert room_b.id not in ids


@pytest.mark.django_db
def test_is_saved_field_true_for_saved_room_in_room_detail_or_search():
    cat = RoomCategorie.objects.create(name="Paid", active=True)
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    user = User.objects.create_user(username="u1", password="pass123", email="u1@x.com")

    room = Room.objects.create(
        title="Room 1",
        category=cat,
        price_per_month=500,
        property_owner=owner,
    )

    SavedRoom.objects.create(user=user, room=room)

    client = APIClient()
    client.force_authenticate(user=user)

    # Room detail should include is_saved = True
    detail_url = reverse("v1:room-detail", kwargs={"pk": room.pk})
    r = client.get(detail_url)

    assert r.status_code in (200, 201), r.content
    detail = r.data.get("data") if isinstance(r.data, dict) and "data" in r.data else r.data
    assert detail.get("is_saved") is True



    # Optional: also confirm search includes it (if your SearchRoomsView returns RoomSerializer list)
    search_url = reverse("v1:search-rooms")
    rs = client.get(search_url, {"q": "Room 1"})
    assert rs.status_code == 200

    # Search response shape can be list or paginated dict. Support both safely:
    data = rs.data.get("results") if isinstance(rs.data, dict) and "results" in rs.data else rs.data
    if isinstance(data, list):
        match = next((x for x in data if x.get("id") == room.id), None)
        if match is not None:
            assert match.get("is_saved") is True
