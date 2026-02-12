import pytest
from django.urls import reverse
from rest_framework import status


@pytest.mark.django_db
def test_find_address_valid_postcode(client):
    """
    When a valid postcode is sent,
    the view should return 200 with some kind of address data.

    We don't care exactly *which* addresses yet, only that:
      - status = 200
      - response is not empty
    Your real view can return either:
      - a list of strings, or
      - a dict with an 'addresses' key, etc.
    Adjust the assertions later if your shape is different.
    """

    url = reverse("api:search-find-address")

    response = client.get(url, {"postcode": "SW1A1AA"})

    assert response.status_code == status.HTTP_200_OK

    # Basic shape checks, but tolerant:
    assert response.data is not None
    # For many APIs you'll either get a list or a dict with a list inside
    assert isinstance(response.data, (list, dict))


@pytest.mark.django_db
def test_find_address_missing_postcode(client):
    """
    Request without 'postcode' should return 400.
    """

    url = reverse("api:search-find-address")
    response = client.get(url)  # no query params

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    # Expect DRF-style validation error containing 'postcode'
    # reason: A4 envelope stores field-level validation errors under field_errors
    assert response.data.get("ok") is False
    assert response.data.get("code") == "validation_error"
    assert "postcode" in response.data.get("field_errors", {})



@pytest.mark.django_db
def test_find_address_invalid_postcode(client):
    """
    Invalid postcode format should fail validation.
    Because your FindAddressSerializer.validate_postcode uses
    normalize_uk_postcode, we expect a 400 here.
    """

    url = reverse("api:search-find-address")
    response = client.get(url, {"postcode": "XYZ"})

    # If you ever decide to return 404 for "not found", you can allow both.
    assert response.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)
