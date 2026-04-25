from urllib.parse import quote
from django.conf import settings


def _frontend_base_url() -> str:
    base = getattr(settings, "FRONTEND_BASE_URL", "") or ""
    return base.rstrip("/")


def _safe_next_path(next_path: str, default: str = "/inbox") -> str:
    if not next_path or not isinstance(next_path, str):
        return default
    next_path = next_path.strip()
    if not next_path.startswith("/"):
        return default
    return next_path


def build_absolute_url(path: str, *, force_login: bool = False) -> str:
    """
    Build a frontend URL for emails.

    force_login=False (old):
      <FRONTEND_BASE_URL><path>

    force_login=True (F3-ready):
      <FRONTEND_BASE_URL>/login?next=<path>
    """
    base = _frontend_base_url()
    safe_path = _safe_next_path(path, default="/inbox")

    if force_login:
        return f"{base}/login?next={quote(safe_path, safe='/?:&=')}"

    return f"{base}{safe_path}"