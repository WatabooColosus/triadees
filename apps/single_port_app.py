"""Tríade Ω Single Port App.

Puerto único 8010 para UI, health, router, compatibilidad, memoria semántica y runs locales.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import sqlite3
import subprocess
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from triade.core.life_pulse import LIFE_PULSE
from triade.core.qualia import QUALIA
from triade.core.runner import TriadeRunner
from triade.core.repo_info import repo_info
from triade.core.pulse_context import build_run_context_with_pulse
from triade.core.neuron_candidate_governance import NeuronCandidateGovernance
from triade.federation.contracts import (
    FederatedJobResultPayload,
    FederatedTransportDoctor,
    SignedEnvelope,
    ensure_sandbox_task,
    verify_envelope,
)
from triade.federation.federation import Federation
from triade.federation.relay_client import PublicRelayClient, relay_capabilities_for_federation
from triade.memory.semantic_embedding_engine import SemanticEmbeddingEngine
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.memory.semantic_search import SemanticSearchEngine
from triade.models.compatibility_matrix import ModelCompatibilityMatrix
from triade.models.hardware_profile import HardwareProfiler
from triade.models.model_install_queue import ModelInstallQueue
from triade.models.model_router import ModelRouter
from triade.models.ollama_client import OllamaClient

NODE_TTL_CHECK_SECONDS = int(os.environ.get("TRIADE_NODE_TTL_CHECK_SECONDS", "15"))
NODE_ONLINE_TTL_SECONDS = int(os.environ.get("TRIADE_NODE_ONLINE_TTL_SECONDS", "45"))


def _parse_node_time(value: Any) -> float | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace(" ", "T") + "+00:00").timestamp()
        except ValueError:
            return None


def mark_stale_federated_nodes(ttl_seconds: int = NODE_ONLINE_TTL_SECONDS) -> dict[str, Any]:
    now = time.time()
    stale: list[str] = []
    federation = Federation()
    for node in federation.list_nodes(status="active"):
        node_id = str(node.get("node_id") or "")
        if node_id == "local-pc":
            continue
        seen_at = _parse_node_time(node.get("last_seen_at"))
        if seen_at is None or now - seen_at > ttl_seconds:
            stale.append(node_id)
    for node_id in stale:
        try:
            federation.stale_node(node_id, f"sin heartbeat en {ttl_seconds}s")
        except Exception:
            continue
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "ttl_seconds": ttl_seconds, "stale_count": len(stale), "stale_nodes": stale}


async def node_ttl_monitor() -> None:
    while True:
        try:
            mark_stale_federated_nodes()
        except Exception:
            pass
        await asyncio.sleep(max(5, NODE_TTL_CHECK_SECONDS))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    LIFE_PULSE.start()
    ttl_task = asyncio.create_task(node_ttl_monitor())
    try:
        yield
    finally:
        ttl_task.cancel()
        try:
            await ttl_task
        except asyncio.CancelledError:
            pass
        LIFE_PULSE.stop()


app = FastAPI(title="Tríade Ω Single Port", version="0.9.0", lifespan=lifespan)
ANDROID_APK_PATH = Path(os.environ.get("TRIADE_ANDROID_APK", "apps/static/triade-android-node.apk"))
ANDROID_RUNTIME_DIR = Path(os.environ.get("TRIADE_ANDROID_RUNTIME_DIR", "apps/static/android-runtime"))
ANDROID_LLAMA_CLI_PATH = Path(os.environ.get("TRIADE_ANDROID_LLAMA_CLI", str(ANDROID_RUNTIME_DIR / "llama-cli")))
ANDROID_BASE_MODEL_PATH = Path(os.environ.get("TRIADE_ANDROID_BASE_MODEL", str(ANDROID_RUNTIME_DIR / "triade-base.gguf")))
LOCAL_JOBS: dict[str, dict[str, Any]] = {}

# NOTE: el resto del archivo queda igual que antes de este commit.
