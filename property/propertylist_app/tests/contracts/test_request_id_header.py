import pytest

@pytest.mark.django_db
def test_every_response_has_request_id(client):
    r = client.get("/health/")
    assert r.status_code == 200
    assert "X-Request-ID" in r.headers
    assert r.headers["X-Request-ID"]