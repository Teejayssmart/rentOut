import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIRequestFactory

from propertylist_app.api.views.public import CityListView
from propertylist_app.models import Room, RoomCategorie


@pytest.mark.django_db
def test_city_list_applies_pagination_in_database(django_user_model):
    landlord = django_user_model.objects.create_user(
        username="city_perf_landlord",
        password="testpass123",
    )
    category = RoomCategorie.objects.create(
        name="City perf category",
        active=True,
    )

    for index in range(30):
        Room.objects.create(
            title=f"City perf room {index}",
            description="x",
            price_per_month=600 + index,
            location=f"City {index:02d}",
            category=category,
            property_owner=landlord,
        )

    factory = APIRequestFactory()
    request = factory.get("/api/v1/cities/?limit=5&offset=0")

    with CaptureQueriesContext(connection) as captured:
        response = CityListView.as_view()(request)

    assert response.status_code == 200

    city_group_queries = [
        query["sql"]
        for query in captured.captured_queries
        if "propertylist_app_room" in query["sql"].lower()
        and "group by" in query["sql"].lower()
    ]

    assert city_group_queries, "No grouped city query was captured."
    assert any(
        "LIMIT 5" in sql.upper()
        for sql in city_group_queries
    ), "\n\n".join(city_group_queries)
