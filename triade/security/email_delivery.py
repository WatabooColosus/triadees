"""SMTP delivery for account verification links."""
from __future__ import annotations
import os
import smtplib
from email.message import EmailMessage

def send_verification_email(email: str, token: str) -> None:
    host = os.getenv("TRIADE_SMTP_HOST", "").strip()
    sender = os.getenv("TRIADE_SMTP_FROM", "").strip()
    if not host or not sender:
        raise RuntimeError("smtp_not_configured")
    port = int(os.getenv("TRIADE_SMTP_PORT", "587"))
    base = os.getenv("TRIADE_PUBLIC_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
    link = f"{base}/?verify={token}"
    msg = EmailMessage()
    msg["Subject"] = "Verifica tu cuenta de Tríade"
    msg["From"] = sender
    msg["To"] = email
    msg.set_content(f"Verifica tu cuenta de Tríade abriendo este enlace:\n\n{link}\n\nCaduca en 15 minutos.")
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if os.getenv("TRIADE_SMTP_STARTTLS", "1").lower() not in {"0", "false", "no"}:
            smtp.starttls()
        user, password = os.getenv("TRIADE_SMTP_USER", ""), os.getenv("TRIADE_SMTP_PASSWORD", "")
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)
