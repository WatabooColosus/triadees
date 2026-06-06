# Core Architecture Audit

Fecha: 2026-06-05

Alcance revisado: `triade/core/`, `triade/memory/`, `triade/learning/`, `triade_digimon.py`, `apps/single_port_app.py`, `apps/model_router_api.py` y tests relacionados. No existe `triade/signals/` como paquete separado; las señales viven en `triade/core/hypothalamus.py` y `triade/core/contracts.py`.

## Central

La Central actual (`triade/core/central.py`) hace dos cosas reales: crea un `PlanPacket` determinista y genera la respuesta final. El plan usa intención, memoria gobernada, estado temporal del Cristal y reglas simples para decidir prudencia/profundidad. La respuesta usa Ollama cuando hay cliente disponible y fallback por plantilla cuando no hay cliente, no hay texto o el modelo falla.

El modelo de Central se define en `TriadeRunner`: manual por CLI/API, por configuración `triade.yml`, o por `ModelRouter` si Ollama está disponible y `auto_select_models=True`. La calidad se estima en `TriadeRunner._score_central`, no dentro de la Central.

## Hipotalamo

El Hipotálamo actual (`triade/core/hypothalamus.py`) produce `SignalPacket`: intención, tono, urgencia, riesgo, PV-7 y notas. Puede llamar a Ollama para JSON estructurado, pero conserva fallback por reglas si no hay cliente, falla el modelo o la salida no parsea como JSON.

El registro de uso real queda en `last_model_result` y luego `TriadeRunner` lo persiste en `model_events`. La lógica de intención/riesgo por reglas está hardcodeada por palabras clave.

## Bodega

La Bodega (`triade/core/bodega.py`) inicializa SQLite, migra columnas de `crystal_states`, crea runs, guarda señales, cristal, safety, episodios, reportes de verificación y eventos de modelo. También recupera identidad, memoria episódica por keywords, memoria semántica legacy por keywords y memoria semántica vectorial si recibe `SemanticSearchEngine`.

La DB local preserva `identity_core`, `runs`, `episodic_memory`, `signal_states`, `crystal_states`, `verification_reports`, `model_events`, `semantic_memory`, `semantic_documents` y `semantic_embeddings`. El nuevo `conversation_analyzer.py` lee esas tablas en modo read-only y no modifica memoria.

## Cristal

El Cristal (`triade/core/crystal.py`) calcula ética, profundidad, creatividad, relación, PV-7, intensidad, estabilidad, `q_crystal` y estado temporal. Compara contra historia reciente filtrada por `context_key` construida en el runner. Genera alertas de baseline, estabilidad, mejora, degradación o estado crítico.

El Cristal ya es verificable y testeable, pero la fórmula y umbrales están concentrados en una sola clase.

## Hardcodeado

- Modelos por defecto y RAM estimada en `triade/models/model_router.py`.
- Palabras clave de intención/riesgo en `Hypothalamus._analyze_rules`.
- Pasos del plan en `Central.plan`.
- Prompts de Hipotálamo y Central en sus clases.
- Fórmula/umbrales del Cristal en `crystal.py`.
- Tags episódicos `triade,mvp,run` y summary truncado en `Bodega.store_episode`.
- Fuente UI variable: `single-port-ui` en request model y `single-port-react-ui` en datos reales históricos.

## Duplicado

- Doctor de modelos existe en CLI (`models doctor`), runner doctor y `apps/model_router_api.py`.
- Selección de modelos aparece en CLI/API/runner con formatos cercanos pero no idénticos.
- Trazabilidad de modelo se repite en `memory_diff`, `integrity.json` y respuesta del runner.
- Lectura semántica mezcla legacy keyword y vector search dentro de `Bodega.recall`.

## Mezclado

- `TriadeRunner.run` orquesta el ciclo completo, persiste DB, escribe artefactos, puntúa modelos, propone neuronas y crea candidatos de learning opcionales.
- `Bodega` mezcla schema/migración, repositorio SQLite, búsqueda keyword, persistencia de safety y doctor.
- `apps/single_port_app.py` mezcla UI/API, router de modelos, memoria semántica, runtime Android/local jobs y federación.
- `triade_digimon.py` mezcla todos los comandos CLI en un solo archivo grande.

## Que Deberia Separarse

- Etapas del run: input, señales, memoria, cristal, plan, modelos, safety, verificación y persistencia.
- Repositorios SQLite por dominio: runs, episodios, cristal, modelos, learning y semántica.
- Prompts/model contracts de Central e Hipotálamo.
- Métricas de calidad de respuesta y comparación de modelos.
- API single-port en routers FastAPI por dominio.

## Modulos Grandes

- `apps/single_port_app.py`: 1580 líneas, demasiadas responsabilidades.
- `triade_digimon.py`: 641 líneas, muchos comandos.
- `triade/core/bodega.py`: 455 líneas, persistencia y búsqueda mezcladas.
- `triade/core/conversation_analyzer.py`: 442 líneas; es nuevo y debe dividirse si crece.
- `triade/core/crystal.py`: 263 líneas, fórmula y temporalidad juntas.
- `triade/learning/pipeline.py`: 360 líneas, pipeline completo en una clase.
- `triade/core/runner.py`: 362 líneas, orquestación y efectos secundarios.

## Trazabilidad Del Run

Hoy cada run tiene input, señales, memoria recuperada, cristal, plan, safety, output, `memory_diff`, reporte e integridad en archivos bajo `runs/<run_id>/`. En DB existen `runs`, `signal_states`, `crystal_states`, `verification_reports`, `model_events` y `episodic_memory`. En el reporte de 50 runs, esas piezas tienen 100% de cobertura.

Faltantes de FASE_F: una representación tipada única del ciclo, diff de memoria más expresivo, latencia real de modelos, causalidad de fallback normalizada y comparación longitudinal de calidad por modelo.

## Que Falta Para Nucleo FASE_F

- Separar el runner en pipeline de etapas testeables.
- Contrato explícito de doble modelo Central/Hipótalamo con razones de selección/fallback persistidas.
- Métricas de calidad comparables por modelo, intención y fuente.
- Analizador conversacional promovido a servicio interno read-only con exports reproducibles.
- Módulos de repositorio SQLite por tabla/dominio.
- Observabilidad de latencia, errores y calidad por run.
- Learning desde conversación solo como candidatos revisables con aprobación humana.
- Tests de CLI/API/UI que cubran trazabilidad completa y fallback controlado.
