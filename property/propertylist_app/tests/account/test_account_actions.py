import pytest

pytestmark = pytest.mark.django_db


def test_change_password_requires_all_fields(auth_client):
    resp = auth_client.post("/api/v1/users/me/change-password/", data={}, format="json")
    assert resp.status_code == 400


def test_change_password_rejects_wrong_current_password(auth_client):
    payload = {
        "current_password": "wrong",
        "new_password": "NewPass123!",
        "confirm_password": "NewPass123!",
    }
    resp = auth_client.post("/api/v1/users/me/change-password/", data=payload, format="json")
    assert resp.status_code == 400
    assert "current_password" in resp.data


def test_deactivate_account_sets_user_inactive(auth_client, user):
    resp = auth_client.post("/api/v1/users/me/deactivate/", data={}, format="json")
    assert resp.status_code == 200
    user.refresh_from_db()
    assert user.is_active is False
