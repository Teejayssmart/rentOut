import pytest
from django.urls import reverse
from propertylist_app.models import RoomCategorie, Room

pytestmark = pytest.mark.django_db


@pytest.fixture
def default_category():
    obj = RoomCategorie.objects.first()
    if obj:
        return obj
    return RoomCategorie.objects.create(
        name="Default",
        key="default",
        slug="default",
        active=True,
    )


@pytest.fixture
def draft_room(auth_client, user, default_category):
    payload = {
        "category_id": default_category.id,
        "title": "Test room",
        "description": (
            "This is a test listing description written to meet validation rules. "
            "It contains more than twenty five words so the API accepts it during tests. "
            "The room is clean, quiet, furnished, and close to shops and public transport."
        ),
        "property_type": "flat",
        "location": "10 Downing Street, London SW1A 2AA",
        "price_per_month": "750.00",
        "is_available": True,
    }

    res = auth_client.post(reverse("api:room-list"), payload, format="json")
    assert res.status_code in (200, 201), res.data

    room_id = res.data.get("id")
    assert room_id, res.data

    return Room.objects.get(pk=room_id)


def test_room_indexing_effective_follows_user_default(auth_client, user, draft_room):
    url = reverse("api:room-detail", kwargs={"pk": draft_room.pk})
    res = auth_client.get(url)

    assert res.status_code == 200
    payload = res.data["data"]

    assert payload["allow_search_indexing_override"] is None
    assert payload["allow_search_indexing_effective"] is True


def test_room_indexing_effective_respects_override_false(auth_client, draft_room):
    url = reverse("api:room-detail", kwargs={"pk": draft_room.pk})

    res_patch = auth_client.patch(
        url,
        {"allow_search_indexing_override": False},
        format="json",
    )
    assert res_patch.status_code == 200, res_patch.data

    res = auth_client.get(url)
    assert res.status_code == 200
    payload = res.data["data"]

    assert payload["allow_search_indexing_override"] is False
    assert payload["allow_search_indexing_effective"] is False


def test_room_indexing_effective_respects_override_true_even_if_user_default_false(
    auth_client, user, draft_room
):
    profile = user.profile
    profile.allow_search_indexing_default = False
    profile.save(update_fields=["allow_search_indexing_default"])

    url = reverse("api:room-detail", kwargs={"pk": draft_room.pk})

    res_patch = auth_client.patch(
        url,
        {"allow_search_indexing_override": True},
        format="json",
    )
    assert res_patch.status_code == 200, res_patch.data

    res = auth_client.get(url)
    assert res.status_code == 200
    payload = res.data["data"]

    assert payload["allow_search_indexing_override"] is True
    assert payload["allow_search_indexing_effective"] is True