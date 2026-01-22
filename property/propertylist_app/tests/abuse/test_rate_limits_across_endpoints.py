import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from django.urls import reverse

from propertylist_app.models import MessageThread

pytestmark = pytest.mark.django_db


def _auth_headers(ip="198.51.100.20"):
    return {"REMOTE_ADDR": ip, "HTTP_X_FORWARDED_FOR": ip}


@pytest.mark.parametrize("rate_register, rate_message", [("2/hour", "2/hour")])
def test_rate_limits_register_and_messages(settings, rate_register, rate_message):
    """
    Abuse pattern:
    - spam registration (anon throttle)
    - spam messages (user throttle)
    Proves your most sensitive endpoints are rate-limited.
    """
    # REQUIRED: confirm exact scope names once you upload settings_test.py
    settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["register_anon"] = rate_register
    settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["message_user"] = rate_message

    client = APIClient()

    # REQUIRED: confirm correct register endpoint once you upload api/urls.py
    register_url = "/api/auth/register/"

    # Spam register
    payload = {
        "email": "spam1@test.com",
        "username": "spam1",
        "password": "Pass12345!",
        "terms_accepted": True,
        "terms_version": "v1",
        "role": "seeker",
    }

    r1 = client.post(register_url, payload, format="json", **_auth_headers())
    assert r1.status_code in (200, 201, 400)  # 400 allowed if your register enforces extra fields

    payload["email"] = "spam2@test.com"
    payload["username"] = "spam2"
    r2 = client.post(register_url, payload, format="json", **_auth_headers())
    assert r2.status_code in (200, 201, 400)

    payload["email"] = "spam3@test.com"
    payload["username"] = "spam3"
    r3 = client.post(register_url, payload, format="json", **_auth_headers())
    assert r3.status_code == 429

    # Message throttle: create two users and a thread
    u1 = User.objects.create_user(username="msg_alice", email="a@test.com", password="pass12345")
    u2 = User.objects.create_user(username="msg_bob", email="b@test.com", password="pass12345")

    thread = MessageThread.objects.create()
    thread.participants.set([u1, u2])

    client.force_authenticate(user=u1)

    # If you have reverse name, use it; otherwise replace with hard path after you upload urls.py
    try:
        url = reverse("v1:thread-messages", kwargs={"thread_id": thread.pk})
    except Exception:
        url = f"/api/messages/threads/{thread.pk}/messages/"

    m1 = client.post(url, {"body": "Hi 0"}, format="json", **_auth_headers())
    assert m1.status_code in (200, 201)

    m2 = client.post(url, {"body": "Hi 1"}, format="json", **_auth_headers())
    assert m2.status_code in (200, 201)

    m3 = client.post(url, {"body": "Hi 2"}, format="json", **_auth_headers())
    assert m3.status_code == 429
