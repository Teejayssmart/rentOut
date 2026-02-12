import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def test_protected_endpoint_rejects_missing_or_tampered_token(user_factory):
    """
    Abuse pattern:
    - call protected endpoint without token
    - call protected endpoint with obviously tampered bearer token

    Proves authentication middleware rejects misuse.
    """
    user = user_factory(username="tok_user", role="seeker")

    client = APIClient()

    # REQUIRED: confirm a reliably protected endpoint once you upload api/urls.py
    # Choose something like /api/users/me/ or /api/notifications/
    # Use a reliably protected endpoint that exists in api/urls.py
    protected_url = "/api/v1/users/me/"


    # No token -> 401
    r1 = client.get(protected_url)
    assert r1.status_code in (401, 403)

    # Tampered token -> 401
    client.credentials(HTTP_AUTHORIZATION="Bearer definitely.invalid.token")
    r2 = client.get(protected_url)
    assert r2.status_code in (401, 403)
