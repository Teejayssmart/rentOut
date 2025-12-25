from django.conf import settings
from urllib.parse import quote


def inbox_login_link() -> str:
    base = getattr(settings, "FRONTEND_BASE_URL", "").rstrip("/")
    # login then redirect to inbox
    return f"{base}/login?next={quote('/inbox')}"


def notification_email_html(title: str, body: str) -> str:
    link = inbox_login_link()
    safe_title = title or "RentOut notification"
    safe_body = body or ""

    return f"""
<!doctype html>
<html>
  <body style="font-family: Arial, sans-serif; background:#f6f7fb; padding:20px;">
    <div style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:12px;padding:20px;">
      <h2 style="margin:0 0 12px 0;color:#111;">{safe_title}</h2>
      <p style="margin:0 0 18px 0;color:#333;line-height:1.5;">{safe_body}</p>

      <a href="{link}"
         style="display:inline-block;padding:12px 16px;border-radius:10px;
                background:#356af0;color:#fff;text-decoration:none;">
        Open RentOut inbox
      </a>

      <p style="margin:18px 0 0 0;color:#777;font-size:12px;">
        If the button doesn’t work, copy and paste this link into your browser:<br/>
        {link}
      </p>
    </div>
  </body>
</html>
""".strip()
