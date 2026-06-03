# AUDIT_REPORT.md · Tríade Ω

**Fase 0 — Auditoría y Comprensión**
Fecha de auditoría: 2026-06-02 · Rama: `main` · Commit base: `90c548f`
Alcance: repositorio local `triadees` (sin clones ni repos externos).
Método: lectura completa del núcleo (~7.245 líneas Python), esquema SQL, 52 documentos, DB versionada y workflows; smoke test del ciclo cognitivo en rutas temporales (**sin modificar el estado del repo**).

> **Regla de fase respetada:** esta auditoría no modificó código, no eliminó archivos, no creó funcionalidades nuevas y no realizó refactors. Solo produjo documentación (este informe y sus dos entregables hermanos).

---

## 1. Estado general

**MVP local real, operativo y auditable. Frontera técnica ≈ v1.9F.**

Tríade Ω dejó de ser solo documentación: el ciclo cognitivo completo se ejecuta de extremo a extremo y deja evidencia persistente por cada run.

**Verificación ejecutada (modo fallback, sin Ollama, en directorio temporal):**

```
run_id: run-20260603-013212-...
response: "Tríade Ω procesó el run ... Intención detectada: conversation. Riesgo: low. ..."
safety: approved
report.status: ok
scores: coherence=0.75 memory=0.90 safety=0.90 usefulness=0.70 traceability=0.95
artifacts: input.json signals.json memory.json crystal.json plan.json
           safety.json output.json memory_diff.json report.json integrity.json CLOSED
```

El comando `align` reporta núcleo `operational` (score 0.74): central 0.65 · hypothalamus 0.75 · bodega 0.82 · crystal 0.60 · runner 0.88. (Estos puntajes son **estáticos/hardcodeados**; ver Deuda Técnica D-03.)

### Composición del repositorio

| Capa | Contenido | Volumen |
|---|---|---|
| `triade/core/` | central, hypothalamus, bodega, crystal, safety, verification, contracts, config, runner, neuron_creator, neuron_trainer, neuron_registry, alignment | 12 módulos |
| `triade/memory/` | semantic_store, semantic_embedding_engine, semantic_search, semantic_governance, schemas.sql, migrations/ | capa semántica 1.9A–F |
| `triade/models/` | model_router, hardware_profile, compatibility_matrix, model_install_queue, ollama_client | capa de modelos |
| `apps/` | api_app, chat_ui_app, chat_ui_router_app, model_router_api, single_port_app | 5 superficies FastAPI |
| `tests/` | 31 archivos de test (pytest) | cobertura por subsistema |
| `docs/` | 52 documentos (ARCHITECTURE, SAFETY, LEARNING, FEDERATION, ROADMAP, STATUS_0_3 … STATUS_1_9E, etc.) | historial denso |
| `n8n/` | 4 workflows (webhook, chat producción, neuron create/list) | integración orquestación |
| `systemd/` | 3 units (api, chat-ui, model-router) | despliegue local |
| Raíz | `triade_digimon.py` (CLI), `triade.yml`, `requirements.txt`, `pyproject.toml`, README, docs base | entrypoints |

**Total Python:** ~7.245 líneas. El módulo más grande es `bodega.py` (455).

---

## 2. Mapeo de los 7 componentes solicitados

### 2.1 Neurona Central — 🟡 Operativo parcial
- **Código:** `core/central.py` (planeación + respuesta regulada por Cristal/memoria/gobernanza); órganos N Creadora = `neuron_creator.py`, N Formadora = `neuron_trainer.py`, persistencia = `neuron_registry.py`.
- **Cumple:** crea `PlanPacket`, genera `OutputPacket`, usa Ollama con fallback por plantilla, respeta gobernanza semántica (1.9E) y continuidad temporal del Cristal, exige atribución literal de fuentes.
- **Brecha:** **N Creadora/Formadora NO participan en el ciclo `run()`** — solo se invocan por la CLI `neuron create/list/show`. No hay gobierno activo de aprendizaje dentro del run.

### 2.2 Hipotálamo Emocional — 🟢 Operativo
- **Código:** `core/hypothalamus.py`.
- **Cumple:** detecta intención (conversation/build_or_update/analyze/memory), tono, urgencia, riesgo y vector **PV-7**; usa modelo local con validación JSON y fallback por reglas robusto.
- **Brecha:** sin estado emocional longitudinal ni personalidad dinámica por neurona.

### 2.3 Bodega de Almacenamiento — 🟢 Fuerte (órgano más sólido)
- **Código:** `core/bodega.py` + `memory/*`.
- **Cumple:** SQLite con WAL, inicialización de esquema, migración Crystal v2 por código, persistencia de runs/episodios/señales/cristal/safety/reportes/eventos de modelo, recuperación de identidad y memoria episódica/semántica, `doctor` con conteos. Capa semántica vectorial (documentos + embeddings + búsqueda coseno + gobernanza de estados).
- **Brecha:** ver regresión 1.9F (D-01); recall semántico vectorial es **opt-in** (flag `semantic_recall_enabled`), no automático.

### 2.4 Verification — 🟢 Operativo
- **Código:** `core/verification.py` (`Verifier`).
- **Cumple:** reporte con 5 scores (coherencia, memoria, safety, utilidad, trazabilidad), retroalimenta degradación temporal del Cristal, gobernanza semántica y estado de modelos; persiste en `verification_reports`.

### 2.5 Safety — 🟢 Operativo
- **Código:** `core/safety.py`.
- **Cumple:** evalúa entrada/plan/cristal/memoria; eleva nivel de riesgo; pone en cuarentena memoria semántica no autorizada; exige aprobación humana ante riesgo alto o degradación temporal con herramientas.
- **Brecha:** de los 5 estados declarados, **`sandbox_only` nunca se emite** (no hay sandbox real).

### 2.6 Learning Pipeline — 🔴 Solo visión
- **Existe:** `docs/LEARNING.md` (pipeline completo descrito) + tabla `learning_queue`.
- **Código:** **0 referencias** a `learning_queue` en Python. No hay descubrimiento, extracción, normalización, sandbox ni cola.
- **Parcial relacionado:** la gobernanza semántica 1.9E (`semantic_governance.py`) implementa un *subconjunto* del pipeline: estados `candidate → experimental → stable → rejected`, transiciones auditables con razón/evidencia, y bloqueo de influencia de memoria no autorizada. Es el embrión más cercano a "consolidación verificada".

### 2.7 Federation — 🔴 Solo visión
- **Existe:** `docs/FEDERATION.md` + tablas `federated_nodes`, `federated_exchange_log` (0 filas).
- **Código:** **0 referencias** en Python. 100% aspiracional.

---

## 3. Deuda técnica detectada

| ID | Severidad | Descripción | Ubicación |
|---|---|---|---|
| **D-01** | 🔴 Alta | `SemanticMemoryStore.list_documents()` perdió el parámetro `limit` en el "1.9F compatibility layer", pero dos llamadores lo pasan → `TypeError` en runtime. `embed_pending()` y `governance.doctor()` están rotos hoy. | `memory/semantic_store.py:190` vs `semantic_embedding_engine.py:165`, `semantic_governance.py:134` |
| **D-02** | 🟠 Media | `get_document()` devuelve `metadata` como string JSON sin parsear; el consumidor hace `dict(metadata)` → `ValueError` si metadata no está vacío. | `semantic_store.py:182`, `semantic_search.py:117` |
| **D-03** | 🟠 Media | `CoreAlignment` usa puntajes y textos **hardcodeados** y desactualizados (afirma "Q_cristal pendiente", "Crystal v2 pendiente", "embeddings reales pendientes" — todos ya implementados). El comando `align` desinforma. | `core/alignment.py:72-180` |
| **D-04** | 🟡 Baja | Estrategia de migración mixta: ALTER TABLE en código (`_migrate_crystal_v2`) para Crystal, vs. `migrations/*.sql` solo para semántica. Sin sistema de versiones de esquema unificado. | `bodega.py:73`, `memory/migrations/` |
| **D-05** | 🟡 Baja | Parser YAML casero (para evitar PyYAML en MVP); frágil ante listas, multilínea o tipos complejos. | `core/config.py:42` |
| **D-06** | 🟡 Baja | `Crystal.q_crystal()` (classmethod legacy) duplica la lógica de `q_crystal_payload()`. Redundancia mantenible. | `core/crystal.py:143` |
| **D-07** | 🟡 Baja | 5 superficies FastAPI con HTML embebido en strings; `single_port_app` es la unificada pero las otras 4 siguen activas → duplicación de UI/endpoints. | `apps/*` |
| **D-08** | 🟡 Baja | Contracts usan dataclasses con nota "migrar a Pydantic"; sin validación en frontera de API más allá de manual. | `core/contracts.py` |
| **D-09** | 🟡 Baja | Safety declara estado `sandbox_only` pero nunca lo emite (sin sandbox). | `core/safety.py` |

### Deriva documental (clasificada aparte por su impacto en confianza)
- `docs/ROADMAP.md`: Fases 2–5 marcadas "pendiente" cuando están implementadas.
- `docs/MVP_REAL_STATUS.md`: afirma ausencia de Ollama, FastAPI y persistencia de señales/cristal — falso hoy.
- `README.md` "Contenido Actual del Repositorio": describe el estado de ~68KB (Manifiesto/Inicio/IngeniaInversa), no la estructura modular actual.
- 52 docs `STATUS_*`: historial valioso pero sin un único índice de estado vigente.

---

## 4. Dependencias

**Runtime núcleo:** solo biblioteca estándar de Python (`sqlite3`, `dataclasses`, `json`, `hashlib`, `math`). **El ciclo cognitivo corre sin dependencias externas** (verificado).

**Dependencias externas (`requirements.txt`):**
- `fastapi>=0.115.0`, `uvicorn[standard]>=0.30.0` — apps web/API.
- `httpx>=0.27.0` — cliente Ollama (`ollama_client.py`) y tests de API.
- `pytest>=8.0.0` — suite de pruebas.

**Servicios externos:** Ollama en `http://127.0.0.1:11434` (opcional; hay fallback por plantilla/reglas en cada rol de modelo). n8n para orquestación (opcional).

**Estado del entorno auditado:** Python 3.14.4 **sin `pip` ni `pytest`** disponibles → **no fue posible ejecutar los 31 archivos de test** en este entorno. El smoke test del ciclo sí se ejecutó (solo stdlib). Esto implica que la verificación automatizada depende de un entorno con dependencias instaladas (riesgo R-04).

---

## 5. Coherencia arquitectónica

**Núcleo: muy coherente.** El ciclo `input → señales → memoria → gobernanza → cristal → plan → safety → salida → verificación → integridad` está implementado con contratos tipados (`contracts.py`), evidencia por run (11 artefactos + `CLOSED`), y fallback en cada punto de modelo. El `runner.py` orquesta todo de forma lineal, auditable y determinista. Runner (0.88) y Bodega (0.82) son los órganos más maduros.

**Incoherencias estructurales:**
1. **Tablas muertas:** `federated_nodes`, `federated_exchange_log`, `learning_queue`, `goals` existen en el esquema con 0 filas y 0 código — dan falsa sensación de completitud.
2. **Órganos desconectados:** N Creadora/Formadora viven fuera del ciclo principal.
3. **Capa semántica con regresión:** la frontera de desarrollo (1.9) está parcialmente caída por el refactor 1.9F (D-01/D-02) y no integra recall automáticamente.
4. **Autoauditoría estática:** `align` no refleja el código real (D-03).

---

## 6. Conclusión

Tríade Ω es un **MVP local genuinamente funcional y auditable** con un núcleo triádico sólido (Central + Hipotálamo + Bodega + Cristal + Safety + Verification operando end-to-end). Las dos grandes promesas pendientes —**Learning Pipeline** y **Federation**— son hoy solo visión documentada con esquema preparado. La prioridad inmediata no es expandir sino **estabilizar** (reparar la regresión 1.9F) y **sincronizar la verdad de estado** (docs + `align`), porque la base verificable es el activo principal del proyecto y actualmente la documentación y la capa semántica lo contradicen.

Ver `ARCHITECTURE_MAP.md` para el mapa de módulos y flujo, y `ROADMAP.md` para la ruta priorizada.
