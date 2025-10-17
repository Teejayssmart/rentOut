import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from propertylist_app.models import Room, RoomCategorie

User = get_user_model()

@pytest.mark.django_db
def test_report_does_not_auto_hide_room():
    owner = User.objects.create_user(username="owner", password="pass123", email="o@example.com")
    reporter = User.objects.create_user(username="reporter", password="pass123", email="r@example.com")
    cat = RoomCategorie.objects.create(name="Any", active=True)
    room = Room.objects.create(
        title="Reported Room",
        description="...",
        price_per_month=1000,
        location="Manchester M1 1AA",
        category=cat,
        property_owner=owner,
        status="active",
    )

    # Reporter files a report
    client = APIClient()
    client.force_authenticate(user=reporter)
    url_report = reverse("v1:report-create")
    payload = {"target_type": "room", "object_id": room.id, "reason": "abuse", "details": "spammy"}
    r = client.post(url_report, payload, format="json")
    assert r.status_code == 201

    # Room remains visible in public search until staff moderates
    client = APIClient()  # unauth
    url_search = reverse("v1:search-rooms")
    r2 = client.get(url_search, {"q": "Reported"})
    assert r2.status_code == 200
    titles = [x["title"] for x in r2.json()["results"]]
    assert "Reported Room" in titles
