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

## Fase A · Estabilización y Verdad de Estado  ← **PRÓXIMO PASO RECOMENDADO**
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

### B.1 N Creadora / N Formadora dentro del ciclo
- Permitir que `run()` pueda proponer/evaluar neuronas candidatas como parte del gobierno cognitivo (no solo vía CLR `neuron`).
- **Evidencia:** un run con intención de creación genera un `NeuronSpec` candidato trazable.

### B.2 Recall semántico como ciudadano de primera clase
- Evaluar activar recall vectorial por defecto (hoy es flag opt-in), con la gobernanza 1.9E ya implementada como filtro de seguridad.
- **Evidencia:** runs con memoria semántica autorizada citada literalmente; runs sin ella, sin alucinación de procedencia.

### B.3 Estado `sandbox_only` real en Safety (cierra D-09)
- Implementar una vía sandbox mínima para que el estado declarado tenga semántica.

---

## Fase C · Learning Pipeline (cerrar promesa)
**Prioridad P2 · de visión a código, reutilizando lo que existe.**

- Implementar el pipeline mínimo sobre la tabla `learning_queue` (hoy muerta):
  `candidate → evaluated → (sandbox) → verified → consolidated | rejected`.
- Reutilizar la maquinaria de gobernanza semántica 1.9E (transiciones auditables con razón/evidencia) como motor de consolidación.
- Conectar con Safety (bloqueo/cuarentena) y Verification (reporte previo a consolidar).
- **Regla innegociable:** ningún aprendizaje toca memoria estable ni identidad núcleo sin verificación y aprobación (ya respetado por diseño en 1.9E).
- **Evidencia de cierre:** un candidato externo recorre el pipeline y deja `learning_candidate.json` + `evaluation.json` + `verification_report.json` + `memory_diff.json`.

---

## Fase D · Federación entre Nodos (cerrar promesa)
**Prioridad P3 · las tablas ya existen, falta toda la lógica.**

- Implementar `FederatedNode` + `FederatedExchangePacket` sobre `federated_nodes` / `federated_exchange_log`.
- Flujo de recepción: autenticación → permisos → Safety → log → learning_queue → verificación → decisión de Central.
- Niveles de confianza (low/medium/high), permisos por tipo, revocación.
- **Depende de Fase C** (todo lo recibido entra al pipeline de aprendizaje como candidato).
- **Evidencia de cierre:** un intercambio simulado entre dos nodos locales queda registrado y pasa por Safety sin consolidación automática.

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
