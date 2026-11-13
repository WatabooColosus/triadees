# Runtime Topology After Reboot · Tríade Ω

## Topología Actual

```
Internet
   │
   ▼
Lightning AI Proxy (HTTPS)
   │  https://lightning.ai/.../web-ui?port=8010
   │
   ▼
API FastAPI (single_port_app)
   │  0.0.0.0:8010
   │  apps.single_port_app:app
   │
   ├──▶ Runtime Always-On (embebido)
   │      └── LifePulse (heartbeat 5s)
   │      └── Resource Governor
   │      └── Scheduler
   │
   ├──▶ Workers (embebidos)
   │      └── WorkerBackgroundService
   │      └── WorkerLoop
   │      └── Task Queue (SQLite)
   │
   ├──▶ Metabolismo (MetabolicCoordinator)
   │      └── health_check (30s)
   │      └── heartbeat (5s)
   │      └── lease_supervision (60s)
   │      └── budget_check (120s)
   │
   ├──▶ Model Router (auto-selección por hardware)
   │
   ├──▶ Ollama Blood
   │      └── http://127.0.0.1:11434
   │
   └──▶ Base de Datos SQLite
          └── triade/memory/triade.db (WAL, 74 MiB, 104 tablas)

Ollama
   │  127.0.0.1:11434 (systemd + on_start.sh)
   │
   ├── qwen2.5:3b-instruct (razonador central)
   ├── qwen3:1.7b (respuesta rápida)
   ├── qwen2.5-coder:3b (código)
   ├── nomic-embed-text (embeddings)
   ├── qwen3:4b (profundidad)
   └── gemma3:4b (alternativo)

Hardware
   ├── NVIDIA L4 23GB VRAM
   ├── 8 vCPU Intel Xeon 2.20GHz
   ├── 31 GB RAM
   └── 369 GB disco (310 GB libres)
```

## Flujo de Datos

1. Usuario accede vía Lightning AI proxy (HTTPS)
2. API FastAPI recibe request en puerto 8010
3. Model Router selecciona modelo según rol y hardware
4. Si es necesario, se envía a Ollama (127.0.0.1:11434)
5. Ollama Blood monitorea estado cognitivo
6. Runtime Always-On ejecuta ciclos de vida cada 60s
7. LifePulse genera heartbeat cada 5s
8. Metabolismo ejecuta necesidades cada 15s
9. Workers procesan cola de tareas
10. Resultados persisten en SQLite (memoria episódica, semántica, qualia)

## Puertos

| Puerto | Servicio | Acceso |
|---|---|---|
| 22 | SSH | Público |
| 8010 | API Tríade | Local + Lightning Proxy |
| 11434 | Ollama | Local únicamente |
| 2222 | Lightning | Interno |
| 9090/9091 | Lightning Metrics | Interno |

## Seguridad

- Ollama: solo local (127.0.0.1), no expuesto públicamente
- API: requiere proxy headers, protegido por Lightning AI
- Base de datos: acceso solo local mediante API
- Sin firewall local (seguridad perimetral GCP/Lightning)
