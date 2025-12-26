import datetime
import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


def test_get_me_returns_user(auth_client, user):
    resp = auth_client.get("/api/users/me/")
    assert resp.status_code == 200
    assert resp.data["id"] == user.id
    assert resp.data["username"] == user.username


def test_get_profile_creates_profile_if_missing(auth_client):
    resp = auth_client.get("/api/users/me/profile/")
    assert resp.status_code == 200
    # serializer guarantees these keys exist
    assert "user" in resp.data
    assert "role" in resp.data
    assert "onboarding_completed" in resp.data


def test_patch_profile_normalises_postcode_and_accepts_gender(auth_client):
    payload = {
        "postcode": "sw1a1aa",
        "gender": "Female",
    }
    resp = auth_client.patch("/api/users/me/profile/", data=payload, format="json")
    assert resp.status_code == 200

    # postcode should be normalised by serializer
    assert resp.data["postcode"] == "SW1A 1AA"

    # your serializer returns display label in representation
    assert resp.data["gender"] in ("Female", "female")  # depending on model choices


def test_patch_profile_rejects_invalid_postcode(auth_client):
    payload = {"postcode": "NOT_A_POSTCODE"}
    resp = auth_client.patch("/api/users/me/profile/", data=payload, format="json")
    assert resp.status_code == 400
    assert "postcode" in resp.data


def test_patch_profile_rejects_under_18_dob(auth_client):
    today = timezone.localdate()
    dob = today.replace(year=today.year - 17)
    payload = {"date_of_birth": dob.isoformat()}
    resp = auth_client.patch("/api/users/me/profile/", data=payload, format="json")
    assert resp.status_code == 400
    assert "date_of_birth" in resp.data
