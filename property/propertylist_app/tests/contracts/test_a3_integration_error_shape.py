import pytest
from django.conf import settings as django_settings
from django.urls import reverse, NoReverseMatch
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def _resolve_register_url():
    """
    Use URL reversing so this test works whether your project exposes the API as:
    - /api/v1/...  (namespace v1)
    - /api/...     (namespace api legacy alias)
    """
    # try v1 first
    try:
        return reverse("v1:auth-register")
    except NoReverseMatch:
        pass

    # then try legacy /api/ alias
    try:
        return reverse("api:auth-register")
    except NoReverseMatch:
        pass

    # final fallback (if namespaces changed)
    # NOTE: keep this as last resort only.
    return "/api/v1/auth/register/"


def test_production_exception_handler_shape_on_validation_error():
    """
    A3 integration proof:
    This test must run under property.settings (production settings),
    because settings_test.py uses DRF default exception handler.
    """

    expected = "propertylist_app.api.exceptions.custom_exception_handler"
    actual = django_settings.REST_FRAMEWORK.get("EXCEPTION_HANDLER")

    if actual != expected:
        pytest.skip(
            f"A3 integration contract test is only valid under property.settings. "
            f"Expected EXCEPTION_HANDLER={expected}, got {actual}."
        )


    client = APIClient()
    url = _resolve_register_url()

    # Intentionally invalid payload (missing required fields) to trigger ValidationError
    payload = {"terms_accepted": True}

    r = client.post(url, payload, format="json")

    # If this fails as 404, it means your root urls.py does not expose auth-register at all.
    # In that case, the failure message will show the URL used.
    assert r.status_code == 400, f"Expected 400, got {r.status_code} at {url}. Body={getattr(r, 'content', b'')!r}"

    data = r.json() if hasattr(r, "json") else getattr(r, "data", None)

    # production error envelope (from exceptions.py)
    assert isinstance(data, dict), data
    assert data.get("ok") is False, data
    assert "code" in data, data
    assert "message" in data, data
    assert data.get("status") == 400, data
    assert ("field_errors" in data) or ("detail" in data) or ("details" in data), data
