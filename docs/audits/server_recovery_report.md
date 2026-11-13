# Server Recovery Report · Tríade Ω

**Fecha:** 2026-07-30T19:11:07Z  
**Host:** cs-01kyt66rer1jbb9g7t7vcnczfv  
**OS:** Ubuntu 24.04.4 LTS (Docker container)  
**Kernel:** Linux 6.8.0-1064-gcp x86_64  
**Uptime:** 12 minutes (post-reboot)  
**Virtualization:** Docker (systemd PID 1)  

## Hardware

| Component | Detalle |
|---|---|
| CPU | Intel Xeon @ 2.20GHz, 8 vCPUs (4 cores/8 threads) |
| RAM | 31 GiB total, 27 GiB available |
| Swap | 16 GiB (file, 0 used) |
| GPU | NVIDIA L4, 23 GiB VRAM, Driver 580.173.02, CUDA 13.0 |
| Disk | 369 GiB overlay, 36 GiB used, 310 GiB free |
| Red | ens5: 10.138.0.111/32 (privada GCP) |

## Repositorio

- **Ruta:** `/teamspace/studios/this_studio/triadees`
- **Remote:** `https://github.com/WatabooColosus/triadees.git`
- **Rama:** `main` (up to date with origin/main)
- **SHA:** `b0613ea5b164b2929d87b7545e491d2a1514f525`
- **Estado:** Clean (no cambios sin commit)

## Servicios Recuperados

| Servicio | Estado | Puerto | Autoarranque |
|---|---|---|---|
| Ollama | HEALTHY | 11434 | systemd + on_start.sh |
| API (single-port) | HEALTHY | 8010 | systemd + on_start.sh |
| Workers | HEALTHY (cooldown por load) | embebido | systemd |
| Watchdog | ENABLED | - | systemd |
| Backup timer | ENABLED | - | systemd+timer |

## Base de Datos

- **Ruta:** `triade/memory/triade.db`
- **Tamaño:** 74 MiB (WAL mode)
- **Integridad:** OK (PRAGMA integrity_check)
- **Tablas:** 104
- **identity_core:** 6 filas intactas
- **Runs históricos:** 182
- **Workers activos:** sí (degradado a cooldown por load)

## Ollama

- **Versión:** 0.32.5
- **Endpoint:** http://127.0.0.1:11434
- **Modelos (6):** qwen2.5:3b-instruct, qwen3:1.7b, qwen2.5-coder:3b, nomic-embed-text, qwen3:4b, gemma3:4b
- **Inferencia:** verificada (respuesta ~33s en GPU)
- **Embeddings:** verificados (nomic-embed-text en GPU)
- **Ollama Blood:** activo, modo `cognitive_blood_active`

## URL Pública

- **Mecanismo:** Lightning AI Studio proxy
- **URL:** `https://lightning.ai/agenciadigitalwataboo-org/deploy-model-project/studios/triade/web-ui?port=8010`
- **TLS:** Gestionado por Lightning AI (HTTPS automático)

## Acciones Realizadas

1. Inspección completa del servidor post-reboot
2. Verificación del repositorio, rama y SHA
3. Verificación de integridad de base de datos (104 tablas, identity_core intacto)
4. Inicio de Ollama con 6 modelos
5. Verificación de inferencia y embeddings
6. Inicio de API en puerto 8010
7. Verificación de Ollama Blood
8. Creación de archivo .env en `/etc/triade/triade.env`
9. Instalación de unidades systemd (ollama, api, backup, watchdog, workers)
10. Creación de script `triade_doctor_full.py`
11. Creación de script `post_reboot_verify.sh`
12. Actualización de `on_start.sh` para autoarranque

## Riesgos Pendientes

1. Load average elevado post-reboot causa degradación a modo `cooldown`
2. Sin backup verificado previo (backup script requiere fix en ruta)
3. Sin firewall local (entorno Lightning gestiona seguridad perimetral)
4. Sin túnel externo (cloudflared/ngrok) ni dominio propio
