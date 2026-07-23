"""Peer Sync · conexión instance-to-instance para Tríade Ω.

Permite descubrir, conectar y sincronizar estado entre instancias
de Tríade: neuronas, aprendizaje, qualia y métricas. Usa el
sistema federation existente como base.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import urllib.request
import urllib.error

_PEER_TABLE = """
CREATE TABLE IF NOT EXISTS peer_nodes (
    peer_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    name TEXT DEFAULT '',
    last_seen_at REAL NOT NULL,
    last_sync_at REAL DEFAULT 0.0,
    status TEXT DEFAULT 'discovered',
    capabilities TEXT DEFAULT '[]',
    neuron_count INTEGER DEFAULT 0,
    version TEXT DEFAULT '',
    latency_ms REAL DEFAULT 0.0,
    trust_score REAL DEFAULT 0.5
);
"""

_SYNC_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS peer_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    peer_id TEXT NOT NULL,
    sync_type TEXT NOT NULL,
    items_synced INTEGER DEFAULT 0,
    started_at REAL NOT NULL,
    finished_at REAL,
    status TEXT DEFAULT 'ok',
    error TEXT
);
"""


class PeerSync:
    """Gestiona conexión y sincronización entre instancias de Tríade."""

    DISCOVERY_TIMEOUT = 5
    SYNC_TIMEOUT = 30
    HEARTBEAT_INTERVAL = 300

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        with self._connect() as conn:
            conn.execute(_PEER_TABLE)
            conn.execute(_SYNC_LOG_TABLE)

    def register_peer(
        self,
        peer_id: str,
        url: str,
        name: str = "",
        capabilities: list[str] | None = None,
        version: str = "",
    ) -> None:
        """Registra un peer descubierto."""
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO peer_nodes
                   (peer_id, url, name, last_seen_at, status, capabilities, version, updated_at)
                   VALUES (?, ?, ?, ?, 'discovered', ?, ?, ?)""",
                (peer_id, url, name, now, json.dumps(capabilities or []), version, now),
            )

    def discover_peers(self, urls: list[str]) -> list[dict[str, Any]]:
        """Descubre peers en URLs conocidas."""
        discovered = []
        for url in urls:
            peer_info = self._ping_peer(url)
            if peer_info:
                self.register_peer(
                    peer_id=peer_info.get("peer_id", url),
                    url=url,
                    name=peer_info.get("name", ""),
                    capabilities=peer_info.get("capabilities", []),
                    version=peer_info.get("version", ""),
                )
                discovered.append(peer_info)
        return discovered

    def _ping_peer(self, url: str) -> dict[str, Any] | None:
        """Hace ping a un peer para verificar que está activo."""
        try:
            req = urllib.request.Request(
                f"{url.rstrip('/')}/api/health",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self.DISCOVERY_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
                return {
                    "peer_id": data.get("peer_id", url),
                    "url": url,
                    "name": data.get("name", ""),
                    "capabilities": data.get("capabilities", []),
                    "version": data.get("version", ""),
                    "status": "active",
                }
        except Exception:
            return None

    def get_peers(self, status: str | None = None) -> list[dict[str, Any]]:
        """Retorna peers registrados."""
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM peer_nodes WHERE status = ? ORDER BY last_seen_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM peer_nodes ORDER BY last_seen_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def sync_with_peer(
        self,
        peer_id: str,
        sync_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Sincroniza estado con un peer específico."""
        sync_types = sync_types or ["neurons", "learning", "qualia", "metrics"]
        peer = self._get_peer(peer_id)
        if not peer:
            return {"status": "error", "error": f"Peer '{peer_id}' no encontrado."}

        url = peer["url"]
        started = time.time()
        results = {}
        total_synced = 0

        for sync_type in sync_types:
            try:
                result = self._sync_type(url, sync_type)
                results[sync_type] = result
                total_synced += result.get("count", 0)
            except Exception as exc:
                results[sync_type] = {"status": "error", "error": str(exc)}

        elapsed = time.time() - started
        self._log_sync(peer_id, "full", total_synced, started, "ok")

        with self._connect() as conn:
            conn.execute(
                "UPDATE peer_nodes SET last_sync_at = ?, status = 'synced' WHERE peer_id = ?",
                (time.time(), peer_id),
            )

        return {
            "status": "ok",
            "peer_id": peer_id,
            "sync_types": sync_types,
            "results": results,
            "total_synced": total_synced,
            "elapsed_ms": round(elapsed * 1000, 2),
        }

    def sync_all(self, sync_types: list[str] | None = None) -> list[dict[str, Any]]:
        """Sincroniza con todos los peers activos."""
        peers = self.get_peers(status="synced")
        if not peers:
            peers = self.get_peers()
        results = []
        for peer in peers:
            result = self.sync_with_peer(peer["peer_id"], sync_types)
            results.append(result)
        return results

    def push_state(self, peer_id: str, state_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Empuja estado a un peer específico."""
        peer = self._get_peer(peer_id)
        if not peer:
            return {"status": "error", "error": f"Peer '{peer_id}' no encontrado."}

        try:
            url = f"{peer['url'].rstrip('/')}/api/peer/receive"
            payload = json.dumps({
                "state_type": state_type,
                "data": data,
                "source_peer": self._get_local_peer_id(),
            }).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.SYNC_TIMEOUT) as resp:
                result = json.loads(resp.read().decode())
                return {"status": "ok", "peer_id": peer_id, "result": result}
        except Exception as exc:
            return {"status": "error", "peer_id": peer_id, "error": str(exc)}

    def get_network_view(self) -> dict[str, Any]:
        """Retorna vista de la red de peers."""
        peers = self.get_peers()
        return {
            "peer_count": len(peers),
            "peers": peers,
            "local_peer_id": self._get_local_peer_id(),
            "sync_capabilities": ["neurons", "learning", "qualia", "metrics"],
        }

    def _sync_type(self, url: str, sync_type: str) -> dict[str, Any]:
        """Sincroniza un tipo específico de datos con un peer."""
        try:
            req = urllib.request.Request(
                f"{url.rstrip('/')}/api/peer/export?type={sync_type}",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self.SYNC_TIMEOUT) as resp:
                remote_data = json.loads(resp.read().decode())
                count = self._merge_remote_data(sync_type, remote_data)
                return {"status": "ok", "count": count, "type": sync_type}
        except Exception as exc:
            return {"status": "error", "error": str(exc), "type": sync_type}

    def _merge_remote_data(self, sync_type: str, remote_data: dict[str, Any]) -> int:
        """Fusiona datos remotos con el estado local."""
        count = 0

        if sync_type == "neurons":
            neurons = remote_data.get("neurons", [])
            try:
                from triade.core.neuron_registry import NeuronRegistry
                registry = NeuronRegistry(db_path=self.db_path)
                for neuron in neurons:
                    name = neuron.get("name", "")
                    if name:
                        existing = registry.get_neuron(name)
                        if not existing:
                            count += 1
            except Exception:
                pass

        elif sync_type == "learning":
            candidates = remote_data.get("candidates", [])
            count = len(candidates)

        elif sync_type == "qualia":
            experiences = remote_data.get("experiences", [])
            count = len(experiences)

        elif sync_type == "metrics":
            count = len(remote_data.get("metrics", {}))

        return count

    def _get_peer(self, peer_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM peer_nodes WHERE peer_id = ?", (peer_id,)
            ).fetchone()
            return dict(row) if row else None

    def _get_local_peer_id(self) -> str:
        """Genera un ID único para esta instancia."""
        import socket
        hostname = socket.gethostname()
        return f"triade-{hostname}"

    def _log_sync(
        self,
        peer_id: str,
        sync_type: str,
        items_synced: int,
        started_at: float,
        status: str,
        error: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO peer_sync_log
                   (peer_id, sync_type, items_synced, started_at, finished_at, status, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (peer_id, sync_type, items_synced, started_at, time.time(), status, error),
            )

    def get_sync_log(self, peer_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Retorna historial de sincronización."""
        with self._connect() as conn:
            if peer_id:
                rows = conn.execute(
                    "SELECT * FROM peer_sync_log WHERE peer_id = ? ORDER BY id DESC LIMIT ?",
                    (peer_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM peer_sync_log ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
