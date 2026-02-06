# propertylist_app/services/security.py
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
from datetime import timedelta


def _login_key(ip: str | None, username: str | None) -> str:
    base = username or ip or "unknown"
    return f"login_fail::{base.lower()}"

def is_locked_out(ip: str | None, username: str | None) -> bool:
    key = _login_key(ip, username)
    info = cache.get(key)
    if not info:
        return False

    until = info.get("until")
    return bool(until and timezone.now() < until)


def register_login_failure(ip: str | None, username: str | None) -> None:
    key = _login_key(ip, username)
    info = cache.get(key) or {"count": 0, "until": None}

    info["count"] = int(info.get("count", 0)) + 1

    # IMPORTANT FIX:
    # Lockout should start AFTER exceeding the limit, not when equal
    if info["count"] > settings.LOGIN_FAIL_LIMIT:
        info["until"] = timezone.now() + timedelta(
            seconds=settings.LOGIN_LOCKOUT_SECONDS
    )

    cache.set(key, info, timeout=settings.LOGIN_LOCKOUT_SECONDS)


def clear_login_failures(ip: str | None, username: str | None) -> None:
    cache.delete(_login_key(ip, username))
