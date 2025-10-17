import pytest, hmac, hashlib
from django.core.exceptions import ValidationError
from propertylist_app.validators import verify_webhook_signature

def _hmac_header(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()

def test_verify_webhook_signature_ok():
    secret = "whsec_test"
    body = b'{"ok":true}'
    header = _hmac_header(secret, body)
    # Should not raise
    verify_webhook_signature(secret=secret, payload=body, signature_header=header, scheme="sha256=")

def test_verify_webhook_signature_bad():
    secret = "whsec_test"
    body = b'{"ok":true}'
    with pytest.raises(ValidationError):
        verify_webhook_signature(secret=secret, payload=body, signature_header="sha256=deadbeef", scheme="sha256=")
