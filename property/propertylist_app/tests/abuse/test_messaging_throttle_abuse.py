import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from propertylist_app.models import MessageThread

pytestmark = pytest.mark.django_db


def _ip_headers(ip="198.51.100.50"):
    return {"REMOTE_ADDR": ip, "HTTP_X_FORWARDED_FOR": ip}


def test_message_user_throttle_blocks_spam(settings):
    """
    Abuse case:
    - authenticated user spams messages rapidly
    - backend must throttle after limit is reached
    """
    # use existing scope from settings_test.py
    settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["message_user"] = "2/min"

    user1 = User.objects.create_user(
        username="spam_sender", email="s@test.com", password="Pass12345!"
    )
    user2 = User.objects.create_user(
        username="spam_receiver", email="r@test.com", password="Pass12345!"
    )

    thread = MessageThread.objects.create()
    thread.participants.set([user1, user2])

    client = APIClient()
    client.force_authenticate(user=user1)

    url = f"/api/v1/messages/threads/{thread.id}/messages/"


    r1 = client.post(url, {"body": "msg 1"}, format="json", **_ip_headers())
    assert r1.status_code in (200, 201)

    r2 = client.post(url, {"body": "msg 2"}, format="json", **_ip_headers())
    assert r2.status_code in (200, 201)

    r3 = client.post(url, {"body": "msg 3"}, format="json", **_ip_headers())
    assert r3.status_code == 429
