"""Compression: compresión de memoria (resumir episodios, deduplicar semántica).

Reduce el volumen de memoria preservando información esencial.
Opera sobre tablas existentes sin crear nuevas.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now


@dataclass(slots=True)
class CompressionResult:
    operation: str = ""
    items_processed: int = 0
    items_removed: int = 0
    items_merged: int = 0
    space_saved_bytes: int = 0
    details: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation, "items_processed": self.items_processed,
            "items_removed": self.items_removed, "items_merged": self.items_merged,
            "space_saved_bytes": self.space_saved_bytes,
            "details": list(self.details), "created_at": self.created_at,
        }


class MemoryCompressor:
    """Compresión de memoria episódica y semántica."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def deduplicate_semantic(self) -> CompressionResult:
        """Elimina entradas semánticas duplicadas (mismo key+value)."""
        processed = 0
        removed = 0
        details: list[str] = []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, key, value, confidence FROM semantic_memory ORDER BY confidence DESC"
            ).fetchall()
            seen: dict[str, list[str]] = {}
            for row in rows:
                combo = f"{row['key']}||{row['value']}"
                rid = str(row["id"])
                if combo in seen:
                    seen[combo].append(rid)
                else:
                    seen[combo] = [rid]
                processed += 1
            for combo, ids in seen.items():
                if len(ids) > 1:
                    to_remove = ids[1:]
                    for rid in to_remove:
                        conn.execute("DELETE FROM semantic_memory WHERE id = ?", (rid,))
                        removed += 1
                    details.append(f"Duplicate {combo[:40]}: {len(ids)} copies, {len(to_remove)} removed")
        return CompressionResult(
            operation="deduplicate_semantic", items_processed=processed,
            items_removed=removed, details=details,
        )

    def compress_episodes(self, *, max_age_days: int = 90, keep_min: int = 10) -> CompressionResult:
        """Comprime episodios antiguos conservando los más recientes y relevantes."""
        processed = 0
        removed = 0
        details: list[str] = []
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) as c FROM episodic_memory").fetchone()["c"]
            if total <= keep_min:
                return CompressionResult(
                    operation="compress_episodes", items_processed=total,
                    details=["No hay episodios suficientes para comprimir."],
                )
            rows = conn.execute(
                """SELECT id, run_id, created_at FROM episodic_memory
                ORDER BY created_at ASC LIMIT ?""",
                (total - keep_min,),
            ).fetchall()
            for row in rows:
                conn.execute("DELETE FROM episodic_memory WHERE id = ?", (row["id"],))
                processed += 1
                removed += 1
            details.append(f"Episodios antiguos eliminados: {removed}")
        return CompressionResult(
            operation="compress_episodes", items_processed=processed,
            items_removed=removed, details=details,
        )

    def merge_similar_signals(self, *, same_type_threshold: float = 0.9) -> CompressionResult:
        """Fusiona señales Qualia del mismo tipo y run en una sola."""
        processed = 0
        merged = 0
        details: list[str] = []
        with self._connect() as conn:
            runs = conn.execute(
                "SELECT DISTINCT run_id FROM qualia_signals"
            ).fetchall()
            for run_row in runs:
                run_id = str(run_row["run_id"])
                signals = conn.execute(
                    "SELECT id, signal_type, intensity, valence FROM qualia_signals WHERE run_id = ? ORDER BY created_at",
                    (run_id,),
                ).fetchall()
                type_groups: dict[str, list[sqlite3.Row]] = {}
                for sig in signals:
                    sig_type = str(sig["signal_type"] or "unknown")
                    type_groups.setdefault(sig_type, []).append(sig)
                for sig_type, group in type_groups.items():
                    if len(group) <= 1:
                        continue
                    keep = group[0]
                    for dup in group[1:]:
                        conn.execute("DELETE FROM qualia_signals WHERE id = ?", (dup["id"],))
                        merged += 1
                    processed += len(group)
                if merged > 0:
                    details.append(f"Run {run_id[:12]}: {merged} señales fusionadas")
        return CompressionResult(
            operation="merge_similar_signals", items_processed=processed,
            items_merged=merged, details=details,
        )

    def summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            episodic = conn.execute("SELECT COUNT(*) as c FROM episodic_memory").fetchone()["c"]
            semantic = conn.execute("SELECT COUNT(*) as c FROM semantic_memory").fetchone()["c"]
            signals = conn.execute("SELECT COUNT(*) as c FROM qualia_signals").fetchone()["c"]
        return {
            "episodic_count": episodic,
            "semantic_count": semantic,
            "qualia_signals_count": signals,
        }
