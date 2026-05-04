from rest_framework import permissions



class IsOwner(permissions.BasePermission):
    """
    Strict ownership check (no read-only bypass).
    Useful for sensitive endpoints (delete, billing, etc.)
    """

    def has_object_permission(self, request, view, obj):
        owner = getattr(obj, "user", None) or getattr(obj, "property_owner", None)
        return owner == request.user



class IsAdminOrReadOnly(permissions.IsAdminUser):
    """Read for all, write only for admin/staff users."""
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_staff)


class IsOwnerOrReadOnly(permissions.BasePermission):
    """Read for all; write only by property owner or staff."""
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        owner = getattr(obj, "property_owner", None)
        return (owner is not None and owner == request.user) or bool(request.user and request.user.is_staff)





class HasAnyAdminRole(permissions.BasePermission):
    """
    Allows access to staff/superuser users or users whose profile.admin_role is set.
    """

    message = "You do not have permission to perform this action."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
            return True

        profile = getattr(user, "profile", None)
        admin_role = getattr(profile, "admin_role", "") if profile else ""
        return bool(admin_role)


class HasSpecificAdminRole(permissions.BasePermission):
    """
    Base class for role-specific admin access.
    Child classes must define allowed_admin_roles.
    """
    allowed_admin_roles = set()
    message = "You do not have permission to perform this action."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if getattr(user, "is_superuser", False):
            return True

        # Project tests and current endpoint contract treat staff users
        # as valid admins for role-specific admin endpoints.
        if getattr(user, "is_staff", False):
            return True

        profile = getattr(user, "profile", None)
        admin_role = getattr(profile, "admin_role", "") if profile else ""

        return admin_role in self.allowed_admin_roles


class IsModerationAdmin(HasSpecificAdminRole):
    allowed_admin_roles = {"super_admin", "moderator"}


class IsOpsAdmin(HasSpecificAdminRole):
    allowed_admin_roles = {"super_admin", "ops_admin"}


class IsFinanceAdmin(HasSpecificAdminRole):
    allowed_admin_roles = {"super_admin", "finance_admin"}


class IsSupportAdmin(HasSpecificAdminRole):
    allowed_admin_roles = {"super_admin", "support_admin"}
