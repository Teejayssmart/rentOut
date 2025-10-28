# property/propertylist_app/tasks_webhooks.py
import json
from celery import shared_task
from django.utils import timezone

try:
    import requests
except Exception:
    requests = None

@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=7,
)
def deliver_webhook(self, url: str, payload: dict, headers: dict | None = None, timeout: int = 10):
    """
    Deliver an outbound webhook with exponential backoff on failure.
    Route: 'webhooks' queue (see settings.py CELERY_TASK_ROUTES).
    """
    if requests is None:
        raise RuntimeError("The 'requests' package is required to deliver webhooks")

    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)

    resp = requests.post(url, data=json.dumps(payload or {}), headers=hdrs, timeout=timeout)

    if resp.status_code >= 500:
        # transient error → retry
        raise RuntimeError(f"Receiver 5xx: {resp.status_code}")
    if resp.status_code >= 400:
        # client error → fail (still counts toward retries due to autoretry_for)
        raise RuntimeError(f"Receiver 4xx: {resp.status_code} {resp.text[:200]}")

    return {"delivered": True, "status": resp.status_code, "at": timezone.now().isoformat()}
