"""Cliente local para alimentar Tríade desde el relay público."""

from __future__ import annotations

import time
from typing import Any

import httpx

from triade.federation.federation import Federation


class PublicRelayClient:
    """Orquesta nodos browser autorizados sin exponer memoria local."""

    def __init__(self, base_url: str, admin_token: str, timeout: float = 20.0, client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token
        self.timeout = timeout
        self.client = client or httpx.Client(timeout=timeout)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.admin_token}"}

    def list_nodes(self) -> list[dict[str, Any]]:
        response = self.client.get(f"{self.base_url}/api/nodes", headers=self.headers)
        response.raise_for_status()
        return response.json().get("nodes", [])

    def list_jobs(self) -> list[dict[str, Any]]:
        response = self.client.get(f"{self.base_url}/api/jobs", headers=self.headers)
        response.raise_for_status()
        return response.json().get("jobs", [])

    def create_job(
        self,
        node_id: str,
        task: str = "browser_benchmark",
        payload: dict[str, Any] | None = None,
        seconds: float = 2.0,
    ) -> str:
        response = self.client.post(
            f"{self.base_url}/api/jobs",
            headers=self.headers,
            json={"node_id": node_id, "task": task, "payload": payload or {}, "seconds": seconds},
        )
        response.raise_for_status()
        return str(response.json()["job_id"])

    def wait_for_job(self, job_id: str, timeout: float = 30.0, interval: float = 1.0) -> dict[str, Any]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for job in self.list_jobs():
                if job.get("job_id") == job_id:
                    if job.get("status") in {"completed", "failed"}:
                        return job
            time.sleep(interval)
        return {"job_id": job_id, "status": "timeout", "result": None, "error": "Tiempo de espera agotado."}

    def sync_nodes_to_federation(self, federation: Federation) -> dict[str, Any]:
        synced = []
        for node in self.list_nodes():
            node_id = str(node.get("node_id") or "").strip()
            if not node_id:
                continue
            capabilities = relay_capabilities_for_federation(node, self.base_url)
            registered = federation.register_node(
                node_id=node_id,
                name=str(node.get("display_name") or node_id),
                owner="public-relay",
                endpoint=self.base_url,
                trust_level="low",
                permissions=["publish_capabilities", "request_compute"],
                capabilities=capabilities,
            )
            synced.append(registered)
        return {"status": "ok", "synced": len(synced), "nodes": synced}

    def benchmark_online_nodes(self, federation: Federation, seconds: float = 2.0, wait_timeout: float = 45.0) -> dict[str, Any]:
        sync = self.sync_nodes_to_federation(federation)
        jobs = []
        for node in sync["nodes"]:
            if not (node.get("capabilities") or {}).get("online"):
                continue
            job_id = self.create_job(str(node["node_id"]), task="browser_benchmark", seconds=seconds)
            result_job = self.wait_for_job(job_id, timeout=wait_timeout)
            updated = self._update_node_with_job_result(federation, node, result_job)
            jobs.append({"job_id": job_id, "node_id": node["node_id"], "job": result_job, "node": updated})
        return {"status": "ok", "synced": sync["synced"], "benchmarks": jobs}

    def _update_node_with_job_result(
        self,
        federation: Federation,
        node: dict[str, Any],
        job: dict[str, Any],
    ) -> dict[str, Any]:
        capabilities = dict(node.get("capabilities") or {})
        if job.get("status") == "completed" and isinstance(job.get("result"), dict):
            result = dict(job["result"])
            capabilities["last_benchmark"] = result
            capabilities["benchmark_score"] = int(result.get("score") or 0)
            capabilities["compute_status"] = "ready"
        else:
            capabilities["compute_status"] = "degraded"
            capabilities["last_benchmark_error"] = job.get("error") or job.get("status")
        capabilities["model_support"] = model_support_from_capabilities(capabilities)
        return federation.update_capabilities(str(node["node_id"]), capabilities)


def relay_capabilities_for_federation(node: dict[str, Any], relay_url: str) -> dict[str, Any]:
    raw = dict(node.get("capabilities") or {})
    cpu = int(raw.get("cpu_count") or raw.get("hardware_concurrency") or 1)
    memory = float(raw.get("device_memory_gb") or 0.0)
    online = bool(node.get("online"))
    capability_tier = _browser_tier(cpu, memory)
    capabilities = {
        **raw,
        "source": "public_relay",
        "relay_url": relay_url.rstrip("/"),
        "relay_node_id": node.get("node_id"),
        "online": online,
        "tier": capability_tier,
        "browser_tier": raw.get("tier", "browser"),
        "cpu_count": cpu,
        "device_memory_gb": memory,
        "allowed_tasks": ["echo", "sha256", "browser_benchmark"],
        "model_support": model_support_from_capabilities({"cpu_count": cpu, "device_memory_gb": memory, "online": online}),
    }
    return capabilities


def model_support_from_capabilities(capabilities: dict[str, Any]) -> dict[str, Any]:
    online = bool(capabilities.get("online", True))
    score = int(capabilities.get("benchmark_score") or 0)
    cpu = int(capabilities.get("cpu_count") or 1)
    memory = float(capabilities.get("device_memory_gb") or 0.0)
    ready = online and cpu >= 2 and memory >= 1.0
    return {
        "ready_for_model_management": ready,
        "local_ollama": False,
        "recommended_use": "browser_preprocess" if ready else "heartbeat_only",
        "can_host_llm": False,
        "can_assist": ["hashing", "benchmark", "preprocess"] if ready else ["heartbeat"],
        "benchmark_score": score,
        "note": "Nodo browser: alimenta planificación y tareas ligeras; no hospeda Ollama ni modelos nativos.",
    }


def _browser_tier(cpu: int, memory_gb: float) -> str:
    if cpu >= 8 and memory_gb >= 6:
        return "medium"
    if cpu >= 4 and memory_gb >= 2:
        return "low"
    return "low"
