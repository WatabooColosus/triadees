# Server Runtime Topology · Tríade Ω

**Generated:** 2026-07-30  
**SHA:** b0613ea5

```
┌─────────────────────────────────────────────────────────────────┐
│                        INTERNET                                 │
│  Lightning AI Proxy (HTTPS)                                     │
│  → https://lightning.ai/.../web-ui?port=8010                    │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FASTAPI SINGLE PORT (8010)                    │
│  apps.single_port_app:app                                       │
│                                                                 │
│  ├── API Router (/api/*)                                        │
│  │   ├── /api/health         → System health check              │
│  │   ├── /health/live        → Liveness probe                   │
│  │   ├── /api/runtime/*      → Heartbeat, journal, nutrition    │
│  │   ├── /api/models/*       → Ollama, blood, router            │
│  │   ├── /api/bodega/*       → Memory context                   │
│  │   ├── /api/observability  → Full observability               │
│  │   ├── /api/system/*       → Living report, debt              │
│  │   ├── /api/neurons/*      → Neuron audit                     │
│  │   └── /api/workers/*      → Worker management                │
│  │                                                              │
│  ├── React SPA (/)         → Cabina Viva dashboard             │
│  │                                                              │
│  ├── LifePulse             → Heartbeat 5s                       │
│  │   └── build_runtime_heartbeat()                              │
│  │   └── build_learning_journal()                               │
│  │                                                              │
│  ├── Resource Governor     → Mode decision                      │
│  │   └── full_local_guarded / cooldown                          │
│  │                                                              │
│  ├── MetabolicCoordinator  → Needs every 15s                    │
│  │   ├── health_check (30s priority 90)                         │
│  │   ├── heartbeat (5s priority 80)                             │
│  │   ├── lease_supervision (60s priority 70)                    │
│  │   └── budget_check (120s priority 60)                        │
│  │                                                              │
│  ├── Workers (embebidos)   → BackgroundService                  │
│  │   ├── WorkerLoop (9 task types)                              │
│  │   ├── Task Queue (SQLite-backed)                             │
│  │   ├── State Store                                           │
│  │   └── Sandbox                                                │
│  │                                                              │
│  ├── Scheduler            → TriadeOS event engine              │
│  │   └── max_wakeups_per_cycle: 5                               │
│  │                                                              │
│  └── Model Router         → Auto-selection by hardware         │
│      ├── roles: hypothalamus, central, creator, trainer         │
│      ├── coder, embedding, fast, deep                           │
│      └── fallback: rules/template when Ollama unavailable       │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    OLLAMA (127.0.0.1:11434)                      │
│  Version 0.32.5 · GPU NVIDIA L4                                 │
│                                                                 │
│  ├── qwen2.5:3b-instruct   (1.9 GB)  → central, hypothalamus   │
│  ├── qwen3:1.7b            (1.4 GB)  → fast response           │
│  ├── qwen2.5-coder:3b      (1.9 GB)  → code generation         │
│  ├── nomic-embed-text      (274 MB)  → embeddings (GPU)        │
│  ├── qwen3:4b              (2.5 GB)  → deep analysis           │
│  └── gemma3:4b             (3.3 GB)  → alternative             │
│                                                                 │
│  Ollama Blood → cognitive_blood_active                          │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│              SQLite DATABASE (triade/memory/triade.db)           │
│  WAL mode · 74 MiB · 104 tables                                 │
│                                                                 │
│  ├── identity_core        (6 rows)  → Core identity             │
│  ├── runs                 (182)     → Run history               │
│  ├── episodic_memory      (106)     → Episodes                  │
│  ├── semantic_memory      (86 doc)  → Knowledge (candidates)    │
│  ├── learning_queue       (13)      → Learning candidates       │
│  ├── neurons              (16+5)    → Neuron registry           │
│  ├── autonomous_tasks     (active)  → Autonomous task queue     │
│  ├── worker_tasks         (1802+)   → Worker task history       │
│  ├── qualia_*             (5 tabs)  → QualiaBus                 │
│  ├── metabolic_*          (5 tabs)  → Metabolic cycles          │
│  ├── backup_restore_drills          → Restore drills            │
│  └── ... (94 more tables)          → Extended schema            │
└─────────────────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    HARDWARE (GCP / Lightning AI)                  │
│                                                                 │
│  CPU:  Intel Xeon 2.20GHz · 8 vCPUs · 4 cores/8 threads        │
│  RAM:  31 GiB total · 27 GiB available                          │
│  GPU:  NVIDIA L4 · 23 GiB VRAM · CUDA 13.0                     │
│  DISK: 369 GiB overlay · 310 GiB free                           │
│  NET:  10.138.0.111/32 (GCP private)                            │
│                                                                 │
│  Services: ssh, docker, containerd, jupyterlab, vscode          │
└─────────────────────────────────────────────────────────────────┘
```

## Componentes Clave

| Componente | Mecanismo | Puerto | Estado |
|---|---|---|---|
| API/UI | `single_port_app.py` (FastAPI + React SPA) | 8010 | ✅ Activo |
| Ollama | `ollama serve` (systemd) | 11434 | ✅ Activo |
| Workers | `WorkerBackgroundService` embebido | - | ✅ (cooldown) |
| LifePulse | `build_runtime_heartbeat()` | - | ✅ Activo |
| Metabolismo | `MetabolicCoordinator` | - | ✅ Activo |
| DB | SQLite WAL | 8010 (API) | ✅ Íntegra |
| Proxy | Lightning AI HTTPS | 443 | ✅ Activo |
| Auto-start | `on_start.sh` + systemd | - | ✅ Configurado |
