import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db

User = get_user_model()


def make_user(email: str):
    username = email.split("@")[0]
    return User.objects.create_user(
        username=username,
        email=email,
        password="pass12345",
    )


def auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def profile_me_url():
    return "/api/v1/users/me/profile/"


def _body(res):
    return res.data.get("data", res.data)


def test_profile_me_get_returns_current_profile():
    user = make_user("profile_get@example.com")
    client = auth_client(user)

    res = client.get(profile_me_url())
    assert res.status_code == 200, getattr(res, "data", None)

    body = _body(res)

    # Current profile endpoint returns profile fields, not the User.email field.
    assert isinstance(body, dict)
    assert "email" not in body or body["email"] == "profile_get@example.com"

    expected_profile_keys = {
        "gender",
        "occupation",
        "postcode",
        "about_you",
        "address_manual",
        "date_of_birth",
    }
    assert expected_profile_keys.intersection(body.keys())


def test_profile_me_patch_updates_profile_fields_and_normalises_postcode():
    user = make_user("profile_patch@example.com")
    client = auth_client(user)

    payload = {
        "gender": "Female",
        "occupation": "Professional",
        "postcode": "so32 1aa",
        "about_you": "Short bio",
        "address_manual": "1 Constant Close, Bursledon, Southampton, SO32 1AA",
        "date_of_birth": "1993-11-09",
    }

    res = client.patch(profile_me_url(), data=payload, format="json")
    assert res.status_code == 200, getattr(res, "data", None)

    body = _body(res)
    assert body["gender"] == "Female"
    assert body["occupation"] == "Professional"
    assert body["postcode"] == "SO32 1AA"
    assert body["about_you"] == "Short bio"
    assert body["address_manual"] == "1 Constant Close, Bursledon, Southampton, SO32 1AA"
    assert str(body["date_of_birth"]) == "1993-11-09"


def test_profile_me_patch_rejects_invalid_postcode():
    user = make_user("profile_bad_pc@example.com")
    client = auth_client(user)

    res = client.patch(profile_me_url(), data={"postcode": "NOT_A_POSTCODE"}, format="json")
    assert res.status_code == 400, getattr(res, "data", None)

    field_errors = res.data.get("field_errors", {})
    details = res.data.get("details", {})
    assert "postcode" in field_errors or "postcode" in details