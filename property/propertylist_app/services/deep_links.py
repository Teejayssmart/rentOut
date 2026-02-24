from django.conf import settings


def build_absolute_url(path: str) -> str:
    """
    Build a full URL for email buttons, using FRONTEND_BASE_URL.

    Example:
      path="/app/threads/12"
      -> "https://rentout.co.uk/app/threads/12"
    """
    base = (getattr(settings, "FRONTEND_BASE_URL", "") or "").rstrip("/")
    if not path:
        path = "/app/inbox"
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"