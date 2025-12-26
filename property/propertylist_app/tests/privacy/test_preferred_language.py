import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_get_preferred_language_default(auth_client):
    url = reverse("api:my-privacy-preferences")
    res = auth_client.get(url)
    assert res.status_code == 200
    assert res.data["preferred_language"] == "en-GB"


def test_patch_preferred_language(auth_client):
    url = reverse("api:my-privacy-preferences")
    res = auth_client.patch(url, {"preferred_language": "en-US"}, format="json")
    assert res.status_code == 200
    assert res.data["preferred_language"] == "en-US"


def test_patch_preferred_language_rejects_invalid(auth_client):
    url = reverse("api:my-privacy-preferences")
    res = auth_client.patch(url, {"preferred_language": "xx-YY"}, format="json")
    assert res.status_code == 400
