# propertylist_app/services/captcha.py
import json
import urllib.request
from django.conf import settings

def verify_captcha(token: str, remote_ip: str | None = None) -> bool:
    """
    Minimal pluggable CAPTCHA verifier.
    Returns True when:
      - CAPTCHA is disabled (settings.ENABLE_CAPTCHA=False), or
      - provider verifies token successfully.

    Wire with environment:
      CAPTCHA_PROVIDER=recaptcha|hcaptcha
      CAPTCHA_SECRET=your-secret
    """
    if not settings.ENABLE_CAPTCHA:
        return True
    if not token or not settings.CAPTCHA_SECRET:
        return False

    provider = (settings.CAPTCHA_PROVIDER or "recaptcha").lower().strip()
    if provider == "hcaptcha":
        url = "https://hcaptcha.com/siteverify"
        data = {"secret": settings.CAPTCHA_SECRET, "response": token}
        if remote_ip:
            data["remoteip"] = remote_ip
    else:
        url = "https://www.google.com/recaptcha/api/siteverify"
        data = {"secret": settings.CAPTCHA_SECRET, "response": token}
        if remote_ip:
            data["remoteip"] = remote_ip

    payload = urllib.parse.urlencode(data).encode("utf-8")
    try:
        with urllib.request.urlopen(url, data=payload, timeout=5) as resp:
            parsed = json.loads(resp.read().decode("utf-8"))
            # both providers return {"success": true/false, ...}
            return bool(parsed.get("success"))
    except Exception:
        return False
