import pytest

pytestmark = pytest.mark.django_db




def test_onboarding_complete_sets_flag_true(auth_client, user):
    resp = auth_client.post(
        "/api/users/me/onboarding/complete/",
        data={"confirm": True},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["onboarding_completed"] is True

    user.refresh_from_db()
    user.profile.refresh_from_db()
    assert user.profile.onboarding_completed is True
