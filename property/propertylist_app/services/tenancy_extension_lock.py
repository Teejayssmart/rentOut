from functools import wraps

from rest_framework.exceptions import ValidationError

from propertylist_app.models import Tenancy, TenancyExtension


def _landlord_rejected_tenant_extension(tenancy):
    return TenancyExtension.objects.filter(
        tenancy_id=tenancy.id,
        proposed_by_id=tenancy.tenant_id,
        status=TenancyExtension.STATUS_REJECTED,
    ).exists()


def install_tenancy_extension_rejection_lock():
    from propertylist_app.api.serializers import MessageSerializer
    from propertylist_app.api.views.tenancies import TenancyExtensionCreateView

    original_get_available_actions = MessageSerializer.get_available_actions
    original_post = TenancyExtensionCreateView.post

    @wraps(original_get_available_actions)
    def get_available_actions(self, obj):
        metadata = obj.metadata or {}

        if metadata.get("event_type") == "still_living_check":
            tenancy_id = metadata.get("tenancy_id")
            tenancy = (
                Tenancy.objects
                .only("id", "tenant_id")
                .filter(id=tenancy_id)
                .first()
                if tenancy_id
                else None
            )

            if tenancy and _landlord_rejected_tenant_extension(tenancy):
                return []

        return original_get_available_actions(self, obj)

    @wraps(original_post)
    def post(self, request, tenancy_id: int, *args, **kwargs):
        tenancy = (
            Tenancy.objects
            .only("id", "landlord_id", "tenant_id")
            .filter(id=tenancy_id)
            .first()
        )

        if (
            tenancy
            and request.user.id in {
                tenancy.landlord_id,
                tenancy.tenant_id,
            }
            and _landlord_rejected_tenant_extension(tenancy)
        ):
            raise ValidationError({
                "detail": (
                    "Tenancy information can no longer be updated because "
                    "the landlord rejected the tenant's extension proposal."
                )
            })

        return original_post(self, request, tenancy_id, *args, **kwargs)

    MessageSerializer.get_available_actions = get_available_actions
    TenancyExtensionCreateView.post = post
