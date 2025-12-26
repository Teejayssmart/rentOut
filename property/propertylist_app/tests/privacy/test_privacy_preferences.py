import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_get_privacy_preferences_returns_default_true(api_client, user):
    api_client.force_authenticate(user=user)

    url = reverse("api:my-privacy-preferences")
    res = api_client.get(url)

    assert res.status_code == 200
    assert res.data["read_receipts_enabled"] is True
    assert res.data["allow_search_indexing_default"] is True



def test_patch_privacy_preferences_turns_off_and_on(api_client, user):
    api_client.force_authenticate(user=user)

    url = reverse("api:my-privacy-preferences")

    res1 = api_client.patch(url, {"read_receipts_enabled": False}, format="json")
    assert res1.status_code == 200
    assert res1.data["read_receipts_enabled"] is False

    res2 = api_client.get(url)
    assert res2.status_code == 200
    assert res2.data["read_receipts_enabled"] is False

    res3 = api_client.patch(url, {"read_receipts_enabled": True}, format="json")
    assert res3.status_code == 200
    assert res3.data["read_receipts_enabled"] is True
    
    res_idx = api_client.patch(url, {"allow_search_indexing_default": False}, format="json")
    assert res_idx.status_code == 200
    assert res_idx.data["allow_search_indexing_default"] is False



def test_privacy_preferences_requires_auth(api_client):
    url = reverse("api:my-privacy-preferences")

    res_get = api_client.get(url)
    assert res_get.status_code in (401, 403)

    res_patch = api_client.patch(url, {"read_receipts_enabled": False}, format="json")
    assert res_patch.status_code in (401, 403)
