import os
import re
from urllib.parse import urlparse

import pytest
from django.conf import settings
from django.test.utils import override_settings
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

User = get_user_model()

@pytest.mark.django_db
def test_export_creates_artifact(tmp_path, monkeypatch):
    """
    Requesting a data export should:
      - return 201
      - include a download_url
      - actually create the ZIP file under MEDIA_ROOT
    """
    # Make MEDIA_ROOT point at a writable temp dir for this test
    monkeypatch.setattr(settings, "MEDIA_ROOT", tmp_path, raising=False)
    # Leave MEDIA_URL as-is; default is '/media/'

    user = User.objects.create_user(
        username="gdpr_user", password="pass123", email="u@example.com"
    )

    client = APIClient()
    client.force_authenticate(user=user)

    # Hit the export start endpoint (view: DataExportStartView)
    r = client.post("/api/v1/users/me/export/", {"confirm": True}, format="json")
    assert r.status_code == 201, r.content

    data = r.json()
    assert "download_url" in data and data["download_url"], data

    # Map the URL path back to a filesystem path under MEDIA_ROOT
    parsed = urlparse(data["download_url"])
    media_prefix = (settings.MEDIA_URL or "/media/").rstrip("/")
    # remove leading '/media/' (or custom MEDIA_URL) from the URL path
    rel_path = re.sub(rf"^{re.escape(media_prefix)}/?", "", parsed.path)

    file_abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)
    assert os.path.exists(file_abs_path), f"Export file not found at {file_abs_path}"
