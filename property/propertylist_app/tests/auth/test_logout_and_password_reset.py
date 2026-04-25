import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import UserProfile

User = get_user_model()


def _extract_last_email_code():
    assert mail.outbox, "Expected at least one email in outbox."
    body = mail.outbox[-1].body
    match = re.search(r"(\d{6})", body)
    assert match is not None, f"Could not find 6-digit code in email body: {body}"
    return match.group(1)


@pytest.mark.django_db
def test_password_reset_request_and_confirm():
    """
    Password reset flow:
      1) POST reset request (email) -> creates EmailOTP
      2) POST confirm (email + token + new_password) -> resets password
      3) Login with new password works
    """
    u = User.objects.create_user(
        username="resetuser",
        email="reset@example.com",
        password="pass12345",
    )
    UserProfile.objects.update_or_create(user=u, defaults={"email_verified": True})

    client = APIClient()

    # Step 1: request reset
    r_req = client.post(
        reverse("api:auth-password-reset"),
        {"email": u.email},
        format="json",
    )
    assert r_req.status_code == 200, r_req.data

    token = _extract_last_email_code()

    # Step 2: confirm reset with token from email
    r_conf = client.post(
        reverse("api:auth-password-reset-confirm"),
        {
            "email": u.email,
            "token": token,
            "new_password": "newpass123",
            "confirm_password": "newpass123",
        },
        format="json",
    )
    assert r_conf.status_code in (200, 204), r_conf.data

    # Step 3: login with new password should work
    r_login = client.post(
        reverse("api:auth-login"),
        {"identifier": u.email, "password": "newpass123"},
        format="json",
    )
    assert r_login.status_code == 200, r_login.data