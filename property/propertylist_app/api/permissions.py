from rest_framework import permissions


class IsAdminOrReadOnly(permissions.IsAdminUser):
    """Read for all, write only for admin/staff users."""
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_staff)


class IsReviewUserOrReadOnly(permissions.BasePermission):
    """Read for all; write only by review creator or staff."""
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.review_user == request.user or request.user.is_staff


class IsOwnerOrReadOnly(permissions.BasePermission):
    """Read for all; write only by property owner or staff."""
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        owner = getattr(obj, "property_owner", None)
        return (owner is not None and owner == request.user) or bool(request.user and request.user.is_staff)
