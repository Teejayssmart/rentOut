from .models import AuditLog

def record_audit_log(user, action, request=None, extra=None):
    """
    Save an audit log entry.
    """
    ip = None
    if request:
        ip = request.META.get("REMOTE_ADDR")

    AuditLog.objects.create(
        user=user if user.is_authenticated else None,
        action=action,
        ip_address=ip,
        extra_data=extra or {}
        
    )