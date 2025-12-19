import pytest
from datetime import date, timedelta

from django.utils import timezone
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model


pytestmark = pytest.mark.django_db


def make_user(email="u@example.com", password="pass12345", username=None):
    User = get_user_model()
    if username is None:
        username = email.split("@")[0]
    return User.objects.create_user(username=username, email=email, password=password)


def auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def profile_me_url():
    return "/api/users/me/profile/"


def avatar_upload_url():
    return "/api/users/me/profile/avatar/"


def test_profile_me_requires_auth():
    client = APIClient()
    res = client.get(profile_me_url())
    assert res.status_code in (401, 403)


def test_profile_me_get_returns_expected_fields():
    user = make_user("profile_get@example.com")
    client = auth_client(user)

    res = client.get(profile_me_url())
    assert res.status_code == 200

    # must exist for the Profile + Edit Profile UI
    for key in [
        "id",
        "user",
        "role_detail",
        "onboarding_completed",
        "gender",
        "occupation",
        "postcode",
        "date_of_birth",
        "about_you",
        "avatar",
        "address_line_1",
        "address_line_2",
        "city",
        "county",
        "country",
        "address_manual",
        "email_verified",
    ]:
        assert key in res.data


def test_profile_me_patch_updates_profile_fields_and_normalises_postcode():
    user = make_user("profile_patch@example.com")
    client = auth_client(user)

    payload = {
        "gender": "Female",
        "occupation": "Professional",
        "postcode": "so32 1aa",  # should normalise
        "about_you": "Short bio",
        "address_manual": "1 Constant Close, Bursledon, Southampton, SO32 1AA",
        "date_of_birth": "1993-11-09",
    }

    res = client.patch(profile_me_url(), data=payload, format="json")
    assert res.status_code == 200

    # confirm updates came back
    assert res.data["gender"] == "Female"
    assert res.data["occupation"] == "Professional"
    assert res.data["about_you"] == "Short bio"
    assert res.data["address_manual"] == "1 Constant Close, Bursledon, Southampton, SO32 1AA"

    # postcode normalisation (at least: uppercase + spacing)
    assert res.data["postcode"] is not None
    assert res.data["postcode"].upper() == res.data["postcode"]
    assert " " in res.data["postcode"]


def test_profile_me_patch_rejects_invalid_postcode():
    user = make_user("profile_bad_pc@example.com")
    client = auth_client(user)

    res = client.patch(profile_me_url(), data={"postcode": "NOT_A_POSTCODE"}, format="json")
    assert res.status_code == 400
    assert "postcode" in res.data


def test_profile_me_patch_rejects_under_18_dob():
    user = make_user("profile_underage@example.com")
    client = auth_client(user)

    under_18 = date.today() - timedelta(days=365 * 10)
    res = client.patch(profile_me_url(), data={"date_of_birth": under_18.isoformat()}, format="json")
    assert res.status_code == 400
    assert "date_of_birth" in res.data


def test_profile_avatar_upload_endpoint_requires_auth():
    client = APIClient()
    res = client.post(avatar_upload_url(), data={}, format="multipart")
    assert res.status_code in (401, 403)
