import logging
import smtplib
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger("dhandas.email")


def send_email(to_email: str, subject: str, body: str) -> None:
    """Sends a plain-text email via SMTP. If SMTP isn't configured (local
    dev), logs the email instead of failing — so OTP flows are testable
    without a real mail server."""
    if not settings.smtp_host:
        logger.info("EMAIL (dev, not sent) to=%s subject=%s body=%s", to_email, subject, body)
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to_email

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from, [to_email], msg.as_string())
        logger.info("email_sent to=%s subject=%s", to_email, subject)
    except Exception:
        logger.exception("email_send_failed to=%s subject=%s", to_email, subject)
        raise


def send_otp_email(to_email: str, code: str, purpose: str) -> None:
    subject = {
        "signup_verify": "Verify your Dhandas account",
        "login_2fa": "Your Dhandas login code",
        "password_reset": "Reset your Dhandas password",
    }.get(purpose, "Your Dhandas verification code")
    body = (
        f"Your verification code is: {code}\n\n"
        f"This code expires in {settings.otp_expire_minutes} minutes. "
        "If you didn't request this, you can ignore this email."
    )
    send_email(to_email, subject, body)


def send_invitation_email(to_email: str, invite_link: str, temp_password: str, company_name: str, role: str) -> None:
    subject = f"You've been invited to {company_name} on Dhandas"
    body = (
        f"You've been invited to join {company_name} as a {role}.\n\n"
        f"Temporary password: {temp_password}\n"
        f"Accept your invitation here: {invite_link}\n\n"
        "You'll be asked to set your own password when you accept."
    )
    send_email(to_email, subject, body)
