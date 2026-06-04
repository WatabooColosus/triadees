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
            existing = federation.get_node(node_id)
            if existing:
                previous = existing.get("capabilities") or {}
                for key in ("benchmark_score", "last_benchmark", "compute_status", "last_benchmark_error"):
                    if key in previous and key not in capabilities:
                        capabilities[key] = previous[key]
                if "benchmark_score" in capabilities:
                    capabilities["model_support"] = model_support_from_capabilities(capabilities)
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

    def preprocess_text_online(
        self,
        federation: Federation,
        text: str,
        max_chunk_chars: int = 1200,
        wait_timeout: float = 45.0,
    ) -> dict[str, Any]:
        sync = self.sync_nodes_to_federation(federation)
        jobs = []
        for node in sync["nodes"]:
            capabilities = node.get("capabilities") or {}
            if not capabilities.get("online"):
                continue
            if "preprocess_text" not in capabilities.get("allowed_tasks", []):
                continue
            job_id = self.create_job(
                str(node["node_id"]),
                task="preprocess_text",
                payload={"text": text, "max_chunk_chars": max_chunk_chars},
                seconds=1.0,
            )
            result_job = self.wait_for_job(job_id, timeout=wait_timeout)
            jobs.append({"job_id": job_id, "node_id": node["node_id"], "job": result_job})
        completed = [job for job in jobs if job["job"].get("status") == "completed"]
        return {
            "status": "ok",
            "synced": sync["synced"],
            "submitted": len(jobs),
            "completed": len(completed),
            "results": jobs,
            "model_feed": _merge_preprocess_results(completed),
        }

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
    memory = float(raw.get("ram_available_gb") or raw.get("device_memory_gb") or 0.0)
    online = bool(node.get("online"))
    native_android = bool(raw.get("native_android") or raw.get("app_node"))
    resource_limit = max(0, min(100, int(raw.get("resource_limit_percent") or 60))) if native_android else 0
    authorized_cpu = int(raw.get("cpu_authorized_count") or max(1, int(cpu * (resource_limit / 100.0)))) if native_android else 0
    authorized_memory = float(raw.get("ram_authorized_gb") or (memory * (resource_limit / 100.0))) if native_android else 0.0
    capability_tier = _browser_tier(cpu, memory)
    allowed_tasks = raw.get("allowed_tasks") if isinstance(raw.get("allowed_tasks"), list) else ["echo", "sha256", "browser_benchmark", "preprocess_text"]
    capabilities = {
        **raw,
        "source": "public_relay",
        "relay_url": relay_url.rstrip("/"),
        "relay_node_id": node.get("node_id"),
        "online": online,
        "tier": "medium" if native_android and capability_tier == "low" and cpu >= 4 else capability_tier,
        "browser_tier": raw.get("tier", "browser"),
        "native_android": native_android,
        "cpu_count": cpu,
        "cpu_authorized_count": authorized_cpu,
        "device_memory_gb": memory,
        "ram_available_gb": memory,
        "ram_authorized_gb": authorized_memory,
        "resource_limit_percent": resource_limit,
        "federation_complete": bool(native_android and online and resource_limit > 0),
        "allowed_tasks": allowed_tasks,
        "model_support": model_support_from_capabilities({
            "cpu_count": cpu,
            "cpu_authorized_count": authorized_cpu,
            "device_memory_gb": memory,
            "ram_authorized_gb": authorized_memory,
            "online": online,
            "native_android": native_android,
            "background_execution": bool(raw.get("background_execution")),
            "resource_limit_percent": resource_limit,
        }),
    }
    return capabilities


def model_support_from_capabilities(capabilities: dict[str, Any]) -> dict[str, Any]:
    online = bool(capabilities.get("online", True))
    score = int(capabilities.get("benchmark_score") or 0)
    cpu = int(capabilities.get("cpu_count") or 1)
    native_android = bool(capabilities.get("native_android"))
    authorized_cpu = int(capabilities.get("cpu_authorized_count") or (cpu if native_android else 0))
    memory = float(capabilities.get("ram_authorized_gb") or capabilities.get("device_memory_gb") or 0.0) if native_android else 0.0
    ready = online and native_android and authorized_cpu >= 1 and memory >= 0.5
    recommended = "android_native_cpu_feed" if ready else "not_federated"
    assist = ["hashing", "benchmark", "preprocess", "context_chunking", "background_cpu_feed"] if ready else ["heartbeat"]
    return {
        "ready_for_model_management": ready,
        "local_ollama": False,
        "recommended_use": recommended,
        "can_host_llm": False,
        "can_assist": assist,
        "benchmark_score": score,
        "authorized_cpu_count": authorized_cpu,
        "authorized_ram_gb": memory,
        "resource_limit_percent": int(capabilities.get("resource_limit_percent") or 0),
        "note": "Nodo Android nativo: alimenta modelos locales con CPU/RAM autorizadas y servicio en primer plano." if native_android
        else "Browser descartado: no invierte recursos nativos en el modelo local.",
    }


def _browser_tier(cpu: int, memory_gb: float) -> str:
    if cpu >= 8 and memory_gb >= 6:
        return "medium"
    if cpu >= 4 and memory_gb >= 2:
        return "low"
    return "low"


def _merge_preprocess_results(completed_jobs: list[dict[str, Any]]) -> dict[str, Any]:
    keyword_counts: dict[str, int] = {}
    chunks: list[dict[str, Any]] = []
    total_words = 0
    total_chars = 0
    for item in completed_jobs:
        result = item["job"].get("result") or {}
        total_words = max(total_words, int(result.get("word_count") or 0))
        total_chars = max(total_chars, int(result.get("chars") or 0))
        for keyword in result.get("keywords") or []:
            term = str(keyword.get("term") or "").strip().lower()
            if term:
                keyword_counts[term] = keyword_counts.get(term, 0) + int(keyword.get("count") or 0)
        for chunk in result.get("chunks") or []:
            if isinstance(chunk, dict):
                chunks.append({**chunk, "node_id": item["node_id"]})
    keywords = [
        {"term": term, "count": count}
        for term, count in sorted(keyword_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:24]
    ]
    return {
        "ready_for_local_model": bool(completed_jobs),
        "chars": total_chars,
        "word_count": total_words,
        "approx_tokens": int(total_words * 1.35) if total_words else 0,
        "keywords": keywords,
        "chunks": chunks,
        "note": "Contexto preprocesado por nodos browser autorizados antes de invocar modelos locales.",
    }
