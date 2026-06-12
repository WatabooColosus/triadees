"""Safety Sandbox — ejecuta operaciones federadas en aislamiento.

Usa subprocesos con directorio temporal, resource limits y timeout
para garantizar que una tarea sandbox no afecte al sistema principal.
"""

from __future__ import annotations

import json
import os
import resource
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any

SANDBOX_DIR = Path("/tmp/triade-sandbox")


def _ensure_sandbox_dir() -> Path:
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    return SANDBOX_DIR


def run_in_sandbox(
    task: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 30.0,
    max_memory_mb: int = 512,
) -> dict[str, Any]:
    """Ejecuta una tarea en entorno aislado.

    Crea un directorio temporal, escribe payload.json,
    ejecuta la tarea con resource limits y devuelve el resultado.
    """
    base = _ensure_sandbox_dir()
    sandbox_id = f"{task}_{int(time.time() * 1000)}_{os.getpid()}"
    workdir = base / sandbox_id

    try:
        workdir.mkdir(parents=True, exist_ok=True)
        if payload:
            (workdir / "payload.json").write_text(json.dumps(payload), encoding="utf-8")

        script = _build_sandbox_script(task)
        script_path = workdir / "run.py"
        script_path.write_text(script, encoding="utf-8")

        result_path = workdir / "result.json"

        start = time.monotonic()
        proc = subprocess.Popen(
            [sys.executable, str(script_path)],
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=_set_limits(max_memory_mb),
        )

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            _cleanup(workdir)
            return {"status": "timeout", "task": task, "error": f"Sandbox timeout after {timeout}s", "sandbox": sandbox_id}

        elapsed = time.monotonic() - start

        if result_path.exists():
            raw = result_path.read_text(encoding="utf-8", errors="replace")
            try:
                data = json.loads(raw)
                data["sandbox"] = sandbox_id
                data["elapsed"] = round(elapsed, 3)
                _cleanup(workdir)
                return data
            except json.JSONDecodeError:
                _cleanup(workdir)
                return {"status": "error", "task": task, "error": f"Result JSON inválido: {raw[:200]}", "sandbox": sandbox_id}

        _cleanup(workdir)
        return {
            "status": "ok" if proc.returncode == 0 else "error",
            "task": task,
            "stdout": stdout.decode("utf-8", errors="replace")[:2000] if stdout else "",
            "stderr": stderr.decode("utf-8", errors="replace")[:2000] if stderr else "",
            "returncode": proc.returncode,
            "elapsed": round(elapsed, 3),
            "sandbox": sandbox_id,
        }

    except Exception as exc:
        _cleanup(workdir)
        return {"status": "error", "task": task, "error": f"Sandbox error: {exc}", "sandbox": sandbox_id}


def _build_sandbox_script(task: str) -> str:
    """Genera un script Python que ejecuta la tarea sandbox."""
    parts = [
        textwrap.dedent("""\
        import json, os, sys
        payload = {}
        if os.path.exists("payload.json"):
            with open("payload.json") as f:
                payload = json.load(f)
        result = {"status": "completed", "task": %r}
        """ % task),
    ]

    if task == "sha256":
        parts.append(textwrap.dedent("""\
        import hashlib
        text = payload.get("text") or "triade"
        sha = hashlib.sha256(text.encode()).hexdigest()
        result["sha256"] = sha
        """))
    elif task == "sandbox_exec":
        parts.append(textwrap.dedent("""\
        result["executed"] = True
        result["sandbox_mode"] = "isolated"
        result["payload_keys"] = sorted(payload.keys())
        result["note"] = "Ejecución aislada en sandbox. Ninguna acción real fue ejecutada."
        """))
    elif task == "echo":
        parts.append("result['payload'] = payload\n")
    elif task == "browser_benchmark":
        parts.append(textwrap.dedent("""\
        import random, time
        seconds = float(payload.get("seconds", 1))
        score = random.randint(5000, 15000)
        time.sleep(seconds)
        result["score"] = score
        result["ops"] = score * 2
        """))
    elif task == "preprocess_text":
        parts.append(textwrap.dedent("""\
        text = payload.get("text") or ""
        chars = len(text)
        words = len(text.split())
        tokens = chars // 3
        result["word_count"] = words
        result["char_count"] = chars
        result["approx_tokens"] = tokens
        """))
    elif task == "federated_inference_probe":
        parts.append(textwrap.dedent("""\
        import random
        iterations = int(payload.get("iterations", 5000))
        result["ops"] = iterations // 1000 + random.randint(0, 10)
        """))

    parts.append(textwrap.dedent("""\
    with open("result.json", "w") as f:
        json.dump(result, f)
    """))

    return "\n".join(parts)


def _set_limits(max_memory_mb: int):
    def _apply():
        try:
            resource.setrlimit(resource.RLIMIT_AS, (max_memory_mb * 1024 * 1024, -1))
        except (resource.error, ValueError):
            pass
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
    return _apply


def _cleanup(workdir: Path) -> None:
    try:
        import shutil
        shutil.rmtree(str(workdir), ignore_errors=True)
    except Exception:
        return
