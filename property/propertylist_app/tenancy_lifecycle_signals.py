from django.db.models.signals import post_save
from django.dispatch import receiver

from propertylist_app.models import Tenancy


@receiver(post_save, sender=Tenancy)
def release_room_when_tenancy_ends(
    sender,
    instance,
    created,
    update_fields,
    **kwargs,
):
    if created or instance.status != Tenancy.STATUS_ENDED:
        return

    if update_fields is not None and "status" not in update_fields:
        return

    room = instance.room

    if room.is_available:
        return

    room.is_available = True
    room.save(
        update_fields=[
            "is_available",
            "updated_at",
        ]
    )
