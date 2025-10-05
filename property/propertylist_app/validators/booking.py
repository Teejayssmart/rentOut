from django.core.exceptions import ValidationError

def validate_no_booking_conflict(room, start, end, booking_qs):
    """
    Ensure no overlapping active bookings for a room.
    """
    if start >= end:
        raise ValidationError("End must be after start.")
    clash = (
        booking_qs.filter(room=room, canceled_at__isnull=True)
        .filter(start__lt=end, end__gt=start)
        .exists()
    )
    if clash:
        raise ValidationError("Selected dates clash with an existing booking.")
