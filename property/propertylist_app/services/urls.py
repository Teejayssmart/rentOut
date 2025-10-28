# property/propertylist_app/services/urls.py
"""
Simple helper for generating signed or normal media URLs.
Used by tests to verify the signed URL policy.
"""

from django.core.files.storage import default_storage

def signed_media_url(path: str) -> str:
    """
    Returns a (possibly signed) URL for the given media file.

    - If using S3 with AWS_QUERYSTRING_AUTH=True, this will be a time-limited signed URL.
    - If using local storage, it just returns /media/<path>.
    """
    try:
        return default_storage.url(path)
    except Exception:
        # Fallback: build a relative /media/ URL for local dev
        return f"/media/{path.lstrip('/')}"
