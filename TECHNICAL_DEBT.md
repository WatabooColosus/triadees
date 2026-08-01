# Deuda técnica vigente · Tríade Ω

Corte: 2026-08-01. SHA documental base: `8f44814`. Esta lista es canónica;
los reportes anteriores son históricos cuando la contradicen.

## P0 — CORREGIDO: el cuelgue de `test_concurrent_status_calls`

Causa determinada y cerrada con evidencia. Detalle completo en
[`docs/METABOLISM_STATUS_HANG_ROOT_CAUSE.md`](docs/METABOLISM_STATUS_HANG_ROOT_CAUSE.md).
En corto: `_acquire_process_lock` cerraba el descriptor y **después** lo
guardaba en `self._lock_fd`; el número volvía a la piscina de libres, se lo
llevaba el siguiente `open()` del proceso, y `_release_process_lock` cerraba el
fichero de otro. Cuando ese otro era una base SQLite con transacción viva, la
conexión moría con `disk I/O error` dejando su bloqueo POSIX **huérfano**, y los
lectores esperaban a nadie. Sólo se veía en la suite completa porque depende de
qué descriptor se recicle.

De paso, tres cosas más del mismo camino: el lock se derivaba sólo del **nombre**
del fichero de base (dos `test.db` distintas colisionaban), `_release` borraba
locks ajenos con `unlink` incondicional, y `status()` hacía `load_config()`
dentro del lock — lo que **ponía `cycle_count` a cero** cada vez que alguien
consultaba el estado, por un `GET` que no pide clave.

Verificado: suite completa **con** el test y sin `--deselect`, 1749 pruebas, 0
fallos, 100 %; 100 repeticiones del nodo; `mypy triade` limpio. El test entra en
`RUNTIME_TESTS` de la matriz de concurrencia, cuyo trabajo `serial` **sí**
bloquea el PR.

## P0 — ABIERTO: un run que cierra con tareas vivas retiene el lock para siempre

`worker_loop.py:544` pone `_retain_lock_for_active_tasks = True` cuando el run
termina con tareas huérfanas, y el `finally` conserva el fichero de lock a
propósito. El comentario dice que no queda huérfano porque
`recover_interrupted_runtime` lo recupera cuando el proceso muera — y ahí está
el fallo: `state_store.py:390` devuelve `live_owner` **siempre que el PID esté
vivo**, y en el runtime siempre-activo ese PID es el de `uvicorn`, que vive toda
la sesión. El lock retenido no se recupera nunca mientras la app siga en pie.

Es literalmente "una tarea puede detener todo el sistema". No es un parche:
necesita un contrato de autoridad con lease, generación y heartbeat, de modo que
un PID vivo deje de bastar para validar un lock y la última tarea en terminar
libere la autoridad. Hay pruebas que hoy fijan el contrato actual
(`test_worker_runtime_recovery.py:32`, `test_worker_lifecycle_hardening.py:30`,
`test_orphaned_task_recovery.py:83` esperan `live_owner`), así que el cambio
tiene que rehacerlas a conciencia, no saltárselas.

## P0 — CORREGIDO (parcial): `last_governor_decision` vacío deja Always-On congelado en `observe_only`

Reportado en vivo por el usuario tras la auditoría de educación: la Cabina
Viva volvió a mostrar `configured_mode=full_local_guarded` /
`effective_mode=observe_only` / `degradado=true` con la misma razón
contradictoria ("...permitido") que se había corregido en la Fase 1
(`7d4b78d`). **No era el mismo bug reapareciendo** — verificado con
evidencia distinta:

- `decide_work_mode()` con condiciones reales (load 2–6, RAM 25GB libre, GPU
  libre) devuelve correctamente `full_local_guarded` sin degradar —
  confirmado con llamada directa.
- Los eventos reales `work_mode_decided` en `worker_events` mostraban
  `effective=full_local` correcto en **cada ciclo automático**, sin
  excepción, durante toda la ventana observada.
- Instrumentado con logging directo en el proceso real (no inferido):
  `get_internal_runtime_governor_status()` devuelve `{}` (vacío)
  **periódicamente**, con una cadencia que coincide con el ciclo de
  self-test (`self_test_every_cycles=5`, `triade/services/supervisor.py`).
  Cuando `governor={}`, `build_always_on_status()` (`always_on.py`) tiene
  `if governor:` — un dict vacío es falsy — así que el bloque entero que
  actualiza `effective_mode`/`degraded_by_governor` se salta por completo,
  dejando el estado congelado en lo último que hubiera (a veces
  `observe_only` heredado de un momento anterior del arranque).

**No identificada con certeza la causa exacta de por qué
`last_governor_decision` queda vacío periódicamente** (hipótesis no
confirmada: alguna llamada dentro del ciclo de self-test —
`run_self_test_cycle` → `build_runtime_heartbeat` →
`get_internal_runtime_state` → `get_internal_runtime_supervisor` — con
`db_path`/`runs_dir` en una forma distinta dispara la lógica de
recreación del singleton `_SUPERVISOR` en `internal_runtime.py`, sirviendo
un objeto nuevo con `last_governor_decision={}`; no se confirmó con
certeza en el tiempo disponible). **Corregido el síntoma de forma segura y
verificada**, no la causa exacta: cuando `governor` viene vacío,
`build_always_on_status()` ahora recalcula una decisión fresca en el acto
(`decide_work_mode` + `build_resource_probe` + `check_ollama_blood`, las
mismas funciones puras/de solo-lectura que ya se usan en el arranque) en
vez de servir un valor potencialmente obsoleto. Verificado en vivo:
correcto inmediatamente tras el fix, y **correcto de nuevo tras superar la
ventana del siguiente ciclo de self-test** (320s de observación
ininterrumpida, sin fallback registrado como fallido). Pendiente para una
sesión dedicada: confirmar la causa raíz exacta de por qué el cache se
vacía, en vez de solo compensarla.

## Auditoría integral 2026-07-31 (post bebb270/9be6f33/5219e00) — 3 bugs P0 más, todos CORREGIDOS

Auditoría de extremo a extremo pedida explícitamente sobre el circuito real
de educación neuronal, con prueba controlada real (no simulada) en cada
paso. Encontró que los dos fixes anteriores (investigación web, next_review)
eran necesarios pero **no suficientes**: el circuito completo tenía dos
eslabones más rotos, silenciosamente, que impedían que `lesson_prepared`
ocurriera alguna vez, y un tercer bug expuesto por los propios fixes.

- **P0, CORREGIDO:** `_candidate_materials()` (`triade/neurons/education_cycle.py`)
  buscaba `learning_queue.status IN ('cross_checked','externally_supported')`
  — dos valores que **ningún productor real escribe jamás**. Verificado:
  583/583 candidatos reales estaban en `internally_checked` (el estado real
  del pipeline), y la consulta devolvía 0 filas siempre, sin importar cuánto
  contenido bueno existiera. Corregido a
  `IN ('internally_checked','validated_in_runs','consolidated')` — el
  vocabulario real de `triade/learning/pipeline.py`. Verificado: la consulta
  pasó de 0 a 25 materiales reales encontrados.
- **P0, CORREGIDO:** con los dos fixes anteriores más este, una prueba real
  controlada (`NeuronEducationCycle.run_once()` en vivo, neurona 12 "Código y
  Reparación") produjo por primera vez `status="lesson_prepared"` con 3
  fuentes independientes reales (Wikipedia, docs.python.org, docs.pytest.org),
  `next_review` actualizado correctamente, y una fila real en
  `learning_evidence` (decision='pending', hipótesis declarada). Ver detalle
  completo del circuito trazado en el reporte de la sesión.
- **P0, CORREGIDO (bug expuesto por el propio fix, no preexistente):**
  `_canonical_execution_result` y el mapeo de estado v2 en
  `triade/workers/worker_loop.py` (dos lugares duplicados) no reconocían
  `"insufficient_sources"`, `"conflicting_sources"`, `"unverifiable"` —
  los 3 estados no-éxito reales que `GovernedResearchWorker.run()`
  (`triade/research/governed.py`) puede devolver. Como `research_curriculum`
  estaba bloqueado antes (bebb270), estos estados eran inalcanzables; al
  correr de verdad, causaban un crash real
  (`unknown_handler_status:unverifiable`, observado en vivo en producción).
  Agregados a la categoría "observado, no reclama éxito indebido" en ambos
  lugares. Verificado con evidencia directa: los 3 estados ya no lanzan
  excepción.
- **P1, CORREGIDO:** `state="material_insufficient"` vs
  `result="insufficient_material"` — mismo caso, misma llamada, dos strings
  con orden de palabras invertido (confirmado, no solo sospechado).
  Normalizado a `insufficient_material` en escrituras nuevas;
  `NeuronEducationCycle.status()` fusiona ambas variantes al contar para no
  fragmentar el histórico. Frontend actualizado a la clave normalizada.
- **P1, CORREGIDO:** el conjunto de dominios curados/confiables
  (`docs.opencv.org`, `pillow.readthedocs.io`, `docs.python.org`,
  `docs.pytest.org`, `es.wikipedia.org`) estaba duplicado en 3 lugares
  independientes con membresías ligeramente distintas
  (`guarded_web.py::CURATED_PUBLIC_SOURCES`, `curriculum.py` sin Wikipedia,
  `worker_loop.py` con Wikipedia — este último introducido en la sesión
  anterior). Consolidado en `guarded_web.TRUSTED_RESEARCH_HOSTS`, única
  fuente de verdad; los otros dos ahora importan de ahí.
- **Observado, no atribuido a un bug de código:** tras un reinicio de
  `triade-workers.service` tomado a mitad de la auditoría (con múltiples
  invocaciones manuales concurrentes de `WorkerLoop`/`WorkerBackgroundService`
  contra la misma DB de producción por parte de la propia sesión de
  auditoría), el servicio entró en crash-loop 5 veces sin ningún error
  registrado en `worker_events` durante la ventana. Una reproducción
  controlada y limpia (mismas variables de entorno reales, sin
  concurrencia) completó sin fallos. Se estabilizó solo tras ~30s y se
  mantuvo estable el resto de la sesión. No se afirma una causa de código
  específica sin evidencia — documentado como posible contención de
  recursos bajo auditoría intensiva, a vigilar, no como corregido.
- **Confirmado, NO corregido (fuera del alcance "solo P0/P1 comprobados",
  no bloquea educación):** la evidencia que crea `lesson_prepared`
  (`learning_evidence`, decision='pending') no tiene ningún proceso
  identificado que resuelva esa decisión — queda como candidato/hipótesis
  permanentemente, sin ruta automática a "improved"/consolidado. La
  educación ejecuta, produce lecciones reales con evidencia real, pero
  "la lección mejoró a la neurona" nunca se demuestra ni se refuta
  automáticamente hoy.

## CORREGIDO — investigación web autónoma nunca corría (commit `bebb270`)

El usuario reportó no ver aprendizaje autónomo usando recursos web en
segundo plano. Verificado en vivo, no supuesto:

- `worker_tasks` (tabla clásica de Living Workers) no recibe filas nuevas
  desde 2026-07-29 07:26 — confirmado observando en tiempo real (0 filas en
  75s). **No es un bug**: el runtime v2 (`autonomous_tasks`, lease/fencing,
  ya mencionado en "Implemented" de `STATUS_CURRENT.md`) reemplazó esa tabla
  y está genuinamente vivo (`pulse_check`, `neuron_candidate_formation`,
  `neuron_autopromotion` cada ~60s, confirmado). Quedó como nota para no
  confundir a futuras auditorías que consulten `worker_tasks` y concluyan
  que el sistema está parado.
- **Bug real:** `_research_curriculum` (`worker_loop.py`) detecta lagunas
  neuronales reales ("Currículo dirigido por 2 lagunas neuronales reales",
  confirmado en payload real) pero nunca incluía `allowed_sources` en el
  `goal_research` delegado. `_goal_research` exige `allowed_sources` no
  vacío o bloquea de inmediato. Resultado: 33 bloqueos en una hora, la
  investigación autónoma nunca corrió pese a detectar lagunas reales.
  Corregido con los mismos dominios curados que `guarded_web.py` ya usa
  como fallback (`docs.opencv.org`, `pillow.readthedocs.io`,
  `docs.python.org`, `docs.pytest.org`, `es.wikipedia.org`) — no se amplió
  a búsqueda sin restricción. Verificado con una llamada real: obtuvo
  contenido real de `docs.python.org` para la laguna de "gobernanza de
  sistemas"; `status="unverifiable"` es correcto cuando solo hay 1 de 2
  fuentes independientes mínimas, no un fallo.
- Confirmado en la misma verificación: la nutrición neuronal vía Ollama
  Blood (`run_neuron_nutrition_cycle`) **sí funciona** — 6 misiones, 6
  evidencias, 6 candidatos, 6 neuronas nutridas en una llamada real durante
  esta sesión.

## Discrepancia adicional con "pytest completo al 100%" (Fase 3)

Al correr `pytest -q tests/ --ignore=tests/operational_truth` (excluyendo el
test de locks ya documentado arriba) apareció una segunda falla real y
preexistente, no causada por esta sesión:
`tests/test_autonomy_delegation.py::test_status_current_mentions_autonomy_delegation`
espera que `docs/STATUS_CURRENT.md` contenga la frase "Autonomía Delegada" /
"autonomía delegada", y no la contiene. No se editó `STATUS_CURRENT.md` para
forzar el texto y pasar el test — sería maquillar la evidencia, no
corregirla. Pendiente: decidir si el test está desactualizado (la sección
correspondiente se renombró) o si `STATUS_CURRENT.md` debe documentar
explícitamente el estado de autonomía delegada. No se ejecutó la suite
completa por costo de tiempo; con esta y la falla de locks documentada
arriba, la afirmación "Pytest completo terminó al 100%" de
`docs/STATUS_CURRENT.md` queda contradicha por evidencia directa, al menos
para este SHA en este entorno.

## P1 — tres sandboxes construidos, solo uno conectado (PARCIALMENTE CORREGIDO)

Verificado con grep exhaustivo (imports reales, no solo presencia del
archivo) de todo `triade/sandbox/` y `triade/core/autonomous_sandbox.py`:
**2316 líneas de infraestructura de sandbox, de las cuales solo 344 están
conectadas a producción.**

- **Viva:** `triade/sandbox/executor.py` + `policy.py` (`run_in_sandbox`,
  exportado en `triade/sandbox/__init__.py`). Conectada vía
  `apps/services.py::wait_local_job()` como fallback cuando un nodo Android
  federado no recoge una tarea a tiempo — la ejecuta localmente en
  aislamiento. `apps/services.py` es importado por `apps/single_port_app.py`
  (producción real) y `triade/workers/worker_loop.py`. Tiene test real
  (`tests/test_sandbox.py`, 205 líneas). Es un sandbox simple: valida contra
  `ALLOWED_TASKS`/`BLOCKED_TASKS`, ejecuta funciones puras (sha256, preprocess
  de texto, análisis de candidatos) — no aísla a nivel de sistema operativo.
- **Construida, sofisticada, NUNCA conectada, cero tests:**
  `triade/sandbox/secure_executor_v2.py` (442 líneas, marcada "T-013" en su
  docstring) implementa ejecución rootless con chroot, política de red
  configurable, límites de GPU/disco/procesos, y una tabla SQLite
  `secure_executions` para replay/auditoría. `secure_executor.py` (252
  líneas, versión anterior), `tool_registry.py` (257) y
  `enhanced_tool_registry.py` (481) tampoco tienen ningún caller ni test
  fuera de sí mismos. `isolation.py` (187) tampoco — las coincidencias de
  "isolation" en tests son la palabra como *tag* de un registro de métricas,
  no el módulo.
- **Construida, sofisticada, NUNCA conectada, cero tests:**
  `triade/core/autonomous_sandbox.py` (353 líneas) implementa snapshot de
  archivos antes de ejecutar, comparación de hashes SHA-256 tras la
  ejecución, y rollback verificable restaurando el contenido original —
  exactamente el mecanismo de "aprender de errores con reversión segura"
  que hace falta para dejar correr más autonomía con seguridad real, no
  solo umbrales.

**No se eliminó nada de esto** (a diferencia de `state_machine.py`/
`lease_retry_breaker.py`/`federation/merge.py` en Fase 3, que eran código
abandonado y sin ambición): esto es trabajo real, bien diseñado, que
alguna sesión autónoma anterior construyó y nunca conectó — no basura.

**Conectado en esta sesión (con aprobación explícita del usuario):**
`AutonomousSandbox` (snapshot SHA-256 + backup + rollback por contenido) ya
está cableado en `WorkerLoop._shell_execute()`
(`triade/workers/worker_loop.py`, task type `goal_safe_command`), como capa
de verificación conservadora y aditiva:
- Con `working_dir` explícito en el payload (nunca sobre el
  `PROJECT_ROOT` por defecto de `safe_shell.run_autonomous` — sería costoso
  hashear todo el repo y sin sentido, el comando ya está gobernado por su
  propia whitelist), se toma snapshot+backup real antes de ejecutar.
- Un comando exitoso **nunca se toca**: solo se añade
  `result["sandbox_file_changes"]` para visibilidad de qué tocó.
- Solo si el comando falló (`status != "ok"`) Y quedaron cambios de
  archivo, se revierte por contenido (no solo se detecta) y se eliminan los
  archivos nuevos que no existían antes —
  `result["sandbox_rollback"] = {"performed": true, "restored_files": N}`.
- `AutonomousSandbox.create_snapshot()` cambió su firma de
  `list[str | Path]` a `Sequence[str | Path]` (covariante; mypy señalaba
  invarianza de `list`, cero cambio de comportamiento).
- Verificado: 4 tests nuevos dedicados
  (`tests/test_worker_shell_sandbox.py` — roundtrip snapshot/restore, éxito
  nunca revierte, falla con cambios sí revierte, sin `working_dir` cero
  regresión) + 82 tests de la suite de workers/sandbox/autonomía existente,
  todos en verde. `triade-workers.service` reiniciado en vivo sin caída de
  los 4 servicios.

**Pendiente, no ejecutado en esta sesión (decisión deliberada, no olvido):**
extender la misma capa a `goal_install` y evaluar si aporta algo sobre el
mecanismo de receipt/rollback que `write_governed_text_artifact` ya tiene
propio (`GovernedFileWriteCapability`) antes de duplicar protección ahí.
`secure_executor_v2.py` (chroot/red/GPU, 442 líneas) sigue sin conectar — es
un proyecto de aislamiento de sistema operativo más grande, con superficie
de riesgo real (escape de chroot, políticas de red) que exige pruebas
dedicadas de seguridad antes de confiar en él; no se improvisa al cierre de
una sesión ya larga.

## P0 — bug real en identidad de locks (CORREGIDO en Fase 3, commit `439116c`)

**`RuntimeProcessLock.inspect()` no detectaba reutilización de PID cuando el
cmdline del proceso no cambió.** Test
`tests/test_worker_lifecycle_hardening.py::test_pid_reuse_identity_mismatch_recovers_lock`
fallaba desde `b0613ea` (antes de esta sesión, no era una regresión de hoy,
pero tampoco estaba documentado). Causa raíz:

- El commit `3c005c0` (30-jul, mismo día) relajó correctamente un bug real:
  antes, `expected_token` (constante hardcodeada `"triade"` en
  `RuntimeProcessLock.payload()`) tenía que aparecer literalmente en el
  cmdline real del proceso, lo cual NUNCA pasa para procesos legítimos
  (`python scripts/runtime_workers.py` no contiene la palabra "triade") —
  causaba falsos positivos marcando workers vivos como huérfanos.
- La relajación quedó excesiva: ahora `expected_token` solo se consulta
  como atenuante *dentro* de la rama `recorded != actual` (cmdline
  cambiado). Si el cmdline grabado coincide con el cmdline actual —el caso
  típico de reutilización de PID por un proceso con invocación similar—,
  el token nunca se compara y el lock se reporta `"live"` aunque
  `expected_token` no coincida en absoluto.
- Problema de fondo, no solo de lógica: `expected_token` es una constante
  fija en todo el código (`"triade"`), no un valor único por instancia de
  proceso, así que en producción NUNCA puede distinguir "este proceso real"
  de "otro proceso que reutilizó el PID" — ambos escribirían el mismo
  token. Arreglar la comparación sin antes darle al token una fuente de
  entropía real (ej. UUID por proceso persistido también en una variable de
  entorno legible vía `/proc/<pid>/environ`.
- **Verificado empíricamente antes de corregir:** escribir a `os.environ`
  en tiempo de ejecución NO actualiza `/proc/<pid>/environ` en este
  entorno (confirmado con una prueba directa), así que un token de
  instancia vía variable de entorno no sirve sin re-exec del proceso.
- **Corrección real aplicada:** `/proc/<pid>/stat` campo 22 (`starttime`,
  jiffies desde el arranque del sistema) sí es una señal de identidad
  garantizada por el kernel — dos procesos con el mismo PID en momentos
  distintos siempre tienen `starttime` distinto, sin importar si su
  cmdline coincide. `RuntimeProcessLock.payload()` ahora graba
  `start_time`; `inspect()` lo usa como verificación primaria, con la
  heurística de cmdline de `3c005c0` como respaldo solo para locks legacy
  sin este campo (para no reintroducir el falso positivo que ese commit
  corrigió). Test corregido para simular reutilización de PID real
  (alterando `start_time`, no solo `expected_token`, que nunca podía
  simular el escenario). Verificado en vivo: `triade-workers.service`
  reiniciado, lock real del proceso activo con `start_time` correcto;
  56/56 tests de locks/leases/recuperación en verde.

## P0 — Learning Pipeline nunca promovía candidatos (CORREGIDO, commit `0c9d234`)

**579 candidatos estancados en `internally_checked`, cero en
`validated_in_runs` o `consolidated`** (verificado contando filas reales de
`learning_queue`, no supuesto). Causa raíz: `_extract_measured_outcome()`
(`run_learning_usage.py`) exige `memory_diff["learning_outcome_score"]` +
`["learning_outcome_evidence_ref"]`, pero nada en producción los escribía —
`runner.py` calculaba un `verification_id` real y lo pasaba como parámetro
`evidence_ref` a `record_learning_usage_from_output()`, pero ese parámetro
nunca se lee dentro de la función (estaba muerto). Cada uso quedaba
`observed_not_counted` para siempre, sin importar cuántas veces se usara un
candidato — el organismo del aprendizaje evidenciado por uso real nunca
había arrancado.

Corrección: el `Verifier` ya calcula 5 scores deterministas y no
autorreportados (coherencia, memoria, safety, utilidad, trazabilidad) en
cada run. `runner.py` ahora escribe el promedio de esos 5 en
`memory_diff["learning_outcome_score"]` y
`f"verification_report:{verification_id}"` en
`memory_diff["learning_outcome_evidence_ref"]`, justo después de calcular
el `VerificationReport`. No se inventó ninguna señal nueva — se cableó una
medición que el sistema ya producía con otra que ya consumía. Verificado en
vivo: `POST /api/run` real devolvió `learning_outcome_score=0.87`,
`learning_outcome_evidence_ref="verification_report:138"`. 85/85 tests
relevantes en verde.

Pendiente de observar: con esto corregido, los candidatos que sí tengan un
match explícito (`used_learning_candidate_ids`, `semantic_matches`,
`evidence_refs`) en runs futuros ahora pueden acumular
`run_use_count`/`avg_outcome_score` reales y cruzar el umbral de
autopromoción (`MIN_RUN_USES=3`, `MIN_OUTCOME_SCORE=0.70`). Los 579
candidatos ya estancados no se reprocesan retroactivamente (no había datos
de uso real que reconstruir); el efecto se observará hacia adelante.

## Decisión Fase 3 — GovernedPlanDispatcher: no conectado a producción (deliberado)

Evaluado conectar `GovernedPlanDispatcher`/`Central.execute_plan_steps` al
ciclo real de `Central.plan()`/`respond()` en `runner.py`. Decisión: **no
conectarlo en esta sesión**. Razones:
- Es una ruta de planificación estructurada alternativa (grafo de pasos con
  presupuesto), no un simple bugfix — integrarla al ciclo cognitivo
  principal cambia el comportamiento de cada run, no solo de un caso
  puntual, y merece su propia validación dedicada (no una corrección
  apurada dentro de una sesión de auditoría de reinicio).
- Ya tiene cobertura de test real y aislada
  (`tests/test_governed_plan_dispatcher.py`,
  `tests/operational_truth/test_invariants.py`), así que no es código en
  riesgo de pudrirse sin uso — es una capacidad lista para cuando se
  decida activarla deliberadamente.
- No implementarlo no bloquea ningún objetivo de "Tríade siempre viva": el
  ciclo cognitivo real (`Central.plan()`/`respond()`) ya funciona sin él.

## Fase 2 — auditoría por órgano (2026-07-30)

Auditoría de conectividad real (call sites, no documentación) de los 6
agentes de exploración lanzados en esta sesión, cubriendo Central/Neuronas,
Hipotálamo/Bodega/Cristal, Workers/Learning, LoRA/PEFT, Federación/nodo
Android, y superficies de entrada. Detalle completo con ruta:línea ya
volcado en `ARCHITECTURE_MAP.md` (marcado `[VERIFICADO 2026-07-30]`); aquí
solo el resumen accionable para Fase 3.

**Código muerto confirmado y ELIMINADO en Fase 3 (2026-07-30, verificado con
grep exhaustivo de todo el repo incluyendo tests antes de borrar — cero
referencias en ningún lado):**
- `triade/workers/state_machine.py` (`WorkerStateMachine`) — borrado.
- `triade/workers/lease_retry_breaker.py` (`Lease`, `CircuitBreaker`, `RetryPolicy`, `LeaseManager`) — borrado. (El `CircuitBreaker` de `advanced_scheduler.py` es una clase homónima distinta, no relacionada; no se tocó.)
- `triade/federation/merge.py` (`FederatedMerge`) — borrado; no estaba exportado en `federation/__init__.py`.

**Corrección importante: NO son código muerto, tienen cobertura de test real
(no se tocaron, deletion habría roto tests):**
- `triade/runtime/governed_plan_dispatcher.py` (`GovernedPlanDispatcher`) y
  `Central.execute_plan_steps/save_plan/load_plan`/`PlanGraph` — SÍ tienen
  tests reales: `tests/test_governed_plan_dispatcher.py`,
  `tests/test_governed_text_artifact_e2e.py`,
  `tests/test_no_simulated_autonomy.py`, y
  `tests/operational_truth/test_invariants.py` (esta última parece parte de
  la suite de invariantes operacionales, posiblemente gateada en CI). Estado
  real: **implementado y probado, pero sin ningún caller de producción**
  (runner/workers/API) — es una capacidad lista pero nunca conectada al
  ciclo en vivo, no código sin uso. Decisión pendiente: conectarla al runner
  o documentar explícitamente por qué se mantiene solo como capacidad
  probada y no activa.
- `triade/memory/semantic_embedding_engine.py::embed_pending()` — tiene test
  real (`tests/test_semantic_embedding_engine.py:104-110`). Mismo caso:
  probado, sin caller de producción.

**Código vestigial ("por estar", construido pero sin efecto) dentro del ciclo 24/7:**
- `worker_loop.py:1684-1685` instancia `SemanticMemoryStore`/`SemanticMemoryGovernance` sin invocar ningún método.
- **Corregido en Fase 3:** `worker_loop.py` usaba un `CrystalPacket` estático
  (`temporal_status="stable"` fijo) en vez de llamar a `Crystal.regulate()`
  real dentro de `_safety_for_task()`. `Crystal.regulate()` es cómputo puro
  (sin I/O ni llamadas a Ollama), así que conectarlo es seguro y barato.
  Ahora los ciclos de fondo (los 19 task types de Living Workers) pasan por
  el mismo regulador Cristal real que los runs conversacionales, con
  `pv7_score`/`stability`/`temporal_status` calculados de verdad en vez de
  un valor fijo. Verificado: 14/14 tests de `test_worker_loop.py` +
  `test_worker_safety_blocks_identity_change.py` +
  `test_worker_stable_consolidation_review.py` +
  `test_worker_learning_integration.py` + `test_worker_qualia_integration.py`
  + `test_worker_runtime_recovery.py` en verde tras el cambio.

**Pendiente de confirmar (no clasificado con certeza):**
- Si `learning_outcome_score`/`learning_outcome_evidence_ref` se están poblando realmente en producción para que la transición `internally_checked → validated_in_runs` del Learning Pipeline cuente casos de uso, o si en la práctica casi todo cae en `observed_not_counted`.
- `installer.py` (`goal_install`) está conectado en el dispatcher pero la tabla `installer_attempts` no existe aún en la DB actual — sugiere que ese camino nunca corrió de verdad.

**Documentación desactualizada corregida en `ARCHITECTURE_MAP.md`:**
- La nota "N Creadora/N Formadora/Registry fuera del ciclo" era falsa — están conectadas al runner y al ciclo 24/7.
- La "duplicación D-07" (`chat_ui_app.py` etc.) ya fue eliminada por el propio proyecto el 2026-07-29 (commit `aa001f3`); el mapa seguía describiendo archivos que ya no existen.
- README subestima Living Workers: son 19 task types reales, no 10.
- La carpeta `systemd/` (raíz) es legado de otra máquina (`/home/santiago/triadees`) y colisionaría en puerto 8010 con `deploy/systemd/` si se instalara; un worker autónomo (`aa001f3`) la sigue tocando — riesgo real de que algún proceso futuro la active por error.

**Hallazgo positivo confirmado (no era solo aspiracional):** el nodo Android
(`android/triade-node/`) tiene 1296 líneas de Java funcional con llamadas
HTTP reales a los endpoints de federación/relay, no un esqueleto vacío. El
pipeline LoRA/PEFT entrenó de verdad con evidencia en DB y disco, y su gate
de aprobación humana bloquea genuinamente en código, no solo en la
documentación.

## P0 — certificación local

- **Pendiente:** ejecutar desde el SHA final, sin compresión, las ventanas de
  24 h y 72 h. El runner ya mide disponibilidad, duplicados, pérdidas, falsos
  `completed`, corrupción, resultados tardíos, artifacts, rollback, reinicios,
  snapshots y RSS. `long_run_verified=false` hasta que ambos reportes pasen.
- **Verificado en runtime aislado:** chaos 15/15 con worker y API reales,
  reinicio de Ollama, ENOSPC, watchdog, GPU oculta, memoria limitada y los diez
  fallos restantes. Cero duplicados, pérdidas, falsos cierres, corrupción,
  tardíos y artifacts perdidos; rollback 100%. La disponibilidad se mide en
  24/72 h, no se inventa para chaos.
- **Cerrado localmente:** Ruff pasó de 271 incidencias a cero y mypy de 224
  errores a cero en 324 archivos fuente, sin desactivar reglas ni añadir
  ignores/noqa/skips/xfail.
- **Parcial:** GitHub Actions estuvo verde en `00a05aa` para Runtime Truth CI,
  Tríade Tests y Measurement Core. Cada commit posterior invalida ese gate; se
  requiere registrar los cuatro workflows obligatorios en verde sobre el SHA
  final mediante `scripts/record_ci_evidence.py`.
- **Pendiente:** regenerar TRIADE-VERIFY-v1 sobre el SHA final. El manifest de
  `2e186b4` fue `PARTIAL_SAFE`: `long_run_verified=false` y
  `ci_verified=false`.

## P1 — producción confiable

- **Verificado localmente:** A/B real multi-modelo por siete roles. El routing
  adoptado mejoró calidad de 0.6786 a 0.9643 con ratio de recursos 1.302 dentro
  del límite predefinido 2.0; tiene evidencia hash y rollback atómico.
- **Pendiente externo:** LoRA canary requiere aprobación humana nominal, tráfico
  controlado real y rollback observado durante serving. Entrenamiento no activa
  automáticamente el adaptador.
- **Pendiente externo:** federación sostenida entre dos hosts distintos. Dos
  procesos TCP reales en un host ya prueban firma, reproducción y revocación,
  pero no equivalen a hosts separados ni a operación offline/online prolongada.
- **Verificado localmente:** rate limiting y sesiones/revocaciones compartidas
  usan Redis con operación Lua atómica; dos réplicas SQLite contra un Redis real
  probaron cuota y revocación cruzadas. `public_guarded` falla cerrado sin Redis.
- **Pendiente externo:** evaluación adversarial independiente de prompt
  injection, abuso y egress. Los tests internos no se presentan como auditoría
  externa.
- **Pendiente temporal:** mantener una ventana productiva legacy y confirmar
  duplicados/pérdidas cero antes de bloquear definitivamente writes o retirar
  tablas. No se borró historial.
- **Verificado una vez / seguimiento pendiente:** restore drill cifrado real,
  identidad, SQLite, 455 refs de artifacts y estados de tareas correctos. El
  worker agenda drills semanales, pero aún faltan semanas de cumplimiento.
- **Verificado localmente:** 503 snapshots históricos quedaron recuperables en
  cuarentena y el volumen bajó de 35 GB a 5.1 GB. Continúa pendiente observar
  crecimiento durante semanas y fijar presupuesto productivo.
- **Pendiente externo:** dominio estable, TLS, ingress y supervisión fuera de
  Cloudspace. La URL actual HTTP 200 no demuestra infraestructura persistente.

## P2 — madurez y escalabilidad

- **Parcial:** continuar separando fronteras DB, contracts, runtime, workers,
  security, federation y learning. El gate estático está verde, pero el tamaño y
  acoplamiento arquitectónico siguen requiriendo reducción incremental.
- **Cerrado para el baseline estático:** se retiraron catches silenciosos y
  amplios detectados por Ruff con manejo específico. Nuevos catches requieren
  revisión semántica aunque Ruff permanezca verde.
- **Pendiente:** ampliar memoria longitudinal con corpus independiente del
  implementador, casos adversariales y múltiples idiomas.
- **Pendiente:** repetir aprendizaje autónomo con tareas más complejas, corpus
  retenido y controles explícitos contra sobreajuste.
- **Pendiente temporal:** medir utilidad autónoma durante semanas; heartbeat,
  pulse y maintenance siguen excluidos de mejora.
- **Parcial:** existe observabilidad runtime actual y métricas de long-run;
  faltan series históricas durables y alertas operacionales externas.
- **Condicional:** generación visual solo se añadirá con caso de uso, evaluación
  de seguridad y benchmark. `gemma3:4b` aporta comprensión, no generación.
- **Pendiente:** benchmark reproducible de capacidad máxima de usuarios, tareas,
  memoria y almacenamiento.
- **Pendiente:** aprobar SLO, RTO, RPO y presupuesto de error de producción con
  resultados de capacidad y 72 h; no se fijarán números como hechos sin medir.
- **Límite explícito:** Tríade OS es un plano de control sobre Linux, no un
  kernel ni un sistema operativo anfitrión independiente.

## P1 — hallazgos 2026-07-30 (sesión de auditoría post-reinicio)

- **Corregido con evidencia:** `triade-ollama.service` quedaba en loop de
  reinicio infinito (150+ reintentos) porque `.lightning_studio/on_start.sh`
  arrancaba Ollama con `nohup` compitiendo por el puerto 11434 contra el propio
  unit systemd (`Restart=always`), que siempre perdía la carrera. El servicio
  vivía sin supervisión real aunque respondía. Corregido: `on_start.sh` ahora
  usa `systemctl start` (idempotente) y solo cae a `nohup` si el unit no existe
  (bootstrap). Ver `deploy/lightning_studio/on_start.sh`. Verificado sin caída
  de servicio (ollama.ok=true antes/después, 6 modelos intactos).
- **Corregido con evidencia:** `scripts/triade_doctor_full.py` tenía una
  f-string suelta sin `print()` que ocultaba el SHA en el reporte humano.
- **Corregido con evidencia:** `deploy/systemd/*.service` y `*.timer` estaban
  desincronizados de los units realmente instalados en
  `/etc/systemd/system/` (paths, usuario, `ProtectSystem`, dependencias);
  `triade-ollama.service` ni siquiera estaba versionado. Si esta Cloudspace se
  recreara desde el repo, la configuración real no se reproduciría. Re-sincronizado
  byte a byte desde los units instalados y verificados en producción local.
- **Corregido con evidencia:** el dashboard mostraba `razon_degradacion` =
  "Hardware tier high con AC y Ollama Blood activa. Full local guarded
  permitido." junto con `degraded_by_governor=true` y
  `effective_mode=observe_only` — el propio texto de la razón contradecía la
  degradación. Causa raíz doble:
  1. `always_on.py` pasaba el nivel de autonomía del continuous-runner
     (`observe_only/form_candidates/train_candidates/promote_experimental/promote_stable`)
     directamente a `resource_governor.decide_work_mode()`, que solo conoce el
     vocabulario de modos operativos (`observe_only…full_local_guarded`). Un
     valor como `promote_stable` no existe en `WORK_MODE_RANK` y se evaluaba
     con rango 0 (el más bajo), forzando una degradación espuria. Corregido en
     `triade/core/always_on.py`: el gobernador ahora recibe `resource_mode`
     (`cfg["mode"]`) en vez del nivel de autonomía.
  2. `InternalRuntimeSupervisor` (el ciclo que sí reevalúa en vivo) lee
     `TRIADE_RUNTIME_MODE`/`TRIADE_RUNTIME_ENABLED` — variables de entorno
     independientes de `TRIADE_ALWAYS_ON_*` y no documentadas en
     `docs/ALWAYS_ON_RUNTIME.md` ni en ningún `.env*.example`. Al no estar
     seteadas en `/etc/triade/triade.env`, el supervisor vivía en
     `mode=observe_only, enabled=false` real sin importar lo que decidiera
     Always-On. Añadidas a `/etc/triade/triade.env` (no versionable, contiene
     `TRIADE_BACKUP_KEY`); pendiente documentarlas y añadir un template
     versionado del env real (`deploy/triade.env.example`) para que sea
     reproducible si la Cloudspace se recrea.
  Verificado tras reinicio de `triade-api.service`: `effective_mode=
  full_local_guarded`, `degraded_by_governor=false`, supervisor real en
  `mode=full_local, enabled=true`.
- **Efecto colateral real del fix anterior, corregido con evidencia:** al
  activarse `full_local_guarded` por primera vez de verdad, `GET
  /api/ui/react-dashboard` y `/triade/run` (chat) quedaron colgados 60s+ en
  vivo — reportado por el usuario ("no me responde, se queda pensando").
  Stack trace (`faulthandler.dump_traceback_later`) mostró el cuelgue exacto:
  `ollama_client.embed()` esperando una respuesta HTTP de Ollama, llamado
  desde `bodega.recall()` → `build_bodega_global_context()` →
  `build_runtime_heartbeat()` → `react_dashboard()`. Causa: el unit
  `triade-ollama.service` fijaba `OLLAMA_MAX_LOADED_MODELS=1` y
  `OLLAMA_NUM_PARALLEL=1`; con el runtime ahora realmente activo, cada
  petición de embedding forzaba descargar el modelo de razonamiento y cargar
  `nomic-embed-text` (o viceversa), serializando todo. Con 22 GB de VRAM
  libres de 23 GB y los 6 modelos instalados sumando 11.3 GB, subido a
  `OLLAMA_MAX_LOADED_MODELS=3` / `OLLAMA_NUM_PARALLEL=2` en
  `/etc/systemd/system/triade-ollama.service` (pendiente de sincronizar en
  `deploy/systemd/triade-ollama.service` y commitear). Verificado: `embed()`
  directo 0.07s con ambos modelos residentes a la vez; tras reiniciar
  `triade-api.service` para vaciar el backlog de hilos ya atascados (algunos
  esperando hasta 180s por el timeout ampliado en esta misma sesión),
  `react-dashboard` respondió en 2.7s y `/api/run` (chat) completó en 23.7s
  con contenido real.
- **Pendiente:** crear `deploy/triade.env.example` versionado con el conjunto
  completo de variables reales usadas en producción local (`TRIADE_ALWAYS_ON_*`
  y `TRIADE_RUNTIME_*`), y un script `deploy/render_triade_env.sh` o similar
  para que `/etc/triade/triade.env` sea reproducible desde el repo, no
  "auto-generado" a mano una vez y luego huérfano.
- **Discrepancia con STATUS_CURRENT.md ("Ruff cero... mypy cero en 324
  archivos"):** en esta Cloudspace, `ruff check .` reporta 643 errores, pero
  613 son `EXE002` (bit ejecutable en archivos `.py` sin shebang) causado por
  `core.fileMode=false` en este entorno — ruido específico del filesystem, no
  del código. Descontando `EXE002`, el baseline ya commiteado (SHA `b0613ea`)
  tiene **18 errores reales de Ruff** (F401, SIM102 en `triade/metabolism/*` y
  `triade/runtime/process_lock.py`, entre otros) y **1 error real de mypy**
  (`triade/workers/worker_loop.py:394`, asignación `float` a variable `int`).
  Ninguno se corrigió en esta sesión por estar fuera del alcance de los
  archivos tocados; quedan listados aquí para que "Ruff/mypy cero" deje de
  afirmarse sin evidencia reproducible en este entorno.
- **Confirmado y cerrado (2026-07-30, ronda posterior):** el cuelgue de `GET
  /api/runtime/heartbeat` era el mismo problema de fondo que el cuelgue del
  dashboard/chat documentado abajo (`OLLAMA_MAX_LOADED_MODELS=1` forzando
  descarga/carga de modelos en cada embedding). Re-probado tras el fix de
  `OLLAMA_MAX_LOADED_MODELS=3`/`OLLAMA_NUM_PARALLEL=2`: 5 llamadas solas
  (1.5–2.2s) y 6 llamadas concurrentes (10–12s, degradación normal bajo
  carga, no cuelgue) — cero fallos. Sigue siendo cierto que la función no es
  tan liviana como dice README (llama a Ollama y construye contexto vivo
  completo); eso queda como nota de precisión de documentación, no como bug
  de disponibilidad.

## Cerrado con evidencia local

- Ejecución con lease, fencing, postcondición, artifact, receipt y rollback.
- Identidad continua, traza causal triádica, memoria longitudinal y modulación
  relacional gobernada.
- Metacognición calibrada, research gobernado, aprendizaje con transferencia,
  persistencia y rollback, Utility Ledger y certificación neuronal.
- Autenticación/RBAC/sesiones, estado distribuido Redis, backup cifrado y
  federación TCP de dos procesos.

## Regla de cierre

Una deuda solo se cierra con código, pruebas, evidencia runtime, documentación y
ruta de recuperación. Actividad, persistencia o etiquetas no sustituyen efecto,
recuperación útil ni aprendizaje validado.

## P2 — DOCUMENTADO, no corregido: el gobernador degrada a `cooldown` en cada arranque frío

Reportado en vivo: `razon_degradacion = "Load average (24.24) muy alto para 8
CPUs.; Modo solicitado 'full_local' excede permitido 'cooldown'. Degradado."`
tras reiniciar. **No lo causan los Living Workers.** Regla en
`resource_governor.py`: `load_1min > cpu_count * 2` → `cooldown`; con 8 CPUs el
umbral es 16.

Evidencia (`worker_events`, `event_type='work_mode_decided'`):

| hora | load | efectivo |
|---|---|---|
| 03:31:38 — 2 s tras `last_start_at` | 59,83 | cooldown |
| 03:32:39 | 24,24 | cooldown |
| 03:33:41 en adelante | 2,x | `full_local` |

En 482 decisiones registradas sólo **3** degradaron por load, y las tres son la
primera decisión de un ciclo de arranque. Cero en régimen estable.

Mecanismo: el `lifespan` de `apps/single_port_app.py` llama
`start_workers_if_configured` → `ensure_workers_alive` → `_decide_worker_mode` →
`build_resource_probe()` en el mismo bloque que verifica identidad, siembra
neuronas fundacionales y lanza `start_model_acquisition_background` (que arranca
los `llama-server`). Lee `/proc/loadavg` en el pico exacto del arranque, y
`load_1min` es una media con inercia de un minuto: describe el minuto *anterior*,
no la capacidad presente.

Agravante medido: `/proc/loadavg` es del **host** (919 procesos totales frente a
39 dentro del contenedor) mientras `cpu_count` sale de `os.cpu_count()` del
cgroup. Se comparan magnitudes distintas. `/proc/pressure/cpu` daba
`full avg10=0.00` — el contenedor no estaba ahogado en ningún momento.

Se deja **sin corregir a propósito**: degradar dos minutos en un arranque frío es
conservador, y elegir entre una gracia de arranque, `load_5min` o presión PSI es
una decisión de producto, no una corrección. Lo que sí faltaba es cobertura: la
regla no tenía ninguna prueba (`tests/test_resource_governor.py` fijaba
`load_1min=1.0` en todos los casos). Añadidas
`test_high_load_average_forces_cooldown` y
`test_load_average_just_under_the_threshold_does_not_degrade`, para que un
cambio en esa regla sea visible y no una deriva.
