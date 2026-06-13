# Auditoría de Superficies UI/API — Tríade Ω v2.2

> Generada: 2026-06-12
> Propósito: Inventariar toda superficie visual y de API para cerrar deuda de UI legacy.

---

## 1. Entrypoint oficial

| Componente | Archivo | Puerto | Estado |
|---|---|---|---|
| FastAPI single-port | `apps/single_port_app.py` | 8010 | **OFICIAL** |
| API router | `apps/routes/api.py` | vía single_port | **OFICIAL** |
| UI router | `apps/routes/ui.py` | vía single_port | **OFICIAL** |
| React build | `frontend/dist/index.html` | vía single_port | **OFICIAL** |

`single_port_app.py` incluye `api_router` y `ui_router`. Sin otros entrypoints.

---

## 2. UI oficial — React SPA

| Ruta | Archivo | Método | Responde |
|---|---|---|---|
| `/` | `routes/ui.py:54` | GET | SPA si `dist/index.html` existe, fallback `CLEAN_UI_HTML` |
| `/ui` | `routes/ui.py:55` | GET | Alias de `/` |
| `/observabilidad` | `routes/ui.py:56` | GET | Alias de `/` |
| `/ui/observabilidad` | `routes/ui.py:57` | GET | Alias de `/` |
| `/assets/{path}` | `routes/ui.py:30` | GET | `FileResponse` desde `frontend/dist/assets/` |

Tabs SPA: Chat, Sistema, Observabilidad, Router, Modelos, Federación, Memoria, Neuronas.

---

## 3. UI legacy con HTML embebido

### 3.1 En `apps/ui_html.py`

| Constante | Líneas | Contenido | Usada por |
|---|---|---|---|
| `CLEAN_UI_HTML` | 6–277 | Consola limpia con chat, paneles de datos en vivo | `/api/ui/clean`, fallback de `/` |
| `HTML` | 278–413 | Chat legacy con sidebar | No ruteada directamente |
| `TRIADE_UI_HTML` | 414–437 | Variante con pulse display | No ruteada directamente |
| `TRIADE_REACT_UI_HTML` | 438–484+ | React inlined vía CDN (legacy) | `/api/ui/legacy` |

### 3.2 Apps legacy independientes (cada una con HTML propio)

| App | Puerto | Rutas HTML | Estado |
|---|---|---|---|
| `chat_ui_app.py` | 8000 (proxy) | `/`, `/ui` → `HTML` (línea 90) | **DEPRECATED** |
| `chat_ui_router_app.py` | — (proxy) | `/`, `/ui` → `HTML` (línea 10) | **DEPRECATED** |
| `api_app.py` | 8000 (proxy) | Ninguna HTML, solo JSON | **DEPRECATED** (duplica single_port routes) |
| `public_relay_app.py` | Railway cloud | `/`, `/downloads/android-node` | **Activo** (nube, no local) |
| `federation_pairing_app.py` | — | `/`, `/admin` | **Activo** (portal de emparejamiento) |
| `mobile_node_agent.py` | 8790 | `/admin` | **Activo** (agente Android) |

---

## 4. Duplicaciones de rutas

### 4.1 API duplicadas en `apps/routes/api.py`

| Ruta original | Alias | Líneas |
|---|---|---|
| `/api/health` | `/health` | 303–304 |
| `/api/observability` | `/api/system/observability` | 388–389 |
| `/api/workers/events` | `/workers/events` | 178, 205, 208 |
| `/api/neurons/missions/relevant` | `/api/system/neurons/missions/relevant` | 545, 556 |
| `/api/neurons/stable-audit` | `/api/system/neurons/stable-audit` | 684, 690 |
| `/api/bodega/global-context` | `/api/system/bodega/global-context` | 966, 977 |
| `/api/models/ollama/blood` | `/api/system/ollama-blood`, `/api/runtime/blood` | 355, 356, 357 |

### 4.2 `api_app.py` (líneas 153–157)

Importa y monta **ambos** routers (`api_router` + `ui_router`), duplicando TODO el surface de `single_port_app.py`.

---

## 5. Dashboards duplicados

| Dashboard | Endpoint API | SPA tab | Legacy HTML |
|---|---|---|---|
| Neuron dashboard | `/api/system/neurons` | Neuronas | `/api/ui/legacy`, `CLEAN_UI_HTML` |
| Identity view | `/api/system/neurons` (embebido) | Neuronas (detalle) | `CLEAN_UI_HTML` |
| Observabilidad | `/api/observability` | Observabilidad | `CLEAN_UI_HTML`, `/observabilidad` fallback |
| Memoria | `/api/semantic/doctor`, `/api/bodega/global-context` | Memoria | `CLEAN_UI_HTML` |
| Workers | `/workers/status` | — | `CLEAN_UI_HTML` |

---

## 6. Acciones recomendadas

| Superficie | Acción | Riesgo |
|---|---|---|
| `apps/single_port_app.py` | **keep** — oficial | bajo |
| `apps/routes/api.py` | **keep** — oficial, JSON puro | bajo |
| `apps/routes/ui.py` | **keep** — oficial (SPA serving) | bajo |
| `apps/ui_html.py` `CLEAN_UI_HTML` | **deprecated_wrapper** — solo como fallback si falta build SPA | bajo |
| `apps/ui_html.py` otras constantes no ruteadas | **remove_after_tests** | bajo (no se usan) |
| `/api/ui/clean` | **deprecated_wrapper** + redirect notice | bajo |
| `/api/ui/legacy` | **deprecated_wrapper** + redirect notice | bajo |
| `apps/api_app.py` | **deprecated_wrapper** — solo compatibilidad API key | medio |
| `apps/chat_ui_app.py` | **deprecated_wrapper** — redirect a single_port | medio |
| `apps/chat_ui_router_app.py` | **deprecated_wrapper** — redirect a single_port | medio |
| `apps/public_relay_app.py` | **keep** — nube, fuera de alcance local | bajo |
| `apps/federation_pairing_app.py` | **keep** — portal independiente | bajo |
| `apps/mobile_node_agent.py` | **keep** — agente Android remoto | bajo |
| Duplicaciones internas (alias) | **keep** — compatibilidad; no eliminar sin tests | bajo |
| `api_app.py` duplicación de routers | **convert_to_api_only** — quitar import de ui_router | medio |
| React SPA `App.tsx` | **keep** + **mejorar** con tarjetas faltantes | bajo |

---

## 7. Resumen

- 6 apps FastAPI
- 11 HTML embebidos (3 no ruteados)
- ~15 endpoints con alias
- 1 SPA React moderna
- `single_port_app.py` + `routes/ui.py` + `routes/api.py` son el stack oficial
- `api_app.py` duplica todo el surface (riesgo medio)
- `chat_ui_app.py` y `chat_ui_router_app.py` son legacy proxy (riesgo medio)
- `public_relay_app.py`, `federation_pairing_app.py`, `mobile_node_agent.py` están fuera del alcance local
