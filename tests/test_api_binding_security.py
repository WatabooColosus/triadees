from __future__ import annotations

import pytest

from triade_digimon import validate_api_binding


def test_loopback_binding_does_not_require_key(monkeypatch) -> None:
    monkeypatch.delenv("TRIADE_API_KEY", raising=False)
    validate_api_binding("127.0.0.1")
    validate_api_binding("localhost")


def test_external_binding_requires_key(monkeypatch) -> None:
    monkeypatch.delenv("TRIADE_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="TRIADE_API_KEY"):
        validate_api_binding("0.0.0.0")


def test_external_binding_accepts_configured_key(monkeypatch) -> None:
    monkeypatch.setenv("TRIADE_API_KEY", "test-secret")
    validate_api_binding("0.0.0.0")
