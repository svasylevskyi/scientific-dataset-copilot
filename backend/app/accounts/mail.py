import smtplib
import ssl
from email.message import EmailMessage

from fastapi import HTTPException

from app.config import settings


def send_link(recipient: str, purpose: str, token: str) -> None:
    config = settings()
    title, action, lifetime = {
        "verify": ("Verify your email", "verify", "24 hours"),
        "reset": ("Reset your password", "reset", "30 minutes"),
        "email": ("Confirm your new email", "email", "30 minutes"),
    }[purpose]
    # Fragments do not appear in HTTP access logs or Referer headers.
    link = f"{config.public_url}/#/{action}?token={token}"
    message = EmailMessage()
    message["Subject"] = f"{title} — Scientific Dataset Copilot"
    message["From"] = config.mail_from
    message["To"] = recipient
    message.set_content(
        f"{title}\n\nOpen this link and confirm the action:\n{link}\n\n"
        f"This single-use link expires in {lifetime}. "
        "If you did not request this, you can ignore this message.\n"
    )
    try:
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=10) as smtp:
            if config.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if config.smtp_username:
                smtp.login(config.smtp_username, config.smtp_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise HTTPException(
            503, "Email delivery is unavailable. Please try again shortly."
        ) from exc
