"""OTP-response fallback: never dead-end signup when email isn't configured,
but never leak the code once a real email channel exists (and DEV_MODE is off)."""
from __future__ import annotations

from backend.config import settings
from backend.routers import auth as authmod


def test_otp_returned_when_no_email_configured(monkeypatch):
    monkeypatch.setattr(settings, "DEV_MODE", False)
    for k in ("BREVO_API_KEY", "RESEND_API_KEY", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.setattr(settings, k, "")
    body = authmod._otp_response("sent", "123456")
    assert body.get("dev_otp") == "123456"  # undeliverable otherwise → must surface


def test_otp_hidden_when_email_configured(monkeypatch):
    monkeypatch.setattr(settings, "DEV_MODE", False)
    monkeypatch.setattr(settings, "BREVO_API_KEY", "xkeysib-real")
    for k in ("RESEND_API_KEY", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.setattr(settings, k, "")
    body = authmod._otp_response("sent", "123456")
    assert "dev_otp" not in body  # secure production path


def test_otp_returned_in_dev_mode_even_with_email(monkeypatch):
    monkeypatch.setattr(settings, "DEV_MODE", True)
    monkeypatch.setattr(settings, "BREVO_API_KEY", "xkeysib-real")
    body = authmod._otp_response("sent", "123456")
    assert body.get("dev_otp") == "123456"
