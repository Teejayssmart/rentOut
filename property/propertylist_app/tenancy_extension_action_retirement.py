from django.apps import apps
from django.db.models.signals import post_save
from django.dispatch import receiver

from propertylist_app.models import Message


TenancyExtension = apps.get_model(
    "propertylist_app",
    "TenancyExtension",
)


@receiver(post_save, sender=TenancyExtension)
def retire_extension_proposal_actions_after_response(
    sender,
    instance,
    created,
    **kwargs,
) -> None:
    """Remove stale renewal response actions once a proposal is answered."""
    if created:
        return

    if instance.status not in {
        instance.STATUS_ACCEPTED,
        instance.STATUS_REJECTED,
    }:
        return

    proposal_messages = Message.objects.filter(
        metadata__extension_id=instance.id,
        metadata__event_type="tenancy_extension_proposed",
        metadata__system_event=True,
    )

    for message in proposal_messages:
        metadata = dict(message.metadata or {})

        if not metadata.get("available_actions"):
            continue

        metadata["available_actions"] = []
        message.metadata = metadata
        message.save(update_fields=["metadata"])
