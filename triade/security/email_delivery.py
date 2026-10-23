"""Secure SMTP email verification with mandatory TLS and configuration diagnostics.

Open-source Python standard-library transport. Secrets only from the runtime
environment, never API responses or Git-tracked configuration.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlparse


class EmailDeliveryUnavailable(RuntimeError):
    """SMTP transport cannot safely deliver an account verification message."""


def registration_delivery_status() -> dict[str, object]:
    host = os.getenv("TRIADE_SMTP_HOST", "").strip()
    sender = os.getenv("TRIADE_SMTP_FROM", "").strip()
    username = os.getenv("TRIADE_SMTP_USER", "").strip()
    password = os.getenv("TRIADE_SMTP_PASSWORD", "").strip()
    raw_port = os.getenv("TRIADE_SMTP_PORT", "587").strip()
    try:
        port = int(raw_port)
    except ValueError:
        return {"available": False, "reason": "smtp_invalid_port"}
    if not 1 <= port <= 65535:
        return {"available": False, "reason": "smtp_invalid_port"}
    if not host or not sender:
        return {"available": False, "reason": "smtp_not_configured"}
    if "\r" in sender or "\n" in sender or "@" not in sender:
        return {"available": False, "reason": "smtp_invalid_sender"}
    if bool(username) != bool(password):
        return {"available": False, "reason": "smtp_credentials_incomplete"}
    # In public Colab no plaintext SMTP fallback. Port 465 uses implicit TLS;
    # all other ports MUST negotiate STARTTLS and validate the server cert.
    return {"available": True, "reason": "ready"}


def send_verification_email(email: str, token: str) -> None:
    status = registration_delivery_status()
    if not status["available"]:
        raise EmailDeliveryUnavailable(str(status["reason"]))

    host = os.environ["TRIADE_SMTP_HOST"].strip()
    port = int(os.getenv("TRIADE_SMTP_PORT", "587"))
    sender = os.environ["TRIADE_SMTP_FROM"].strip()
    username = os.getenv("TRIADE_SMTP_USER", "").strip()
    password = os.getenv("TRIADE_SMTP_PASSWORD", "").strip()
    base = os.getenv("TRIADE_PUBLIC_BASE_URL", "").strip().rstrip("/")
    parsed = urlparse(base)
    # Only allow a configured HTTPS public link. The one-time token is also
    # supplied as a copy-paste code, so an ephemeral Colab host is optional.
    safe_base = (
        bool(base)
        and parsed.scheme == "https"
        and bool(parsed.hostname)
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )
    link = f"{base}/?verify={token}" if safe_base else None

    message = EmailMessage()
    message["Subject"] = "Verifica tu cuenta de Tríade"
    message["From"] = sender
    message["To"] = email
    body = (
        "Código temporal de verificación de Tríade (caduca en 15 minutos):\n\n"
        f"{token}\n\n"
    )
    if link:
        body += f"También puedes abrir: {link}\n\n"
    body += "Si no solicitaste esta cuenta, ignora el mensaje."
    message.set_content(body)
    context = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15, context=context) as smtp:
                if username:
                    smtp.login(username, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                if username:
                    smtp.login(username, password)
                smtp.send_message(message)
    except (smtplib.SMTPException, OSError, ssl.SSLError, TimeoutError) as exc:
        # Never expose SMTP credentials, remote hostname, or raw server errors.
        raise EmailDeliveryUnavailable("smtp_delivery_unavailable") from exc
