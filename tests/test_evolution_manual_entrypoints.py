"""Declared manual evolution diagnostics must not be counted as orphan daemons."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from triade.observability.code_graph import _declared_entrypoint_kind


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "relative",
    (
        "reports/evolution/run_normal_worker_recovery.py",
        "reports/evolution/run_measured_normal_rollback.py",
    ),
)
def test_real_evolution_diagnostics_have_verifiable_manual_contract(relative):
    parsed = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    assert _declared_entrypoint_kind(parsed, relative) == "manual_diagnostic"


def test_no_declaration_means_no_implicit_classification():
    parsed = ast.parse("if __name__ == '__main__':\n    pass\n")
    assert _declared_entrypoint_kind(parsed, "reports/evolution/orphan.py") is None


def test_untrusted_reports_path_cannot_claim_manual_exemption():
    parsed = ast.parse('TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"\n')
    assert _declared_entrypoint_kind(parsed, "reports/finance/unsafe.py") is None


def test_scripts_declarations_remain_recognized():
    parsed = ast.parse('TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"\n')
    assert _declared_entrypoint_kind(parsed, "scripts/manual_report.py") == "manual_diagnostic"
