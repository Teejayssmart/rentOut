
from django.urls import reverse
from rest_framework.test import APIClient

def test_export_and_latest(db, django_user_model):
    user = django_user_model.objects.create_user(username="tee", password="pass12345", email="t@example.com")
    client = APIClient()
    client.force_authenticate(user=user)  # << authenticate without JWT

    r = client.post(reverse("v1:me-export-start"), {"confirm": True}, format="json")
    assert r.status_code == 201
    assert "download_url" in r.data

    r2 = client.get(reverse("v1:me-export-latest"))
    assert r2.status_code == 200
    assert "download_url" in r2.data

def test_delete_preview_and_confirm(db, django_user_model):
    user = django_user_model.objects.create_user(username="del", password="pass12345", email="d@example.com")
    client = APIClient()
    client.force_authenticate(user=user)  # << authenticate without JWT

    r = client.get(reverse("v1:me-delete-preview"))
    assert r.status_code == 200
    assert "anonymise" in r.data

    r2 = client.post(reverse("v1:me-delete-confirm"), {"confirm": True}, format="json")
    assert r2.status_code == 200
