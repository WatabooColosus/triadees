# ROADMAP.md · Tríade Ω (alineado al estado real)

Ruta priorizada derivada de la auditoría Fase 0 (ver `AUDIT_REPORT.md` y `ARCHITECTURE_MAP.md`).
Estado base: 2026-06-02 · commit `90c548f` · frontera técnica ≈ **v1.9F**.

> Este ROADMAP refleja **lo que el código hace hoy** y prioriza estabilizar antes de expandir.
> El roadmap conceptual histórico original se conserva intacto en `docs/ROADMAP.md`.
> Regla rectora del proyecto respetada: *no avanzar una fase sin dejar evidencia auditable.*

---

## Dónde estamos realmente

| Fase conceptual (docs/ROADMAP.md) | Estado declarado allí | Estado REAL |
|---|---|---|
| Fase 0 · Base fundacional | en progreso | ✅ completa |
| Fase 1 · Arquitectura documentada | activo | ✅ completa |
| Fase 2 · MVP consola | pendiente | ✅ completa (CLI run/chat/recall/doctor) |
| Fase 3 · Memoria viva + aprendizaje | pendiente | 🟡 memoria ✅ / aprendizaje 🔴 |
| Fase 4 · Doble modelo por neurona | pendiente | ✅ completa (Hipotálamo+Central, Ollama+router+fallback) |
| Fase 5 · Integración n8n + API | pendiente | ✅ completa (FastAPI + 4 workflows + systemd) |
| Fase 6 · Federación | pendiente | 🔴 solo visión |
| Fase 7 · Framework publicable | futuro | 🔴 futuro |

**Implicación:** el proyecto está mucho más avanzado de lo que su propia documentación admite. El trabajo pendiente no es construir el MVP — ya existe — sino **reparar la regresión semántica, decir la verdad del estado, y cerrar las dos promesas grandes (Learning y Federation).**

---

## Registro de progreso

- **Fase A · ✅ COMPLETA** (A.1, A.2, A.3). Suite verde, base verificable restaurada, docs sincronizados, `align` dinámico.
- **Fase B.1 · ✅ COMPLETA** — N Creadora/Formadora integradas al ciclo `run()` como propuesta auditable (candidate, sin activación).
- **Fase C · ✅ COMPLETA** — Learning Pipeline sobre `learning_queue` (candidate→evaluated→verified→consolidated), consolidación vía gobernanza semántica 1.9E, CLI `learn`. `align` mide **0.93 (strong)**; `learning_queue` deja de ser tabla muerta.
- **Fase D · ✅ COMPLETA** — Federación de nodos sobre `federated_nodes`/`federated_exchange_log`: registro con permisos/confianza, recepción gated (autenticación→permiso→Safety→log→Learning Pipeline como candidato), envío con bloqueo de fuga, revocación. CLI `federate`. Solo queda `goals` como tabla muerta.
- **Pendiente real (medido por `align`):** estado emocional longitudinal (Hipotálamo) y aprendizaje post-run en el ciclo (runner) → Fase B.2/B.3 y enganche C↔run.

---

## Fase A · Estabilización y Verdad de Estado  ✅ COMPLETA
**Prioridad P0/P1 · sin features nuevas · objetivo: restaurar la base verificable.**

### A.1 Reparar regresión 1.9F (P0)
- Corregir `SemanticMemoryStore.list_documents()` para volver a aceptar `limit` (o ajustar los dos llamadores). Cubre D-01.
- Parsear `metadata` (JSON) en `get_document()` o en el consumidor de `semantic_search`. Cubre D-02.
- **Evidencia de cierre:** test nuevo que reproduzca el `TypeError`/`ValueError` y pase tras el fix; `embed_pending()` y `governance.doctor()` ejecutan sin error.

### A.2 Restablecer verificación automatizada (P0)
- Documentar/garantizar entorno con `pytest`, `fastapi`, `uvicorn`, `httpx` (entorno actual no tiene `pip`).
- **Evidencia de cierre:** los 31 archivos de `tests/` ejecutan y reportan resultado conocido.

### A.3 Sincronizar la verdad de estado (P1)
- Actualizar `docs/MVP_REAL_STATUS.md`, sección "Contenido Actual" del README, y reconciliar `docs/ROADMAP.md` con este archivo.
- Volver `core/alignment.py` (`align`) **dinámico** (medir, no hardcodear) o marcarlo explícitamente como histórico. Cubre D-03.
- **Evidencia de cierre:** un nuevo lector puede entender el estado real sin leer el código; `align` no contradice la realidad.

**Criterio de cierre de Fase A:** base verificable restaurada, suite ejecutable, documentación que no miente.

---

## Fase B · Integración de Órganos Existentes
**Prioridad P2 · conectar lo ya construido pero desconectado.**

### B.1 N Creadora / N Formadora dentro del ciclo  ✅ COMPLETA
- `run()` propone y evalúa neuronas candidatas cuando la intención es `build_or_update` (gobierno cognitivo), no solo vía CLI `neuron`.
- Propuesta **auditable**: se registra siempre como `candidate`, nunca se activa ni degrada una neurona ya promovida; promoción = decisión humana.
- **Evidencia:** artefacto `neuron_candidate.json` por run + campo `neuron_proposal` en `memory_diff`/`integrity`/resultado. Tests en `tests/test_neuron_proposal.py`. Controlable con `propose_neurons=False`.

### B.2 Recall semántico como ciudadano de primera clase
- Evaluar activar recall vectorial por defecto (hoy es flag opt-in), con la gobernanza 1.9E ya implementada como filtro de seguridad.
- **Evidencia:** runs con memoria semántica autorizada citada literalmente; runs sin ella, sin alucinación de procedencia.

### B.3 Estado `sandbox_only` real en Safety (cierra D-09)
- Implementar una vía sandbox mínima para que el estado declarado tenga semántica.

---

## Fase C · Learning Pipeline (cerrar promesa)  ✅ COMPLETA
**Prioridad P2 · de visión a código, reutilizando lo que existe.**

- ✅ Pipeline implementado en `triade/learning/pipeline.py` (`LearningPipeline`) sobre `learning_queue`:
  `candidate → evaluated → verified → consolidated | rejected` (+ `archived`).
- ✅ Consolidación reutiliza la gobernanza semántica 1.9E (candidate→experimental→stable con razón/evidencia) como motor de memoria estable.
- ✅ Reglas duras: nada se consolida sin `verified` + aprobación humana (`approved_by`) + `source_ref`; riesgo `critical` no auto-avanza; un intento de alterar identidad se rechaza en evaluación; el pipeline **nunca** escribe en `identity_core` (test lo garantiza).
- ✅ Evidencia: `verification_notes` acumula historial por paso (ingested/evaluated/verified/consolidated) en la fila; CLI `learn` (ingest/evaluate/verify/consolidate/reject/list/doctor); tests en `tests/test_learning_pipeline.py`.
- **Pendiente menor (Fase futura):** enganche automático C↔`run()` (proponer candidato de aprendizaje desde el episodio post-run) y un sandbox real (B.3). Artefactos por paso en disco quedan opcionales (la traza vive en `verification_notes`).

---

## Fase D · Federación entre Nodos (cerrar promesa)  ✅ COMPLETA
**Prioridad P3 · las tablas ya existen, falta toda la lógica.**

- ✅ `Federation` (`triade/federation/federation.py`) sobre `federated_nodes` / `federated_exchange_log`.
- ✅ Flujo de recepción: autenticación → validación de permiso → Safety → log → Learning Pipeline (candidato). Nada se consolida automáticamente (reusa Fase C).
- ✅ Niveles de confianza (low/medium/high), permisos por tipo, permisos prohibidos rechazados al registrar, revocación/pausa, envío con bloqueo de fuga de datos sensibles.
- ✅ **Evidencia:** intercambios registrados en `federated_exchange_log` con safety_status y decisión; CLI `federate`; tests en `tests/test_federation.py`.
- **Pendiente (futuro):** transporte real entre nodos (red/HTTP + firma con public_key); hoy el registro y la gobernanza son locales y verificables.

---

## Fase E · Consolidación y Framework Publicable
**Prioridad P3 · calidad y difusión.**

- Consolidar las 5 superficies FastAPI en `single_port_app` (cierra D-07).
- Migrar contratos a Pydantic con validación en frontera (cierra D-08).
- Unificar estrategia de migración de esquema (cierra D-04); reemplazar parser YAML casero por PyYAML o equivalente (cierra D-05).
- Documentación pública, ejemplos, diagramas, licencia.

---

## Tablero de deuda técnica → fase

| ID | Descripción corta | Fase |
|---|---|---|
| D-01 | `list_documents(limit=)` roto (regresión 1.9F) | **A.1** |
| D-02 | `metadata` sin parsear en `get_document` | **A.1** |
| D-03 | `align` hardcodeado/desactualizado | **A.3** |
| D-09 | `sandbox_only` declarado sin emitir | B.3 |
| D-06 | `Crystal.q_crystal()` legacy duplicado | E |
| D-07 | 5 apps FastAPI duplicadas | E |
| D-08 | Contracts → Pydantic | E |
| D-04 | Estrategia de migración mixta | E |
| D-05 | Parser YAML casero | E |

---

## Reglas de avance (heredadas del proyecto)

1. No avanzar una fase sin dejar evidencia.
2. Todo cambio con commit claro.
3. Toda función nueva con contrato.
4. Toda memoria estable con criterio de consolidación.
5. Todo aprendizaje pasa por sandbox/verificación.
6. Toda acción sensible pasa por Safety.
7. Toda ejecución debe poder auditarse.

---

## Recomendación final

**Empezar por Fase A.1 (reparar la regresión 1.9F con un test que la cubra).** Es el cambio de mayor impacto y menor riesgo: restaura la frontera de desarrollo que hoy está parcialmente caída, sin añadir superficie nueva, y deja evidencia verificable — exactamente el espíritu del proyecto.
