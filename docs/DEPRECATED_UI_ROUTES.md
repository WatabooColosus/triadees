# Deprecated UI Routes — Tríade Ω

> Rutas HTML legacy que fueron migradas a la SPA React.
> Mantener por compatibilidad hasta v2.4.

---

## Rutas deprecadas

| Ruta | Archivo | Reemplazo React | Fecha objetivo | Test de compatibilidad |
|---|---|---|---|---|
| `/api/ui/clean` | `apps/routes/ui.py` | `/observabilidad` (SPA) | v2.4 | `test_legacy_ui_routes_redirect_or_wrapper` |
| `/api/ui/legacy` | `apps/routes/ui.py` | `/` (SPA) | v2.4 | `test_legacy_ui_routes_redirect_or_wrapper` |
| `/ui` | `apps/routes/ui.py` | `/` (SPA) | v2.4 | `test_single_port_serves_spa_index` |
| `/ui/observabilidad` | `apps/routes/ui.py` | `/observabilidad` (SPA) | v2.4 | `test_single_port_serves_spa_index` |
| `/observabilidad` | `apps/routes/ui.py` | `/` (SPA maneja routing) | v2.4 | `test_single_port_serves_spa_index` |

## Apps deprecadas

| App | Puerto | Reemplazo | Fecha objetivo |
|---|---|---|---|
| `api_app.py` | 8000 | `single_port_app.py` (8010) | v2.4 |
| `chat_ui_app.py` | 8000 (proxy) | `single_port_app.py` (8010) | v2.4 |
| `chat_ui_router_app.py` | — | `single_port_app.py` (8010) | v2.4 |

## Excepciones (NO deprecadas)

| App | Puerto | Razón |
|---|---|---|
| `public_relay_app.py` | Railway cloud | Nodo web público para federación remota |
| `federation_pairing_app.py` | — | Portal de emparejamiento de dispositivos |
| `mobile_node_agent.py` | 8790 | Agente Android en Termux |

## Marcas en código

Buscar `# DEPRECATED_UI:` para encontrar todas las rutas legacy marcadas en el código fuente.

---

## Historial

- **v2.2** (2026-06-12): Declaración oficial de React SPA como UI única. Rutas legacy con wrapper/redirect.
- **v2.4** (objetivo): Eliminar rutas y apps legacy.
