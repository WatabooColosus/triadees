"""Tests de salida JSON del CLI."""

from __future__ import annotations

import io
import json
import sys

from triade_digimon import print_json


def test_print_json_reconfigures_stdout_for_unicode(monkeypatch) -> None:
    buffer = io.BytesIO()
    stdout = io.TextIOWrapper(buffer, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stdout)

    print_json({"response": "Triade Omega: Tríade Ω con Δ estable"})

    stdout.flush()
    payload = json.loads(buffer.getvalue().decode("utf-8"))
    assert payload["response"] == "Triade Omega: Tríade Ω con Δ estable"
