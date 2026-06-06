"""Analizador seguro de conversaciones locales de Triade.

Lee la base SQLite en modo read-only y produce metricas agregadas verificables.
No modifica memoria, no toca identity_core y no consolida aprendizaje.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any


STOPWORDS = {
    "actualiza",
    "ahora",
    "analiza",
    "analizar",
    "como",
    "con",
    "crear",
    "crea",
    "cuando",
    "debe",
    "del",
    "desde",
    "donde",
    "estos",
    "esto",
    "hacer",
    "hasta",
    "hola",
    "para",
    "pero",
    "por",
    "que",
    "quiero",
    "revisa",
    "sobre",
    "solo",
    "tarea",
    "test",
    "tests",
    "triade",
    "tríade",
    "una",
    "uno",
    "usa",
}


@dataclass(slots=True)
class ConversationAnalyzer:
    """Agrega conversaciones persistidas sin exponer textos privados completos."""

    db_path: str | Path = "triade/memory/triade.db"

    def analyze(
        self,
        limit: int = 50,
        since: str | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        limit = max(1, int(limit))
        since = self._validate_since(since)
        with self._connect_readonly() as conn:
            rows = self._fetch_runs(conn, limit=limit, since=since, source=source)
            run_ids = [str(row["run_id"]) for row in rows]
            signals = self._fetch_by_run_id(conn, "signal_states", run_ids)
            crystals = self._fetch_by_run_id(conn, "crystal_states", run_ids)
            reports = self._fetch_by_run_id(conn, "verification_reports", run_ids)
            model_events = self._fetch_by_run_id(conn, "model_events", run_ids)
            episodes = self._fetch_by_run_id(conn, "episodic_memory", run_ids)
            semantic_counts = self._semantic_counts(conn)

        payload = {
            "status": "ok",
            "policy": {
                "mode": "read_only_analysis",
                "identity_core_modified": False,
                "auto_consolidation": False,
                "raw_user_inputs_exposed": False,
            },
            "filters": {"limit": limit, "since": since, "source": source},
            "summary": self._summary(rows, episodes, signals, crystals, reports, model_events, semantic_counts),
            "conversation_patterns": self._conversation_patterns(rows, signals, reports),
            "crystal_evolution": self._crystal_evolution(crystals),
            "model_usage": self._model_usage(model_events),
            "traceability": self._traceability(rows, signals, crystals, reports, model_events, episodes),
            "learning_candidates": self._learning_candidates(rows, signals, reports, crystals),
            "recommendations": self._recommendations(rows, signals, crystals, reports, model_events),
        }
        return payload

    def export_markdown(self, payload: dict[str, Any], path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_markdown(payload), encoding="utf-8")
        return target

    def to_markdown(self, payload: dict[str, Any]) -> str:
        summary = payload["summary"]
        model_usage = payload["model_usage"]
        crystal = payload["crystal_evolution"]
        patterns = payload["conversation_patterns"]
        recommendations = payload["recommendations"]
        learning = payload["learning_candidates"]
        lines = [
            "# Conversation Evolution Report",
            "",
            "Reporte generado desde SQLite local en modo solo lectura. No consolida aprendizaje ni modifica identidad.",
            "",
            "## Resumen",
            "",
            f"- Runs analizados: {summary['runs_analyzed']}",
            f"- Episodios relacionados: {summary['episodes_found']}",
            f"- Q_crystal promedio: {crystal['avg_q_crystal']}",
            f"- Estabilidad promedio: {crystal['avg_stability']}",
            f"- Fallback promedio vs Ollama: {model_usage['fallback_percent']}% fallback / {model_usage['ollama_percent']}% Ollama ok",
            "",
            "## Modelos Usados",
            "",
        ]
        lines.extend(self._bullet_counts(model_usage["by_role_provider_model"]))
        lines.extend([
            "",
            "## Fuentes Principales",
            "",
        ])
        lines.extend(self._bullet_counts(summary["sources"]))
        lines.extend([
            "",
            "## Intenciones Mas Comunes",
            "",
        ])
        lines.extend(self._bullet_counts(patterns["common_intents"]))
        lines.extend([
            "",
            "## Temas Recurrentes",
            "",
        ])
        lines.extend(self._bullet_counts(patterns["recurring_themes"]))
        lines.extend([
            "",
            "## Advertencias Recurrentes",
            "",
        ])
        lines.extend(self._bullet_counts(patterns["recurring_warnings"]))
        lines.extend([
            "",
            "## Evolucion Del Cristal",
            "",
            f"- Delta Q promedio: {crystal['avg_q_delta']}",
            f"- Delta estabilidad promedio: {crystal['avg_stability_delta']}",
            f"- Mejoras detectadas: {crystal['improvement_count']}",
            f"- Degradaciones detectadas: {crystal['degradation_count']}",
            "",
            "## Recomendaciones Para Mejorar El Nucleo",
            "",
        ])
        lines.extend(f"- {item}" for item in recommendations)
        lines.extend([
            "",
            "## Aprendizajes Candidatos",
            "",
        ])
        lines.extend(f"- {item}" for item in learning["candidate_themes"])
        lines.extend([
            "",
            "## Que NO Debe Consolidarse Aun",
            "",
        ])
        lines.extend(f"- {item}" for item in learning["do_not_consolidate"])
        lines.append("")
        return "\n".join(lines)

    def _connect_readonly(self) -> sqlite3.Connection:
        path = Path(self.db_path)
        if not path.exists():
            raise FileNotFoundError(f"No existe la base de memoria: {path}")
        uri = f"file:{path.resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _validate_since(value: str | None) -> str | None:
        if not value:
            return None
        datetime.strptime(value, "%Y-%m-%d")
        return value

    @staticmethod
    def _fetch_runs(conn: sqlite3.Connection, limit: int, since: str | None, source: str | None) -> list[sqlite3.Row]:
        clauses: list[str] = []
        params: list[Any] = []
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        if source == "single-port-ui":
            clauses.append("source IN (?, ?)")
            params.extend(["single-port-ui", "single-port-react-ui"])
        elif source:
            clauses.append("source = ?")
            params.append(source)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        return conn.execute(
            f"""SELECT run_id, source, user_input, status, model_hypothalamus, model_central, created_at, closed_at
            FROM runs{where} ORDER BY id DESC LIMIT ?""",
            params,
        ).fetchall()

    @staticmethod
    def _fetch_by_run_id(conn: sqlite3.Connection, table: str, run_ids: list[str]) -> list[dict[str, Any]]:
        if not run_ids:
            return []
        placeholders = ",".join("?" for _ in run_ids)
        rows = conn.execute(f"SELECT * FROM {table} WHERE run_id IN ({placeholders})", run_ids).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _semantic_counts(conn: sqlite3.Connection) -> dict[str, int]:
        tables = ["semantic_memory", "semantic_documents", "semantic_embeddings"]
        counts: dict[str, int] = {}
        existing = {
            str(row["name"])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        for table in tables:
            if table not in existing:
                counts[table] = 0
                continue
            counts[table] = int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])
        return counts

    def _summary(
        self,
        rows: list[sqlite3.Row],
        episodes: list[dict[str, Any]],
        signals: list[dict[str, Any]],
        crystals: list[dict[str, Any]],
        reports: list[dict[str, Any]],
        model_events: list[dict[str, Any]],
        semantic_counts: dict[str, int],
    ) -> dict[str, Any]:
        return {
            "runs_analyzed": len(rows),
            "episodes_found": len(episodes),
            "signals_found": len(signals),
            "crystals_found": len(crystals),
            "verification_reports_found": len(reports),
            "model_events_found": len(model_events),
            "sources": dict(Counter(str(row["source"] or "unknown") for row in rows).most_common()),
            "semantic_counts": semantic_counts,
        }

    def _conversation_patterns(
        self,
        rows: list[sqlite3.Row],
        signals: list[dict[str, Any]],
        reports: list[dict[str, Any]],
    ) -> dict[str, Any]:
        themes = Counter()
        for row in rows:
            themes.update(self._keywords(str(row["user_input"] or "")))
        intents = Counter(str(item.get("intent") or "unknown") for item in signals)
        risks = Counter(str(item.get("risk") or "unknown") for item in signals)
        warnings = Counter()
        for report in reports:
            warnings.update(self._json_list(report.get("warnings")))
            warnings.update(self._json_list(report.get("errors")))
        return {
            "recurring_themes": dict(themes.most_common(12)),
            "common_intents": dict(intents.most_common()),
            "risk_levels": dict(risks.most_common()),
            "recurring_warnings": dict(warnings.most_common(12)),
        }

    @staticmethod
    def _crystal_evolution(crystals: list[dict[str, Any]]) -> dict[str, Any]:
        q_values = [float(item.get("q_crystal") or 0.0) for item in crystals]
        stability_values = [float(item.get("stability") or 0.0) for item in crystals]
        q_deltas = [float(item.get("q_delta") or 0.0) for item in crystals]
        stability_deltas = [float(item.get("stability_delta") or 0.0) for item in crystals]
        temporal = Counter(str(item.get("temporal_status") or "unknown") for item in crystals)
        return {
            "avg_q_crystal": round(mean(q_values), 3) if q_values else 0.0,
            "avg_stability": round(mean(stability_values), 3) if stability_values else 0.0,
            "avg_q_delta": round(mean(q_deltas), 3) if q_deltas else 0.0,
            "avg_stability_delta": round(mean(stability_deltas), 3) if stability_deltas else 0.0,
            "temporal_status": dict(temporal.most_common()),
            "improvement_count": int(sum(1 for item in crystals if str(item.get("temporal_status")) == "improving" or float(item.get("q_delta") or 0.0) > 0)),
            "degradation_count": int(sum(1 for item in crystals if str(item.get("temporal_status")) in {"degrading", "critical"} or float(item.get("q_delta") or 0.0) < -0.05)),
        }

    @staticmethod
    def _model_usage(model_events: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(model_events)
        ollama_ok = sum(1 for item in model_events if item.get("provider") == "ollama" and int(item.get("ok") or 0) == 1)
        fallback = sum(1 for item in model_events if item.get("provider") in {"template", "rules"} or int(item.get("ok") or 0) == 0)
        counts = Counter(
            f"{item.get('role', 'unknown')}:{item.get('provider', 'unknown')}:{item.get('model_name', 'unknown')}:ok={int(item.get('ok') or 0)}"
            for item in model_events
        )
        quality_by_role: dict[str, list[float]] = defaultdict(list)
        for item in model_events:
            quality_by_role[str(item.get("role") or "unknown")].append(float(item.get("quality_score") or 0.0))
        return {
            "total_events": total,
            "ollama_ok_events": ollama_ok,
            "fallback_or_failed_events": fallback,
            "ollama_percent": round((ollama_ok / total) * 100, 2) if total else 0.0,
            "fallback_percent": round((fallback / total) * 100, 2) if total else 0.0,
            "by_role_provider_model": dict(counts.most_common()),
            "avg_quality_by_role": {role: round(mean(values), 3) for role, values in quality_by_role.items()},
        }

    @staticmethod
    def _traceability(
        rows: list[sqlite3.Row],
        signals: list[dict[str, Any]],
        crystals: list[dict[str, Any]],
        reports: list[dict[str, Any]],
        model_events: list[dict[str, Any]],
        episodes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        run_ids = {str(row["run_id"]) for row in rows}
        coverage = {
            "signals": {str(item.get("run_id")) for item in signals},
            "crystals": {str(item.get("run_id")) for item in crystals},
            "verification_reports": {str(item.get("run_id")) for item in reports},
            "model_events": {str(item.get("run_id")) for item in model_events},
            "episodes": {str(item.get("run_id")) for item in episodes},
        }
        return {
            key: {
                "present": len(values & run_ids),
                "missing": sorted(run_ids - values)[:20],
                "coverage_percent": round((len(values & run_ids) / len(run_ids)) * 100, 2) if run_ids else 0.0,
            }
            for key, values in coverage.items()
        }

    def _learning_candidates(
        self,
        rows: list[sqlite3.Row],
        signals: list[dict[str, Any]],
        reports: list[dict[str, Any]],
        crystals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        themes = Counter()
        for row in rows:
            themes.update(self._keywords(str(row["user_input"] or "")))
        clean_themes = [f"Patron recurrente: {theme} ({count} apariciones)" for theme, count in themes.most_common(8) if count >= 2]
        warnings = Counter()
        for report in reports:
            warnings.update(self._json_list(report.get("warnings")))
        if warnings:
            clean_themes.extend([f"Advertencia recurrente candidata: {text}" for text, _ in warnings.most_common(5)])
        return {
            "candidate_themes": clean_themes or ["No hay recurrencia suficiente para proponer candidatos de learning."],
            "do_not_consolidate": [
                "Entradas textuales completas de usuarios sin aprobacion humana.",
                "Inferencias de identidad, preferencias o datos privados no verificadas.",
                "Patrones basados en fallos de modelo o fallback sin revisar causa tecnica.",
                "Temas con una sola aparicion o sin evidencia en verification_reports.",
            ],
            "auto_consolidated": False,
            "signals_considered": len(signals),
            "crystals_considered": len(crystals),
        }

    def _recommendations(
        self,
        rows: list[sqlite3.Row],
        signals: list[dict[str, Any]],
        crystals: list[dict[str, Any]],
        reports: list[dict[str, Any]],
        model_events: list[dict[str, Any]],
    ) -> list[str]:
        recommendations: list[str] = []
        trace_gaps = []
        run_count = len(rows)
        if run_count and len(signals) < run_count:
            trace_gaps.append("senales")
        if run_count and len(crystals) < run_count:
            trace_gaps.append("cristal")
        if run_count and len(reports) < run_count:
            trace_gaps.append("verificacion")
        if trace_gaps:
            recommendations.append(f"Completar trazabilidad por run en: {', '.join(trace_gaps)}.")
        usage = self._model_usage(model_events)
        if usage["fallback_percent"] > 35:
            recommendations.append("Investigar fallback recurrente: registrar causa exacta y separar fallback de modelo ausente vs salida invalida.")
        crystal = self._crystal_evolution(crystals)
        if crystal["degradation_count"] > crystal["improvement_count"]:
            recommendations.append("Revisar reglas de regulacion del Cristal para contextos con degradacion repetida.")
        recommendations.append("Mantener aprendizaje conversacional como candidatos revisables, no como consolidacion automatica.")
        recommendations.append("Separar progresivamente orquestacion del runner en etapas testeables: senales, memoria, cristal, plan, modelos y verificacion.")
        return recommendations

    @staticmethod
    def _json_list(value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        try:
            parsed = json.loads(str(value))
        except json.JSONDecodeError:
            return [str(value)]
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
        return [str(parsed)]

    @staticmethod
    def _keywords(text: str) -> list[str]:
        words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9_]{4,}", text.lower())
        return [word for word in words if word not in STOPWORDS][:40]

    @staticmethod
    def _bullet_counts(counts: dict[str, Any]) -> list[str]:
        if not counts:
            return ["- Sin datos."]
        return [f"- {key}: {value}" for key, value in counts.items()]


def add_analyze_conversations_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")
    parser.add_argument("--limit", type=int, default=50, help="Cantidad maxima de runs")
    parser.add_argument("--json", action="store_true", help="Imprime JSON completo")
    parser.add_argument("--since", default=None, help="Fecha minima YYYY-MM-DD")
    parser.add_argument("--source", choices=["console", "single-port-ui", "test"], default=None, help="Filtra fuente")
    parser.add_argument("--export", default=None, help="Exporta reporte Markdown")
