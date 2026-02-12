import pytest
from django.urls import reverse
from django.utils import timezone

pytestmark = pytest.mark.django_db


def test_get_me_returns_user(auth_client, user):
    url = reverse("v1:user-me")
    resp = auth_client.get(url)
    assert resp.status_code == 200
    assert resp.data["id"] == user.id


def test_get_profile_creates_profile_if_missing(auth_client):
    url = reverse("v1:user-profile")
    resp = auth_client.get(url)
    assert resp.status_code == 200
    assert "id" in resp.data


def test_patch_profile_normalises_postcode_and_accepts_gender(auth_client):
    url = reverse("v1:user-profile")
    payload = {
        "postcode": "sw1a1aa",
        "gender": "Female",
    }
    resp = auth_client.patch(url, data=payload, format="json")
    assert resp.status_code == 200
    # if your serializer normalises postcode, keep this check
    assert resp.data.get("postcode") in ("SW1A 1AA", "SW1A1AA")


def test_patch_profile_rejects_invalid_postcode(auth_client):
    url = reverse("v1:user-profile")
    payload = {"postcode": "NOT_A_POSTCODE"}
    resp = auth_client.patch(url, data=payload, format="json")
    assert resp.status_code == 400
    assert "postcode" in resp.data


def test_patch_profile_rejects_under_18_dob(auth_client):
    url = reverse("v1:user-profile")
    today = timezone.localdate()
    dob = today.replace(year=today.year - 17)
    payload = {"date_of_birth": dob.isoformat()}
    resp = auth_client.patch(url, data=payload, format="json")
    assert resp.status_code == 400
    assert "date_of_birth" in resp.data
