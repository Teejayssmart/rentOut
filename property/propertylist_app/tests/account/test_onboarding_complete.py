import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_onboarding_complete_sets_flag_true(auth_client, user):
    url = reverse("v1:user-onboarding-complete")
    resp = auth_client.post(url, data={"confirm": True}, format="json")
    assert resp.status_code == 200
