# property/conftest.py
import os
import uuid
import pytest
from django.utils import timezone
from django.core.cache import cache
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from propertylist_app.models import UserProfile, RoomCategorie, Room



@pytest.fixture(autouse=True)
def clear_cache_between_tests(settings):
    # Make sure throttle counters and any cached responses don’t leak across tests
    cache.clear()
    yield
    cache.clear()

@pytest.fixture(autouse=True)
def unique_cache_location_for_session(settings):
    """
    Ensure this test session uses a unique LocMem cache 'LOCATION'
    so it doesn't reuse a stale cache namespace from any prior run.
    """
    caches = settings.CACHES.copy()
    default = caches.get("default", {}).copy()
    default["LOCATION"] = f"pytest-cache-{os.getpid()}-{uuid.uuid4()}"
    caches["default"] = default
    settings.CACHES = caches



@pytest.fixture
def api_client():
    return APIClient()





@pytest.fixture
def user(db):
    User = get_user_model()
    u = User.objects.create_user(
        username="alice",
        email="alice@example.com",
        password="pass12345",
        first_name="Alice",
    )
    UserProfile.objects.get_or_create(user=u)
    return u



@pytest.fixture
def user2(db):
    User = get_user_model()
    u = User.objects.create_user(
        username="bob",
        email="bob@example.com",
        password="pass12345",
        first_name="Bob",
    )
    UserProfile.objects.get_or_create(user=u)
    return u



@pytest.fixture
def auth_client(api_client, user):
    """
    Returns an APIClient already authenticated as `user`.
    Uses force_authenticate so we don’t depend on OTP/email verification.
    """
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def user_factory(db):
    """
    Usage:
      u = user_factory()
      u2 = user_factory(username="bob", email="bob@example.com", email_verified=False)
    """
    User = get_user_model()

    def make_user(
        *,
        username="user",
        email=None,
        password="pass12345",
        email_verified=True,
        role="seeker",
        **extra,
    ):
        if email is None:
            email = f"{username}@example.com"

        u = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            **extra,
        )

        # make sure profile exists + defaults that allow login in your backend
        profile, _ = UserProfile.objects.get_or_create(user=u)
        profile.email_verified = bool(email_verified)
        profile.role = role
        if email_verified and not getattr(profile, "email_verified_at", None):
            profile.email_verified_at = timezone.now()
        profile.save()

        return u

    return make_user


@pytest.fixture
def room_factory(db, user_factory):
    """
    Usage:
      room = room_factory()
      room2 = room_factory(property_owner=my_user, title="Nice room", price_per_month="900.00")
    """
    def make_room(
        *,
        property_owner=None,
        category_name="Room",
        title="Test room",
        description="Test description",
        price_per_month="750.00",
        location="London",
        property_type="flat",
        category=None,
        **overrides,
    ):
        if property_owner is None:
            property_owner = user_factory(username="owner", email="owner@example.com")

        if category is None:
            category, _ = RoomCategorie.objects.get_or_create(name=category_name)

        room = Room.objects.create(
            property_owner=property_owner,
            category=category,
            title=title,
            description=description,
            price_per_month=price_per_month,
            location=location,
            property_type=property_type,
            **overrides,
        )
        return room

    return make_room