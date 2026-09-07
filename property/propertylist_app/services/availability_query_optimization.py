from datetime import datetime

from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from propertylist_app.models import AvailabilitySlot, Room


def install_availability_only_free_query_optimization():
    """Filter free viewing slots without one booking-count query per slot."""
    from propertylist_app.api.views.rooms import RoomAvailabilityPublicView

    if getattr(RoomAvailabilityPublicView, "_only_free_query_optimized", False):
        return

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AvailabilitySlot.objects.none()

        room = get_object_or_404(Room.objects.alive(), pk=self.kwargs["pk"])
        qs = room.availability_slots.filter(
            start__gt=timezone.now(),
        ).order_by("start")

        date_value = self.request.query_params.get("date")
        f = self.request.query_params.get("from")
        t = self.request.query_params.get("to")
        only_free = self.request.query_params.get("only_free") in {
            "1",
            "true",
            "True",
        }

        if date_value:
            try:
                selected_date = datetime.fromisoformat(date_value).date()
            except Exception:
                raise ValidationError({"date": "date must use YYYY-MM-DD format."})
            qs = qs.filter(start__date=selected_date)

        if f and t:
            try:
                start = datetime.fromisoformat(f)
                end = datetime.fromisoformat(t)
            except Exception:
                raise ValidationError({"detail": "from/to must be ISO 8601"})
            qs = qs.filter(start__lt=end, end__gt=start)

        if only_free:
            qs = qs.annotate(
                active_booking_count=Count(
                    "bookings",
                    filter=Q(bookings__canceled_at__isnull=True),
                )
            ).filter(active_booking_count__lt=F("max_bookings"))

        return qs

    RoomAvailabilityPublicView.get_queryset = get_queryset
    RoomAvailabilityPublicView._only_free_query_optimized = True
