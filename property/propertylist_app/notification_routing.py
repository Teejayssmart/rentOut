from datetime import timedelta

from django.utils import timezone

from propertylist_app.api.serializers import NotificationSerializer
from propertylist_app.models import Booking, Notification, Tenancy


class BellNotificationSerializer(NotificationSerializer):
    """Bell-specific navigation while preserving stored notification targets."""

    def get_cta_url(self, obj) -> str:
        if (
            obj.type == "tenancy_rejected_unverified"
            and obj.audience == Notification.Audience.SEEKER
            and obj.target_type == "tenancy"
            and obj.target_id
        ):
            tenancy = (
                Tenancy.objects
                .only("room_id", "tenant_id")
                .filter(id=obj.target_id)
                .first()
            )

            if tenancy:
                completed_viewing = (
                    Booking.objects
                    .filter(
                        room_id=tenancy.room_id,
                        user_id=tenancy.tenant_id,
                        is_deleted=False,
                        status=Booking.STATUS_ACTIVE,
                        canceled_at__isnull=True,
                        start__lte=(
                            timezone.now() - timedelta(minutes=10)
                        ),
                    )
                    .order_by("-start", "-id")
                    .first()
                )

                if completed_viewing:
                    return f"/viewings/{completed_viewing.id}"

        return super().get_cta_url(obj)


def install_bell_notification_routing():
    # NotificationListView resolves this module-level serializer at request
    # time. Keep the persisted notification target as the tenancy so retries
    # remain idempotent; only the bell CTA is redirected to the viewing.
    from propertylist_app.api.views import notifications as notification_views

    notification_views.NotificationSerializer = BellNotificationSerializer
