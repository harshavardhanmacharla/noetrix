"""
Email delivery service for password reset and notifications.
Integrates with SMTP when configured, and provides a safe development-only
link mechanism when unconfigured.
"""
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import json
import logging
from pathlib import Path
import smtplib
import threading
from typing import Dict, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Thread-safe development store for inspecting reset links in tests and local development.
# Never populated or exposed in production.
_dev_reset_links: Dict[str, str] = {}
_dev_store_lock = threading.Lock()


def _get_dev_file_path() -> Path:
    """Return the path to the temporary development reset links file."""
    return Path(settings.ARTIFACTS_DIR) / ".dev_reset_links.json"


def get_latest_dev_reset_url(email: str) -> Optional[str]:
    """Retrieve the latest development reset URL for an email (non-production only)."""
    if settings.ENVIRONMENT.lower() == "production":
        return None

    clean = email.strip().lower()
    with _dev_store_lock:
        if clean in _dev_reset_links:
            return _dev_reset_links[clean]

        # File-based fallback for server reloads
        try:
            dev_file = _get_dev_file_path()
            if dev_file.exists():
                data = json.loads(dev_file.read_text(encoding="utf-8"))
                return data.get(clean)
        except Exception:
            pass
        return None


def clear_dev_reset_links() -> None:
    """Clear in-memory and file development reset links (useful between tests)."""
    with _dev_store_lock:
        _dev_reset_links.clear()
        try:
            dev_file = _get_dev_file_path()
            if dev_file.exists():
                dev_file.unlink()
        except Exception:
            pass


def send_password_reset_email(to_email: str, reset_token: str) -> bool:
    """
    Deliver password reset instructions to the given user.

    If SMTP is configured via environment variables, sends via SMTP with TLS.
    If SMTP is not configured:
      - In production: logs a warning and returns False.
      - In development/testing: logs/prints a development link and stores it in the dev store.
    """
    clean_email = to_email.strip().lower()
    reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?token={reset_token}"
    is_prod = settings.ENVIRONMENT.lower() == "production"

    if settings.SMTP_HOST:
        try:
            msg = MIMEMultipart("alternative")
            sender_name = settings.EMAILS_FROM_NAME or "Noetrix"
            sender_email = settings.EMAILS_FROM_EMAIL or f"noreply@{settings.SMTP_HOST}"
            msg["From"] = f"{sender_name} <{sender_email}>"
            msg["To"] = clean_email
            msg["Subject"] = "Noetrix - Password Reset Request"

            text_content = (
                f"Hello,\n\n"
                f"We received a request to reset the password for your Noetrix account.\n"
                f"To choose a new password, visit the following link:\n\n"
                f"{reset_url}\n\n"
                f"This link will expire in {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes.\n"
                f"If you did not request this password reset, please ignore this email.\n\n"
                f"— The Noetrix Team\n"
            )

            html_content = (
                f"<!DOCTYPE html>"
                f"<html><head><meta charset='utf-8'></head>"
                f"<body style='font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, Helvetica, Arial, sans-serif; line-height: 1.5; color: #1e293b; background-color: #f8fafc; padding: 24px;'>"
                f"<div style='max-width: 540px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 32px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);'>"
                f"<h2 style='color: #0f172a; margin-top: 0;'>Reset Your Noetrix Password</h2>"
                f"<p>Hello,</p>"
                f"<p>We received a request to reset the password for your Noetrix account. Click the button below to choose a new password:</p>"
                f"<p style='margin: 28px 0;'>"
                f"<a href='{reset_url}' style='background-color: #2563eb; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: 500; display: inline-block;'>Reset Password</a>"
                f"</p>"
                f"<p style='color: #64748b; font-size: 14px;'>This link will expire in {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes.<br/>"
                f"If you did not request this reset, you can safely ignore this email.</p>"
                f"<hr style='border: none; border-top: 1px solid #f1f5f9; margin: 24px 0;' />"
                f"<p style='color: #94a3b8; font-size: 12px;'>If the button above does not work, copy and paste this link into your browser:<br/>"
                f"<a href='{reset_url}' style='color: #2563eb; word-break: break-all;'>{reset_url}</a></p>"
                f"</div>"
                f"</body></html>"
            )

            msg.attach(MIMEText(text_content, "plain", "utf-8"))
            msg.attach(MIMEText(html_content, "html", "utf-8"))

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
                if settings.SMTP_TLS:
                    server.starttls()
                if settings.SMTP_USER and settings.SMTP_PASSWORD:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)

            logger.info("Password reset email dispatched to %s", clean_email)
            return True
        except Exception as e:
            logger.error("Failed to send password reset email via SMTP: %s", type(e).__name__)
            return False

    if is_prod:
        logger.warning(
            "SMTP_HOST is not configured in production; password reset email could not be sent."
        )
        return False

    # Development / Testing fallback
    with _dev_store_lock:
        _dev_reset_links[clean_email] = reset_url
        try:
            dev_file = _get_dev_file_path()
            dev_file.parent.mkdir(parents=True, exist_ok=True)
            existing = {}
            if dev_file.exists():
                try:
                    existing = json.loads(dev_file.read_text(encoding="utf-8"))
                except Exception:
                    existing = {}
            existing[clean_email] = reset_url
            dev_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        except Exception:
            pass

    logger.info("[DEV ONLY] Password reset link for %s: %s", clean_email, reset_url)
    print(f"\n[DEV ONLY] Password reset link for {clean_email}:\n  --> {reset_url}\n", flush=True)
    return True
