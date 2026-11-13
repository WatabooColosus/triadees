import sqlite3
from unittest.mock import patch

import pytest

from triade.core.safe_file_ops import _register_event


def test_safe_file_event_uses_operational_event_bus():
    with patch("triade.services.event_bus.publish_event") as publish:
        _register_event("safe_file_created", {"path": "runs/evidence.txt"})

    publish.assert_called_once_with(
        "safe_file_created",
        "safe_file_ops",
        {"path": "runs/evidence.txt"},
    )


def test_safe_file_event_does_not_silently_lose_audit_evidence():
    with (
        patch(
            "triade.services.event_bus.publish_event",
            side_effect=sqlite3.OperationalError("database is locked"),
        ),
        pytest.raises(RuntimeError, match="failed to persist"),
    ):
        _register_event("safe_file_created", {"path": "runs/evidence.txt"})
