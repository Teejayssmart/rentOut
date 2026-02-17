import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from datetime import date

from propertylist_app.models import Room, Booking, UserProfile

API_TENANCY_PROPOSE_URL = "/api/tenancies/propose/"


def future_move_in_date():
    return date.today() + timedelta(days=7)


def create_basic_room(owner):
    return Room.objects.create(
        title="Test Room",
        property_owner=owner,
        price_per_month=500,
    )



@pytest.mark.django_db
def test_landlord_cannot_propose_to_user_without_completed_viewing(api_client):
    User = get_user_model()

    landlord = User.objects.create_user(
        username="landlord1",
        email="landlord1@example.com",
        password="Str0ng!Pass123",
    )
    tenant = User.objects.create_user(
        username="tenant1",
        email="tenant1@example.com",
        password="Str0ng!Pass123",
    )

    UserProfile.objects.get_or_create(user=landlord)
    UserProfile.objects.get_or_create(user=tenant)

    room = create_basic_room(landlord)

    api_client.force_authenticate(user=landlord)

    res = api_client.post(
      API_TENANCY_PROPOSE_URL,
      {
          "room_id": room.id,
          "counterparty_user_id": tenant.id,
          "move_in_date": future_move_in_date(),
          "duration_months": 6,
      },
      format="json",
  )


    assert res.status_code == 400


@pytest.mark.django_db
def test_tenant_cannot_propose_to_random_user(api_client):
    User = get_user_model()

    landlord = User.objects.create_user(
        username="landlord2",
        email="landlord2@example.com",
        password="Str0ng!Pass123",
    )
    tenant = User.objects.create_user(
        username="tenant2",
        email="tenant2@example.com",
        password="Str0ng!Pass123",
    )
    random_user = User.objects.create_user(
        username="intruder",
        email="intruder@example.com",
        password="Str0ng!Pass123",
    )

    UserProfile.objects.get_or_create(user=landlord)
    UserProfile.objects.get_or_create(user=tenant)
    UserProfile.objects.get_or_create(user=random_user)

    room = create_basic_room(landlord)

    Booking.objects.create(
      room=room,
      user=tenant,
      start=timezone.now() - timedelta(days=2),
      end=timezone.now() - timedelta(days=1),
      status=Booking.STATUS_ACTIVE,

    )


    api_client.force_authenticate(user=tenant)

    res = api_client.post(
      API_TENANCY_PROPOSE_URL,
      {
          "room_id": room.id,
          "counterparty_user_id": random_user.id,
          "move_in_date": future_move_in_date(),
          "duration_months": 6,
      },
      format="json",
  )


    assert res.status_code == 400


@pytest.mark.django_db
def test_tenant_can_propose_to_landlord_if_viewing_completed(api_client):
    User = get_user_model()

    landlord = User.objects.create_user(
        username="landlord3",
        email="landlord3@example.com",
        password="Str0ng!Pass123",
    )
    tenant = User.objects.create_user(
        username="tenant3",
        email="tenant3@example.com",
        password="Str0ng!Pass123",
    )

    UserProfile.objects.get_or_create(user=landlord)
    UserProfile.objects.get_or_create(user=tenant)

    room = create_basic_room(landlord)

    Booking.objects.create(
      room=room,
      user=tenant,
      start=timezone.now() - timedelta(days=3),
      end=timezone.now() - timedelta(days=2),
      status=Booking.STATUS_ACTIVE,

  )


    api_client.force_authenticate(user=tenant)

    res = api_client.post(
      API_TENANCY_PROPOSE_URL,
      {
          "room_id": room.id,
          "counterparty_user_id": landlord.id,
          "move_in_date": (date.today() + timedelta(days=7)),
          "duration_months": 6,
      },
      format="json",
  )

    assert res.status_code in (200, 201)
