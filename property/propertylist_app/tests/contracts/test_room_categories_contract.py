import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def make_authed_client() -> APIClient:
    User = get_user_model()

    # Use staff/superuser so any IsAdminUser / DjangoModelPermissions passes
    user = User.objects.create_superuser(
        username="contract_categories_admin",
        email="contract_categories_admin@test.com",
        password="StrongP@ssword1",
    )

    client = APIClient()
    client.force_authenticate(user=user)
    return client


def assert_same_keys(a: dict, b: dict) -> None:
    assert isinstance(a, dict) and isinstance(b, dict)
    assert set(a.keys()) == set(b.keys()), (
        f"Keys differ.\n/api: {sorted(a.keys())}\n/v1: {sorted(b.keys())}"
    )


def test_room_categories_list_contract_api_and_v1_match_shape():
    client = make_authed_client()

    r_api = client.get("/api/room-categories/")
    r_v1 = client.get("/api/v1/room-categories/")

    assert r_api.status_code == 200, r_api.data
    assert r_v1.status_code == 200, r_v1.data

    data_api = r_api.json()
    data_v1 = r_v1.json()

    assert isinstance(data_api, list), f"/api must return list, got {type(data_api)}"
    assert isinstance(data_v1, list), f"/api/v1 must return list, got {type(data_v1)}"

    # If empty, contract still passes, but we enforce parity.
    if not data_api or not data_v1:
        assert data_api == data_v1
        return

    assert_same_keys(data_api[0], data_v1[0])


def test_room_categories_detail_contract_api_and_v1_match_shape():
    client = make_authed_client()

    # Get an id from the list first (avoid guessing ids)
    r = client.get("/api/room-categories/")
    assert r.status_code == 200, r.data
    data = r.json()

    if not data:
        # No categories in test DB -> skip detail contract
        pytest.skip("No categories exist in test DB to test detail endpoint.")

    cat_id = data[0]["id"]

    r_api = client.get(f"/api/room-categories/{cat_id}/")
    r_v1 = client.get(f"/api/v1/room-categories/{cat_id}/")

    assert r_api.status_code == 200, r_api.data
    assert r_v1.status_code == 200, r_v1.data

    assert_same_keys(r_api.json(), r_v1.json())


def test_room_categories_not_found_schema_is_consistent_api_and_v1():
    client = make_authed_client()
    bad_id = 999999999

    r_api = client.get(f"/api/room-categories/{bad_id}/")
    r_v1 = client.get(f"/api/v1/room-categories/{bad_id}/")

    assert r_api.status_code in (404, 400), r_api.data
    assert r_v1.status_code in (404, 400), r_v1.data

    # same error-body key shape
    assert set(r_api.json().keys()) == set(r_v1.json().keys())