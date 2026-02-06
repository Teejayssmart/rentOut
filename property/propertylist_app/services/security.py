# propertylist_app/services/security.py
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone


def _login_key(ip: str | None, username: str | None) -> str:
    base = username or ip or "unknown"
    return f"login_fail::{base.lower()}"


def is_locked_out(ip: str | None, username: str | None) -> bool:
    key = _login_key(ip, username)
    try:
        info = cache.get(key)
    except Exception:
        # Fail open: if cache is down, do not block login
        return False

    if not info:
        return False

    until = info.get("until")
    return bool(until and timezone.now() < until)


def register_login_failure(ip: str | None, username: str | None) -> None:
    key = _login_key(ip, username)

    try:
        info = cache.get(key) or {"count": 0, "until": None}
    except Exception:
        # Fail open: if cache is down, do not crash login
        return

    info["count"] = int(info.get("count", 0)) + 1

    fail_limit = getattr(settings, "LOGIN_FAIL_LIMIT", 5)
    lockout_seconds = getattr(settings, "LOGIN_LOCKOUT_SECONDS", 900)

    # Lockout starts AFTER exceeding the limit
    if info["count"] > fail_limit:
        info["until"] = timezone.now() + timedelta(seconds=lockout_seconds)

    try:
        cache.set(key, info, timeout=lockout_seconds)
    except Exception:
        # Fail open: if cache is down, do not crash login
        return


def clear_login_failures(ip: str | None, username: str | None) -> None:
    try:
        cache.delete(_login_key(ip, username))
    except Exception:
        # Fail open: if cache is down, do not crash login
        return
