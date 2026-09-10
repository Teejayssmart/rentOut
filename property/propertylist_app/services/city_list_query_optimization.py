from django.db.models import Count


def install_city_list_query_optimization():
    """Paginate grouped city rows in SQL instead of materialising all rows first."""
    from propertylist_app.api.serializers import CitySummarySerializer
    from propertylist_app.api.views.common import _wrap_response_success
    from propertylist_app.api.views.public import CityListView
    from propertylist_app.models import Room

    if getattr(CityListView, "_database_pagination_installed", False):
        return

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()

        base_qs = (
            Room.objects.alive()
            .exclude(location__isnull=True)
            .exclude(location__exact="")
        )

        if q:
            base_qs = base_qs.filter(location__icontains=q)

        rows = (
            base_qs.values("location")
            .annotate(room_count=Count("id"))
            .order_by("location")
        )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(rows, request, view=self)
        serializer = CitySummarySerializer(
            [
                {"name": row["location"], "room_count": row["room_count"]}
                for row in page
            ],
            many=True,
        )

        return _wrap_response_success(
            paginator.get_paginated_response(serializer.data)
        )

    CityListView.get = get
    CityListView._database_pagination_installed = True
