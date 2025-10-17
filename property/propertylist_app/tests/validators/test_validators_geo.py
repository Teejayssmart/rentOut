import pytest
from django.core.exceptions import ValidationError
from propertylist_app.validators import normalize_uk_postcode, validate_radius_miles, haversine_miles

def test_normalize_uk_postcode_basic():
    assert normalize_uk_postcode("sw1a1aa") == "SW1A 1AA"
    assert normalize_uk_postcode("  Sw1a 1aa  ") == "SW1A 1AA"

def test_validate_radius_miles_ok_and_bounds():
    assert validate_radius_miles("10") == 10
    with pytest.raises(ValidationError):
        validate_radius_miles("0")
    with pytest.raises(ValidationError):
        validate_radius_miles("1000", max_miles=100)

def test_haversine_miles_symmetry_and_units():
    # London (51.5074, -0.1278) to Paris (48.8566, 2.3522) ~ 213 miles
    d = haversine_miles(51.5074, -0.1278, 48.8566, 2.3522)
    assert 200 < d < 230
    # symmetry
    d2 = haversine_miles(48.8566, 2.3522, 51.5074, -0.1278)
    assert abs(d - d2) < 1e-6
