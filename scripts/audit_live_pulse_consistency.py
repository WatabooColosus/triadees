from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def fetch_pulse(base_url: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/system/pulse?sync_relay=true&intent=conversation&urgency=medium"
    result = subprocess.run(
        ["curl", "-s", url],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        return {"status": "error", "error": result.stderr.strip()}
    try:
        return json.loads(result.stdout)
    except Exception as exc:
        return {"status": "error", "error": f"invalid_json: {exc}", "raw": result.stdout[:500]}


def latest_run_path(runs_dir: Path) -> Path | None:
    runs = sorted([p for p in runs_dir.iterdir() if p.is_dir()])
    return runs[-1] if runs else None


def get_check(pulse: dict[str, Any], name: str) -> dict[str, Any]:
    for item in pulse.get("checks", []) or []:
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return {}


def input_context(input_json: dict[str, Any]) -> dict[str, Any]:
    return input_json.get("context") or {}


def summarize_findings(findings: list[dict[str, Any]]) -> dict[str, Any]:
    errors = [f for f in findings if f["level"] == "error"]
    warnings = [f for f in findings if f["level"] == "warning"]
    ok = [f for f in findings if f["level"] == "ok"]
    return {
        "status": "error" if errors else "warning" if warnings else "ok",
        "ok_count": len(ok),
        "warning_count": len(warnings),
        "error_count": len(errors),
    }


def add(findings: list[dict[str, Any]], level: str, name: str, message: str, detail: Any = None) -> None:
    findings.append({
        "level": level,
        "name": name,
        "message": message,
        "detail": detail,
    })


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita consistencia entre Pulso Vivo actual y artefactos del run.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--run-path", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    run_path = Path(args.run_path) if args.run_path else latest_run_path(runs_dir)

    findings: list[dict[str, Any]] = []
    pulse = fetch_pulse(args.base_url)

    if not run_path or not run_path.exists():
        add(findings, "error", "run_path", "No se encontró run para auditar.", str(run_path))
        report = {"summary": summarize_findings(findings), "findings": findings}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    input_json = load_json(run_path / "input.json")
    edge_context = load_json(run_path / "edge_context.json")
    plan = load_json(run_path / "plan.json")
    memory_diff = load_json(run_path / "memory_diff.json")
    system_events = load_json(run_path / "system_events.json", default=[])
    background_candidates = load_json(run_path / "background_neuron_candidates.json", default=[])

    pulse_fed = get_check(pulse, "federation")
    pulse_llm = get_check(pulse, "llm_android_host")
    pulse_router = get_check(pulse, "router")
    pulse_ollama = get_check(pulse, "ollama")
    pulse_docker = get_check(pulse, "docker")

    ctx = input_context(input_json)
    summary = ctx.get("system_pulse_summary") or {}
    summary_fed = summary.get("federation") or {}

    pulse_llm_ok = bool(pulse_llm.get("ok"))
    pulse_fed_ok = bool(pulse_fed.get("ok"))
    summary_llm_hosts = int(summary_fed.get("android_llm_hosts") or 0)
    summary_nodes = int(summary_fed.get("node_count") or 0)

    if pulse.get("status") == "ok":
        add(findings, "ok", "pulse_status", "Pulso actual responde status ok.", pulse.get("summary"))
    else:
        add(findings, "warning", "pulse_status", "Pulso actual no está en ok.", pulse.get("status"))

    if pulse_fed_ok:
        add(findings, "ok", "pulse_federation", "Pulso actual reporta federación activa.", pulse_fed.get("summary"))
    else:
        add(findings, "warning", "pulse_federation", "Pulso actual no reporta federación activa.", pulse_fed)

    if pulse_llm_ok:
        add(findings, "ok", "pulse_llm_android_host", "Pulso actual reporta host LLM Android real.", pulse_llm.get("summary"))
    else:
        add(findings, "warning", "pulse_llm_android_host", "Pulso actual no reporta host LLM Android real.", pulse_llm)

    if summary_nodes >= 1 and summary_llm_hosts >= 1:
        add(findings, "ok", "run_pulse_summary_federation", "input.json conserva datos reales de federación.", summary_fed)
    else:
        level = "error" if pulse_llm_ok or pulse_fed_ok else "warning"
        add(
            findings,
            level,
            "run_pulse_summary_federation",
            "input.json no conserva la federación real del pulso actual.",
            summary_fed,
        )

    if edge_context.get("used_edge") and edge_context.get("accepted") and edge_context.get("node_id"):
        add(findings, "ok", "edge_context", "edge_context.json confirma uso edge aceptado.", {
            "node_id": edge_context.get("node_id"),
            "intent": (edge_context.get("intent_probe") or {}).get("intent"),
        })
    else:
        add(findings, "warning", "edge_context", "edge_context.json no confirma uso edge aceptado.", edge_context)

    plan_edge = plan.get("edge_context") or {}
    if plan_edge.get("used_edge") and plan_edge.get("accepted"):
        add(findings, "ok", "plan_edge_context", "plan.json incorpora edge_context aceptado.", {
            "node_id": plan_edge.get("node_id"),
            "policy": plan_edge.get("policy"),
        })
    else:
        add(findings, "warning", "plan_edge_context", "plan.json no incorpora edge_context aceptado.", plan_edge)

    edge_usage = memory_diff.get("edge_usage") or {}
    if edge_usage.get("used_edge") and edge_usage.get("accepted"):
        add(findings, "ok", "memory_diff_edge_usage", "memory_diff.json registra edge_usage.", {
            "node_id": edge_usage.get("node_id"),
            "intent": edge_usage.get("intent"),
        })
    else:
        add(findings, "warning", "memory_diff_edge_usage", "memory_diff.json no registra edge_usage aceptado.", edge_usage)

    debt_text = json.dumps(system_events, ensure_ascii=False).lower() + " " + json.dumps(background_candidates, ensure_ascii=False).lower()
    false_debt_markers = [
        "0 hosts llm android reales",
        "sin nodos android nativos online",
        "llm_android_host",
    ]
    if pulse_llm_ok and any(marker in debt_text for marker in false_debt_markers):
        add(findings, "error", "obsolete_android_debt", "Hay deuda Android obsoleta aunque el pulso reporta host LLM ok.", {
            "system_events_count": len(system_events) if isinstance(system_events, list) else None,
            "background_candidates_count": len(background_candidates) if isinstance(background_candidates, list) else None,
        })
    else:
        add(findings, "ok", "obsolete_android_debt", "No hay deuda Android obsoleta en system_events/candidates.", None)

    for name, check in [("ollama", pulse_ollama), ("docker", pulse_docker), ("router", pulse_router)]:
        if check.get("ok"):
            add(findings, "ok", f"pulse_{name}", f"{name} aparece activo en pulso actual.", check.get("summary"))
        else:
            add(findings, "warning", f"pulse_{name}", f"{name} no aparece activo en pulso actual.", check)

    report = {
        "mode": "live_pulse_consistency_audit",
        "run_path": str(run_path),
        "pulse_summary": pulse.get("summary"),
        "summary": summarize_findings(findings),
        "findings": findings,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=== LIVE PULSE CONSISTENCY AUDIT ===")
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        print(f"run_path: {run_path}")
        for f in findings:
            icon = "✅" if f["level"] == "ok" else "⚠️" if f["level"] == "warning" else "❌"
            print(f'{icon} {f["name"]}: {f["message"]}')
            if f.get("detail") not in (None, "", [], {}):
                print(f'   detail: {json.dumps(f["detail"], ensure_ascii=False)[:500]}')

    return 2 if report["summary"]["error_count"] else 1 if report["summary"]["warning_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
