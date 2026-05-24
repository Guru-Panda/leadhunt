from __future__ import annotations

import logging

import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from backend.config import settings

log = logging.getLogger(__name__)


def _otp_html(otp_code: str) -> str:
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#f9fafb; padding:40px 0;">
  <div style="max-width:480px; margin:0 auto; background:#ffffff; border-radius:12px; overflow:hidden; border:1px solid #e5e7eb;">
    <div style="background:#6366f1; padding:24px 32px;">
      <h1 style="color:#ffffff; margin:0; font-size:24px; font-weight:700;">LeadHunt</h1>
    </div>
    <div style="padding:32px;">
      <h2 style="color:#111827; font-size:20px; margin:0 0 16px;">Your verification code</h2>
      <p style="color:#6b7280; margin:0 0 24px;">Enter this code to verify your email address. It expires in 10 minutes.</p>
      <div style="background:#f3f4f6; border-radius:8px; padding:20px; text-align:center;">
        <span style="font-family:monospace; font-size:36px; font-weight:700; letter-spacing:12px; color:#111827;">{otp_code}</span>
      </div>
      <p style="color:#9ca3af; font-size:13px; margin:24px 0 0;">If you didn't request this, you can safely ignore this email.</p>
    </div>
  </div>
</body>
</html>
"""


def smtp_configured() -> bool:
    return bool(settings.SMTP_USER and settings.SMTP_PASSWORD)


async def send_otp_email(to_email: str, otp_code: str) -> bool:
    """Send OTP email. Returns True if delivered, False if SMTP missing/failed.

    In dev mode (no SMTP creds), logs the code prominently and returns False
    so the router can include the code in its response.
    """
    if not smtp_configured():
        log.warning(
            "\n"
            "===============================================================\n"
            f"  DEV MODE: SMTP not configured — OTP for {to_email}\n"
            f"  CODE: {otp_code}\n"
            "===============================================================\n"
        )
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your LeadHunt verification code: {otp_code}"
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(_otp_html(otp_code), "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=True,
        )
        log.info(f"OTP email sent to {to_email}")
        return True
    except Exception as e:
        log.error(f"SMTP send failed for {to_email}: {e}")
        log.warning(f"DEV FALLBACK — OTP for {to_email}: {otp_code}")
        return False
