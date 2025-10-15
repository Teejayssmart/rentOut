# propertylist_app/services/security.py
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone

def _login_key(ip: str | None, username: str | None) -> str:
    base = username or ip or "unknown"
    return f"login_fail::{base.lower()}"

def is_locked_out(ip: str | None, username: str | None) -> bool:
    key = _login_key(ip, username)
    info = cache.get(key)
    if not info:
        return False
    count = info.get("count", 0)
    until = info.get("until")
    if until and until > timezone.now() and count >= settings.LOGIN_FAIL_LIMIT:
        return True
    return False

def register_login_failure(ip: str | None, username: str | None) -> None:
    key = _login_key(ip, username)
    info = cache.get(key) or {"count": 0, "until": None}
    info["count"] = int(info.get("count", 0)) + 1
    # start/extend lockout window when threshold reached
    if info["count"] >= settings.LOGIN_FAIL_LIMIT:
        info["until"] = timezone.now() + timezone.timedelta(seconds=settings.LOGIN_LOCKOUT_SECONDS)
    cache.set(key, info, timeout=settings.LOGIN_LOCKOUT_SECONDS)

def clear_login_failures(ip: str | None, username: str | None) -> None:
    cache.delete(_login_key(ip, username))
