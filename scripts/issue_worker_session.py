"""Emite una sesión local limitada para el worker sin leer cookies del navegador.

Las credenciales llegan sólo por variables de entorno y el token se guarda en
``data/secrets``. No se imprime la contraseña ni el token.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parent.parent / "data" / "secrets" / "triade_worker_session.json"

username = os.environ.get("TRIADE_ADMIN_USERNAME", "").strip()
password = os.environ.get("TRIADE_ADMIN_PASSWORD", "")
base = os.environ.get("TRIADE_API_URL", "http://127.0.0.1:8010").rstrip("/")
if not username or not password:
    raise SystemExit("Faltan TRIADE_ADMIN_USERNAME y TRIADE_ADMIN_PASSWORD")
request = urllib.request.Request(
    f"{base}/api/auth/login",
    data=json.dumps({"username": username, "password": password}).encode(),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=30) as response:
    payload = json.loads(response.read().decode())
token = str(payload.get("access_token") or "")
if not token:
    raise SystemExit("El login no devolvió access_token")
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps({"access_token": token, "role": payload.get("role"), "source": "admin_login", "api": base}, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": "issued", "path": str(OUT), "role": payload.get("role"), "api": base}))
