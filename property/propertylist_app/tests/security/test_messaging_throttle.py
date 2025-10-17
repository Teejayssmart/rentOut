import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import MessageThread


def _auth_headers(ip="198.51.100.10"):
    # Consistent IP for throttle keying
    return {"REMOTE_ADDR": ip, "HTTP_X_FORWARDED_FOR": ip}


@pytest.mark.django_db
@pytest.mark.parametrize("rate", ["2/hour"])  # tweakable if you like
def test_message_user_throttle_hits_limit(settings, rate):
    # ✅ IMPORTANT: do NOT replace the entire REST_FRAMEWORK dict.
    # We only change the one scope we care about so other scopes stay intact.
    settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["message_user"] = rate

    u1 = User.objects.create_user(username="alice", email="a@x.com", password="pass12345")
    u2 = User.objects.create_user(username="bob", email="b@x.com", password="pass12345")

    client = APIClient()
    client.force_authenticate(user=u1)

    thread = MessageThread.objects.create()
    thread.participants.set([u1, u2])

    url = reverse("v1:thread-messages", kwargs={"thread_id": thread.pk})

    # First two requests should pass
    r1 = client.post(url, {"body": "Hi 0"}, format="json", **_auth_headers())
    assert r1.status_code in (200, 201)

    r2 = client.post(url, {"body": "Hi 1"}, format="json", **_auth_headers())
    assert r2.status_code in (200, 201)

    # Third should be throttled
    r3 = client.post(url, {"body": "Hi 2"}, format="json", **_auth_headers())
    assert r3.status_code == 429
