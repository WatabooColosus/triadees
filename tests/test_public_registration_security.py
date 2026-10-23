"""Register/verify/owner-bootstrap security contracts; no real SMTP or Colab writes."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.single_port_app import app
from tools.bootstrap_owner_account import bootstrap
from triade.security.email_delivery import (
    EmailDeliveryUnavailable,
    registration_delivery_status,
)
from triade.security.public_auth import PublicAuthStore


def smtp_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIADE_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("TRIADE_SMTP_FROM", "noreply@example.test")
    monkeypatch.setenv("TRIADE_SMTP_PORT", "587")


def count_users(db: Path) -> int:
    with sqlite3.connect(db) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM auth_users").fetchone()[0])


def test_missing_smtp_fails_before_creating_user(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("TRIADE_SMTP_HOST", raising=False)
    monkeypatch.delenv("TRIADE_SMTP_FROM", raising=False)
    monkeypatch.setenv("TRIADE_AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("TRIADE_PUBLIC_GUARDED", "1")
    client = TestClient(app)
    status = client.get("/api/auth/registration-status")
    assert status.status_code == 200
    assert status.json()["available"] is False
    response = client.post(
        "/api/auth/register",
        json={"email": "person@example.org", "password": "correct horse battery staple"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "smtp_not_configured"
    assert count_users(tmp_path / "auth.db") == 0


def test_registration_and_one_time_email_verification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    smtp_ready(monkeypatch)
    captured: list[str] = []
    monkeypatch.setattr(
        "triade.security.email_delivery.send_verification_email",
        lambda email, token: captured.append(token),
    )
    store = PublicAuthStore(tmp_path / "auth.db")
    result = store.register_email(
        "Person@Example.Org", "correct horse battery staple", client_host="127.0.0.1"
    )
    assert result["status"] == "pending_verification"
    assert result["email"] == "person@example.org"
    with pytest.raises(PermissionError, match="email_not_verified"):
        store.authenticate("person@example.org", "correct horse battery staple")
    assert len(captured) == 1
    verified = store.verify_email(captured[0])
    assert verified["status"] == "verified"
    with pytest.raises(PermissionError, match="invalid_or_expired"):
        store.verify_email(captured[0])
    principal = store.authenticate("PERSON@EXAMPLE.ORG", "correct horse battery staple")
    assert principal["role"] == "viewer"
    assert "access_token" in principal


def test_smtp_failure_removes_only_new_account(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    smtp_ready(monkeypatch)
    def failure(email: str, token: str) -> None:
        raise EmailDeliveryUnavailable("smtp_delivery_unavailable")
    monkeypatch.setattr("triade.security.email_delivery.send_verification_email", failure)
    store = PublicAuthStore(tmp_path / "auth.db")
    with pytest.raises(EmailDeliveryUnavailable):
        store.register_email("new@example.org", "correct horse battery staple")
    assert count_users(tmp_path / "auth.db") == 0


def test_sqlite_signup_quota_is_atomic(tmp_path: Path) -> None:
    store = PublicAuthStore(tmp_path / "auth.db")
    for _ in range(5):
        store._register_rate_limit("same@example.org", "198.51.100.1")
    with pytest.raises(PermissionError, match="registration_rate_limited"):
        store._register_rate_limit("same@example.org", "198.51.100.1")


def test_first_owner_bootstrap_is_local_single_use(tmp_path: Path) -> None:
    db = tmp_path / "auth.db"
    PublicAuthStore(db)
    created = bootstrap(db, "owner@example.org", "correct horse battery staple")
    assert created["role"] == "admin"
    auth = PublicAuthStore(db)
    assert auth.authenticate("owner@example.org", "correct horse battery staple")["role"] == "admin"
    with pytest.raises(PermissionError, match="bootstrap_refused_existing_accounts"):
        bootstrap(db, "second@example.org", "correct horse battery staple")
    with sqlite3.connect(db) as conn:
        hashed = conn.execute(
            "SELECT password_hash FROM auth_users WHERE username=?",
            ("owner@example.org",),
        ).fetchone()[0]
    assert "correct horse battery staple" not in hashed


def test_tls_status_rejects_half_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    smtp_ready(monkeypatch)
    monkeypatch.setenv("TRIADE_SMTP_USER", "mailer")
    monkeypatch.delenv("TRIADE_SMTP_PASSWORD", raising=False)
    assert registration_delivery_status()["reason"] == "smtp_credentials_incomplete"
