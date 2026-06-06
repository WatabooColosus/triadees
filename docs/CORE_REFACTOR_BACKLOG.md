# Core Refactor Backlog

Fecha: 2026-06-05

## P0

### Normalizar causa de fallback de modelos

- Objetivo: diferenciar Ollama ausente, modelo no instalado, timeout, salida vacía y JSON inválido.
- Archivos afectados: `triade/core/hypothalamus.py`, `triade/core/central.py`, `triade/core/runner.py`, `triade/core/bodega.py`.
- Riesgo: medio; toca ciclo de respuesta y model_events.
- Test esperado: run con cliente falso para cada causa y aserción de `model_events.error`.
- Criterio de aceptación: cada fallback queda persistido con causa estable y visible en doctor/analyzer.

### Dividir etapas del runner

- Objetivo: extraer funciones/clases para señales, memoria, cristal, plan, safety, modelos y verificación.
- Archivos afectados: `triade/core/runner.py`, posibles nuevos módulos `triade/core/run_pipeline.py`.
- Riesgo: medio-alto; runner es superficie CLI/API/UI.
- Test esperado: tests actuales de runner/API/UI pasan sin cambios y nuevos tests validan cada etapa.
- Criterio de aceptación: `TriadeRunner.run` queda como orquestador breve y mantiene artefactos actuales.

### Completar latencia de model_events

- Objetivo: medir `latency_ms` real para Hipotálamo y Central.
- Archivos afectados: `triade/models/ollama_client.py`, `triade/core/hypothalamus.py`, `triade/core/central.py`, `triade/core/runner.py`.
- Riesgo: bajo-medio.
- Test esperado: cliente falso con latencia conocida y evento persistido.
- Criterio de aceptación: doctor y analyzer pueden comparar calidad/latencia por rol/modelo.

### Mantener `analyze-conversations` como lectura segura

- Objetivo: garantizar que el análisis nunca escriba DB ni consolide learning.
- Archivos afectados: `triade/core/conversation_analyzer.py`, `triade_digimon.py`.
- Riesgo: bajo.
- Test esperado: conteo de `identity_core` y `learning_queue` no cambia tras análisis/export.
- Criterio de aceptación: salida JSON incluye política read-only y tests cubren inmutabilidad.

## P1

### Separar repositorios SQLite por dominio

- Objetivo: reducir tamaño de `Bodega` y aclarar límites.
- Archivos afectados: `triade/core/bodega.py`, nuevos `triade/memory/*_repository.py`.
- Riesgo: medio.
- Test esperado: tests de memoria, cristal, semantic recall y runner pasan.
- Criterio de aceptación: `Bodega` delega persistencia sin cambiar schema ni DB local.

### Router FastAPI por dominios en single-port

- Objetivo: dividir UI/runs, modelos, memoria semántica, Android/local jobs y federación.
- Archivos afectados: `apps/single_port_app.py`, nuevos routers bajo `apps/routers/`.
- Riesgo: medio-alto.
- Test esperado: `tests/test_single_port_*` y API smoke tests pasan.
- Criterio de aceptación: endpoints actuales conservan rutas y respuestas compatibles.

### Contratos de prompts y salidas de modelo

- Objetivo: mover prompts de Central/Hipótalamo a contratos versionados.
- Archivos afectados: `triade/core/central.py`, `triade/core/hypothalamus.py`, nuevo `triade/core/model_contracts.py`.
- Riesgo: medio.
- Test esperado: prompts contienen claves requeridas y parsing de señales sigue estable.
- Criterio de aceptación: cada prompt tiene versión y pruebas de estructura.

### Score de respuesta por intención

- Objetivo: hacer `_score_central` sensible a intención, verificación y memoria usada.
- Archivos afectados: `triade/core/runner.py`, `triade/core/verification.py`.
- Riesgo: bajo-medio.
- Test esperado: ejemplos por intención con scores esperados.
- Criterio de aceptación: quality_score deja de depender casi solo de longitud/model_ok.

## P2

### Reportes longitudinales por sesión/proyecto

- Objetivo: ampliar `conversation_analyzer` para comparar `context_key`, fuente y sesión sin exponer textos.
- Archivos afectados: `triade/core/conversation_analyzer.py`.
- Riesgo: bajo.
- Test esperado: fixture con múltiples fuentes/contextos.
- Criterio de aceptación: JSON exporta evolución por contexto y mantiene privacidad.

### Learning candidates desde analyzer

- Objetivo: crear candidatos revisables desde patrones, sin evaluar ni consolidar automáticamente.
- Archivos afectados: `triade/core/conversation_analyzer.py`, `triade/learning/pipeline.py`, CLI.
- Riesgo: medio por sensibilidad de datos.
- Test esperado: candidato requiere flag explícito y no toca `semantic_memory`.
- Criterio de aceptación: solo crea `learning_queue` bajo confirmación humana explícita.

### Normalizar fuentes UI

- Objetivo: unificar `single-port-ui` y `single-port-react-ui`.
- Archivos afectados: `apps/single_port_app.py`, UI cliente, analyzer.
- Riesgo: bajo.
- Test esperado: requests UI nuevos guardan fuente esperada y analyzer mantiene alias histórico.
- Criterio de aceptación: fuentes nuevas son consistentes sin perder lectura histórica.

### Documentar contrato FASE_F del núcleo

- Objetivo: convertir esta auditoría en especificación de arquitectura futura.
- Archivos afectados: `docs/CORE_ARCHITECTURE_AUDIT.md`, nuevo `docs/CORE_PHASE_F_CONTRACT.md`.
- Riesgo: bajo.
- Test esperado: no aplica código; revisión documental.
- Criterio de aceptación: cada órgano tiene responsabilidades, entradas, salidas y métricas.
