# Auditoría profunda · Tríade Ω · 2026-08-02

Auditoría de arquitectura sobre el código, no sobre la documentación. Cada
hallazgo se cierra con evidencia de primera mano (código citado por
`archivo:línea`, ejecución real, o consulta a la base viva). Donde un documento
anterior o el propio sistema afirma algo que el código contradice, gana el
código.

**Método:** lectura de código, `grep` sobre AST/imports, reconstrucción del call
graph, sondeo no destructivo de la API pública en vivo
(`https://8010-…litng.ai`), y consulta a `triade/memory/triade.db`.

**Regla de estados:** cada hallazgo termina en exactamente uno de
`VERIFIED` · `PARTIAL` · `FALSE POSITIVE` · `NEEDS MORE EVIDENCE`.

---

## Resumen ejecutivo

| # | Hallazgo | Estado | Riesgo |
|---|----------|--------|--------|
| 1 | Sandbox declarado vs real | **VERIFIED** (es lógico, no de SO) | ALTO |
| 2 | Ruta de ejecución LLM → código | **PARTIAL** (gobernada, con un hueco) | ALTO |
| 3 | Seguridad de subprocess | **VERIFIED** (sin `shell=True`/`eval` en runtime) | MEDIO |
| 4 | Seguridad de filesystem | **VERIFIED** (zonas reales; `tests/` es amarilla) | ALTO |
| 5 | Red | **PARTIAL** (SSRF cubierto; egress amplio) | MEDIO |
| 6 | CI | **VERIFIED** (ejecuta de verdad; rojo real en main) | MEDIO |
| 7 | Dependencias | **VERIFIED** (no reproducible) | MEDIO |
| 8 | Código muerto | **VERIFIED** (~1.900 LOC de sandbox sin uso) | MEDIO |
| 9 | Aprendizaje | **PARTIAL** (transición final casi no ocurre) | ALTO |
| 10 | Arquitectura | mapa (maduro / experimental / prototipo) | — |

**NUEVOS HALLAZGOS** (sección propia al final):
- **P0** · La API pública no está autenticada y `TRIADE_API_KEY` está vacía →
  el único cerrojo real de escritura falla abierto.
- **P1** · `authorized_root` de la escritura gobernada viene del mismo payload
  que el `target`.
- **P1** · El Artículo VI de la constitución afirma límites de CPU/RAM/PID que la
  ruta viva no aplica.
- **P2** · `isolation.enforce()` devuelve `"enforced"` sin comprobar nada.

---

# HALLAZGO 1 · Sandbox declarado vs sandbox real

**Estado: VERIFIED** — el aislamiento es **puramente lógico** (whitelist +
filtros de texto + timeout). No hay aislamiento del sistema operativo en ninguna
ruta viva.

**Riesgo: ALTO.** **Prioridad: P1.**

### Las 12 preguntas, respondidas contra el código

| # | Pregunta | Respuesta | Evidencia |
|---|----------|-----------|-----------|
| 1 | ¿Aislamiento real del SO? | **No** | ninguna primitiva presente (abajo) |
| 2 | ¿namespace? | **No** | `grep unshare\|setns\|CLONE_NEW` → 0 |
| 3 | ¿seccomp? | **No** | `grep seccomp\|prctl` → 0 |
| 4 | ¿AppArmor? | **No** | `grep apparmor` → 0 |
| 5 | ¿rootless container? | **No** (solo el nombre) | `SandboxConfig.rootless=True` es un campo sin efecto |
| 6 | ¿bubblewrap? | **No** | `grep bwrap\|bubblewrap` → 0 |
| 7 | ¿chroot? | **No** | `secure_executor_v2.py:193` usa `cwd=chroot_path`, que **no es** `chroot()` |
| 8 | ¿bloqueo real de red? | **No** | se filtran subcadenas (`curl`, `wget`) en el texto del comando |
| 9 | ¿filesystem read-only? | **No** | ninguna ruta monta RO; `read_only_paths` es un campo inerte |
| 10 | ¿`filesystem_writes_allowed` se aplica? | **No** | `isolation.py:28` lo declara; nadie lo lee para bloquear |
| 11 | ¿`network_allowed` se aplica? | **No** | `isolation.py:27` lo declara; nadie lo lee para bloquear |
| 12 | ¿el bloqueo depende de filtros de texto? | **Sí, exclusivamente** | `secure_executor_v2.py:104-156`, `safe_shell.py:_validate_command` |

**Barrido de primitivas de aislamiento en TODO el repo:**

```
unshare/setns/clone(NEW)  → 0
seccomp/prctl             → 0
apparmor                  → 0
bubblewrap/bwrap/nsjail   → 0
firejail                  → 0
chroot()  (la syscall)    → 0   (solo `chroot_path` como string y cwd)
landlock/cgroup           → 0
setrlimit                 → 7   (todas en código muerto o scripts, ver abajo)
```

### Los tres "sandbox seguros" son código muerto

`triade/sandbox/` contiene 1.982 líneas. La clase que más promete —
`SecureExecutor` en `secure_executor_v2.py`, con docstring *"rootless, sandbox
completo, replay, filesystem aislado, network policy, GPU/disk limits"*— **no la
importa nadie**:

```
grep -rn "secure_executor_v2|SecureExecutor" (fuera de sandbox/) → 0 usos
```

Peor: **está rota**. Ejecuta con `shell=False` pero pasa el comando como
**string**, no como lista (`secure_executor_v2.py:186-194`):

```python
result = subprocess.run(
    command,            # str, no list
    shell=False,        # con shell=False esto busca un binario llamado "echo hola"
    ...
)
```

Reproducido:

```
$ subprocess.run('echo hola', shell=False, ...)
FileNotFoundError: [Errno 2] No such file or directory: 'echo hola'
```

`secure_executor.py` (252 LOC, con `setrlimit` real) y `tool_registry.py` (257
LOC) también tienen **0 usos**. Ver Hallazgo 8.

### El único sandbox VIVO

`triade/sandbox/executor.py::run_in_sandbox` — el único que se importa en
producción (`core/runner.py:532`, `apps/services.py:324`). No aísla nada porque
**no ejecuta nada externo**: es un `dict`-dispatch de 9 funciones puras de
Python (`executor.py:131-161`). `sha256`, `echo`, contar palabras. Y reporta
campos de seguridad **hardcodeados** independientemente de lo que pase:

```python
result["network_used"] = False      # executor.py:102 — literal, no medido
result["shell_used"] = False         # executor.py:103 — literal, no medido
result["writes_outside_sandbox"] = False
```

Algunas de esas 9 funciones ni siquiera calculan: `_task_browser_benchmark`
devuelve `random.randint(5000, 15000)` (`executor.py:277-288`).

### Arquitectura correcta para producción

El sandbox lógico es **suficiente para lo que hoy ejecuta** (funciones puras),
pero el nombre y los docstrings prometen aislamiento de SO que no existe, y hay
rutas vivas (`autonomous_sandbox`, `engineering_worker`) que sí lanzan `python`
y `pytest` reales sin ninguna contención. Para esas:

1. **bubblewrap rootless** (`bwrap --unshare-all --ro-bind / / --bind $work
   $work --die-with-parent --new-session`) como envoltorio de todo `subprocess`
   que ejecute código no whitelistado. Es la opción sin privilegios, encaja en
   el Studio.
2. **`setrlimit` en un `preexec_fn`** (RLIMIT_CPU, RLIMIT_AS, RLIMIT_NPROC,
   RLIMIT_FSIZE) — el código ya existe en `secure_executor.py:129-135`, solo hay
   que conectarlo a la ruta viva en vez de dejarlo muerto.
3. **Red denegada por namespace** (`--unshare-net`), no por `grep` de subcadenas
   — hoy `curl$(printf '\x20')evil` evade el filtro trivialmente.
4. Borrar `secure_executor_v2.py` o arreglarlo; mantener código de seguridad
   roto es peor que no tenerlo, porque su nombre sugiere una protección real.

---

# HALLAZGO 2 · Ruta completa de ejecución (Usuario → Execute)

**Estado: PARTIAL** — la ruta está gobernada y un LLM **no** ejecuta comandos de
texto libre, pero **sí** puede provocar ejecución de código arbitrario por una
vía indirecta (plantar un test + disparar `pytest`), y `autonomy_level` viaja en
el payload.

**Riesgo: ALTO.** **Prioridad: P1.**

### Traza reconstruida

```
Usuario/LLM (texto)
  └─ CapabilityResolver.resolve(request)         core/capability_resolver.py:37
       · regex sobre el texto → capability + command_KEY fija (no comando libre)
  └─ GoalOrchestrator.plan_and_dispatch()         core/goal_orchestrator.py
       · si requires_human_approval → se detiene en awaiting_approval  (:56)
       · si no → enqueue(worker_task_type, payload)                    (:100)
         payload fija autonomy_level="train_candidates"                (:86)
  └─ AutonomousTaskStore  (cola autonomous_tasks, lease atómico)
  └─ WorkerLoop  → handlers[task.task_type]                            worker_loop.py:1309
       └─ _goal_safe_command → _shell_execute                         worker_loop.py:2948,2820
            └─ safe_shell.run_autonomous(command_KEY, autonomy_level)  safe_shell.py:258
                 · busca la clave en WHITELIST/AUTONOMOUS_SAFE_EXTENSIONS
                 · _validate_command: BLOCKED_KEYWORDS + gating        safe_shell.py:153
                 · subprocess.run(cmd_LISTA, shell=False, cwd=proyecto) safe_shell.py:377
```

### Respuestas exactas

- **¿Un LLM puede ejecutar código arbitrario?** **Indirectamente, sí.** No por
  comando de texto (la whitelist lo impide), sino porque la whitelist **incluye
  `pytest`** (`test_quick`, `test_verbose`, `coverage` en
  `safe_shell.py:44-47`), y `pytest` importa y ejecuta todo `tests/`. Quien
  pueda **escribir un fichero en `tests/`** (zona amarilla, sin humano — ver
  Hallazgo 4) y luego disparar `test_quick`, ejecuta ese código. La cadena
  completa desde Internet está en NUEVOS HALLAZGOS P0.
- **¿Puede construir comandos?** **No.** `run_autonomous` recibe una **clave**
  (`command_key`), nunca un comando. El comando sale de un `dict` fijo.
- **¿Puede modificar argumentos?** **Parcial.** `timeout` y `working_dir` del
  payload; `working_dir` está confinado al proyecto (`safe_shell.py:283-285`).
  Los argumentos del comando en sí no.
- **¿Puede escribir archivos?** **Sí**, vía `safe_create_file`/`safe_patch_file`
  en zonas green/yellow (Hallazgo 4).
- **¿Puede ejecutar Python?** **Sí**, indirectamente vía `pytest`, y
  directamente vía `autonomous_sandbox.execute_code` — que resulta ser código
  muerto (Hallazgo 8), y vía `engineering_worker` (compileall/pytest en git
  worktree, `evolution/engineering_worker.py:269`).
- **¿Puede invocar subprocess?** Solo el que ya está en la whitelist.

### Hueco de gobierno

`autonomy_level` llega en `task.payload` (`worker_loop.py:2843`) y se pasa tal
cual a `run_autonomous`. El orquestador lo fija en `"train_candidates"`
(`goal_orchestrator.py:86`), pero **nada en `_shell_execute` verifica que el
payload no fue construido por otra vía** con un nivel más alto. La defensa real
es que solo el orquestador encola estas tareas y no hay endpoint que encole
`goal_safe_command` con payload libre — pero el contrato descansa en esa
ausencia, no en una comprobación.

---

# HALLAZGO 3 · Seguridad de subprocess

**Estado: VERIFIED** — no hay `shell=True`, `eval()`, `exec()`, `os.system` ni
`compile()` en el runtime de producción. El riesgo de subprocess es de
**argumentos**, no de shell.

**Riesgo: MEDIO.** **Prioridad: P2.**

### Barrido completo

```
shell=True   → 0 en triade/ y apps/  (solo scripts/live_runtime_audit.py:41,
               scripts/triade_doctor_full.py:26 — herramientas de operador, no runtime)
eval( / exec( → 0 reales; los hits son STRINGS de patrones-bloqueados
               (safety.py:43-46, secure_executor.py:53) y el `.eval()` de torch
os.system    → 0
os.exec*     → 0
compile()    → 0 en runtime
__import__   → cosmético: __import__('time').time() (central.py:176) — no dinámico
importlib    → 0 con input externo
pty          → 0
```

### `subprocess.run` en runtime (clasificado por riesgo)

**Bajo** (argv fijo, sin input externo): `repo_info.py:36`,
`repo_runtime_status.py:19`, `system_monitor.py:165`, `hardware_profile.py:334`,
`senses.py:533`, `hypothalamus`… — leen git/uname/nvidia-smi con listas
constantes.

**Medio** (argv de whitelist con `cwd` del payload): `safe_shell.py:217,378`,
`governed_task_executor.py:226` (`Popen` de `[sys.executable, ...]`).

**Alto** (ejecutan código del repo/plantable): `autonomous_sandbox.py:135`
(`python _sandbox_exec.py` — **código muerto**, ver H8),
`engineering_worker.py:269` (compileall+pytest en worktree),
`safe_shell.py` `test_quick`/`coverage` (pytest sobre `tests/`).

Ninguno usa `shell=True`, así que no hay inyección de shell. El riesgo residual
es que `pytest` es, por diseño, un ejecutor de código arbitrario del árbol de
tests.

---

# HALLAZGO 4 · Seguridad del filesystem

**Estado: VERIFIED** — existe un modelo de zonas real y aplicado
(`system_zones.py`), con papelera y backup. Pero **`tests/` es zona amarilla**
(escritura sin humano), y eso es la primera mitad de la cadena RCE.

**Riesgo: ALTO.** **Prioridad: P1.**

### El modelo de zonas (`triade/core/system_zones.py`)

| Zona | Prefijos | Crear/modificar sin humano |
|------|----------|----------------------------|
| **green** | `runs/ artifacts/ reports/ logs/ tmp/ cache/ .triade_trash/` | Sí (dentro de presupuesto) |
| **yellow** | `docs/ tests/ frontend/src/ apps/routes/ triade/core/ triade/workers/ triade/models/` | **Sí** (dry-run + verificación) |
| **red** | `triade/memory/ config/ migrations/ pyproject.toml package.json` | No (aprobación humana) |
| **forbidden** | `.git/ .env secrets identity_core private_keys` | Nunca |

El modelo es correcto y se aplica de verdad: `safe_file_ops._blocked()`
(`safe_file_ops.py:88-112`) bloquea `forbidden`, exige humano en `red` y
`yellow_unknown`, y respeta el presupuesto por nivel. Hay backup
(`_backup_file`, `:29`) y borrado solo-a-papelera
(`autonomy_budget.py:42: delete_strategy=trash_only`).

### El problema

`tests/`, `triade/core/` y `triade/workers/` están en **amarilla** — creables y
modificables sin aprobación humana con el nivel adecuado. Combinado con que
`pytest` está en la whitelist de shell (H2), un escritor en `tests/` obtiene
ejecución de código. `triade/core/` y `triade/workers/` en amarilla significa
además que el sistema puede reescribir su propia lógica de gobierno sin humano,
si el nivel de autonomía lo permite.

### Qué debería cambiar

- `tests/`, `triade/core/`, `triade/workers/` deberían ser **rojas**: tocar el
  código que gobierna al sistema, o el que `pytest` ejecutará, no es una
  operación amarilla.
- La whitelist de shell no debería contener `pytest` accesible desde la misma
  ruta que puede escribir en `tests/`. Si el sistema necesita correr tests, que
  sea sobre un worktree de solo-lectura (como ya hace `engineering_worker`).

### Escrituras inventariadas

`open(...,"w")`, `write_text`, `mkdir`, `shutil.copy2/move`, `unlink`,
`trash_path` — todas las de runtime pasan por `safe_file_ops` o por
`AtomicArtifactWriter` (escritura atómica con backup). Las escrituras directas a
disco fuera de ese marco son artefactos de run (`runs/`, verde) y la propia
`triade.db`.

---

# HALLAZGO 5 · Red

**Estado: PARTIAL** — hay una guarda anti-SSRF real y correcta para la
investigación web, pero la superficie de egress es amplia y el toolkit HTTP se
usa sin una allowlist central salvo en esa ruta.

**Riesgo: MEDIO.** **Prioridad: P2.**

### Egress en producción

Todo el tráfico saliente usa `urllib.request` (no `requests`/`httpx` en runtime,
pese a estar en deps). Componentes que salen a la red:

- `models/ollama_client.py` — **localhost:11434** (Ollama). Correcto, debe.
- `core/guarded_web.py` — investigación web. **Debe**, con guarda (abajo).
- `federation/edge_router.py`, `federation/peer_sync.py` — federación P2P.
  **Debe**, pero ver replay/nonce.
- `models/meta_orchestrator.py` — descarga de modelos.
- `core/system_monitor.py:201,329` — sondeo HTTP. Revisar destino.

### La guarda SSRF (`guarded_web.py::_assert_public_url`, :268)

Es **sólida** para lo básico:

```python
if parsed.scheme not in {"http","https"}: raise    # sin file://, gopher://
if host localhost / .local: raise                   # sin loopback por nombre
for addr in socket.getaddrinfo(host,...):
    if not ip_address(addr).is_global: raise        # sin 10./192.168/169.254/127.
```

Bloquea IP privadas resolviendo DNS. **Nunca deberían** salir a Internet:
ninguno de los sensores, la Bodega, ni el core cognitivo — y no lo hacen. La
única entrada de URLs externas es la investigación web, que pasa por esta guarda.

**Residual (P3):** ventana TOCTOU / DNS-rebinding — `_assert_public_url` resuelve
el host para validar, y `urlopen` lo resuelve **otra vez** al conectar; un
dominio con TTL 0 apuntando primero a IP pública y luego a `169.254.169.254`
podría deslizarse. Mitigación: resolver una vez y conectar por IP, o pinar la IP
validada.

---

# HALLAZGO 6 · CI

**Estado: VERIFIED** — los workflows existen **y ejecutan de verdad** la suite
completa con cobertura. No es teatro.

**Riesgo: MEDIO** (por el rojo real, no por ausencia). **Prioridad: P2.**

### Qué corre de verdad

8 workflows. El principal, `ci.yml` (*Runtime Truth CI*), en `push` y
`pull_request`:

```yaml
- pytest -q --cov=triade --cov-report=xml     # suite completa + cobertura
- pytest -q tests/operational_truth
- python scripts/run_runtime_concurrency_test.py --tasks 30 --workers 2
- pytest tests/test_runtime_task_leases.py test_lease_fencing.py ...
- ruff check .  /  ruff format --check .
- mypy gate / pip-audit / detect-secrets
```

`concurrency-matrix.yml` corre la matriz py3.11×3 + py3.12×3.
`regression-gate.yml` y `measurement-core.yml` se restringen a `main`.

### Hallazgo real

`Runtime Truth CI` **está en rojo en `main`** ahora mismo (run 30735714262,
`python-truth` 3.11 y 3.12): 4 errores de `ruff` (`Found 4 errors`), imports
desordenados y un `RUF012`. Es decir: **el gate de lint lleva roto en la rama
principal**, lo que significa que los merges recientes entraron con el check en
rojo o el branch protection no lo exige. La rama de esta sesión
(`audit/education-timestamp-and-observation`, PR #66) ya lo deja en verde.

**Corrección:** hacer `ruff check .` y `ruff format --check .` bloqueantes en
branch protection de `main`; hoy se puede mergear con ellos rojos.

---

# HALLAZGO 7 · Dependencias

**Estado: VERIFIED** — el proyecto **no es reproducible**. No hay lockfile y
todo está en `>=`.

**Riesgo: MEDIO.** **Prioridad: P2.**

### Evidencia

```
lockfile (uv.lock/poetry.lock/requirements pineado) → NINGUNO
requirements.txt: 11 deps, TODAS con >=  (fastapi>=… peft>=… cryptography>=…)
pyproject.toml: mismas, >= en todas, requires-python>=3.11
torch: ni siquiera aparece pineado (llega transitivo por sentence-transformers)
```

Dos instalaciones en fechas distintas pueden traer versiones distintas de
`fastapi`, `pydantic`, `peft`, `torch`, `cryptography`. Para un sistema que se
automodifica y ejecuta código, un cambio silencioso de `cryptography` o `torch`
entre reinicios es un riesgo de estabilidad y de seguridad (una versión con CVE
entra sola).

**Corrección:** generar y commitear un lockfile (`uv lock` / `pip-compile`),
pinar exacto (`==`) en el runtime, y correr `pip-audit` contra el lock (ya está
instalado en CI pero audita el entorno resuelto, no un lock fijo).

---

# HALLAZGO 8 · Código muerto

**Estado: VERIFIED.** ~1.900 LOC del paquete `sandbox/` no se importan desde
ninguna ruta viva, incluida la clase de seguridad "completa".

**Riesgo: MEDIO** (confusión de seguridad). **Prioridad: P2.**

### Muerto confirmado (0 usos fuera de su propio fichero)

| Módulo | LOC | Nota |
|--------|-----|------|
| `sandbox/secure_executor_v2.py` | 442 | la clase "sandbox completo"; además **rota** (H1) |
| `sandbox/secure_executor.py` | 252 | tiene el único `setrlimit` real, sin usar |
| `sandbox/tool_registry.py` | 257 | 0 usos |
| `core/autonomous_sandbox.py::execute_code` | ~80 | `grep .execute_code(` → 0; solo `create_snapshot` se usa |

`sandbox/isolation.py` tiene **1 uso** — pero solo desde
`secure_executor.py`, que a su vez está muerto: es una isla muerta con dos
nodos. `enhanced_tool_registry.py` tiene 2 usos (`integration/final_validator`,
`dashboard/routes`).

### Clasificación

- **Experimental/aspiracional:** `secure_executor_v2.py` (T-013), `isolation.py`
  — describen aislamiento de SO que nunca se cableó.
- **Roto:** `secure_executor_v2.execute` (string a `shell=False`).
- **Huérfano:** `execute_code` de `autonomous_sandbox`.

### Impacto

No es peso muerto inocuo: son **1.400+ LOC con nombres como `SecureExecutor` y
docstrings que prometen rootless/seccomp/network-policy**. Una auditoría
apresurada (o el propio sistema razonando sobre sí mismo) puede creer que esa
protección existe. Borrarlos o marcarlos `# DEAD / aspirational` es una
corrección de seguridad, no de limpieza.

---

# HALLAZGO 9 · Aprendizaje

**Estado: PARTIAL** — el pipeline existe entero y las primeras transiciones
ocurren, pero la **transición final (a saber consolidado/verificado) casi no
sucede**: la cola se atasca en `internally_checked`.

**Riesgo: ALTO** (el sistema "aprende" pero casi nada cuaja). **Prioridad: P1.**

### Estado real de la cola (base viva, 2026-08-02)

```sql
learning_queue por status:
  internally_checked  662     ← atascados
  evidence_verified     2

learning_evidence por decision:
  improved    2
  pending     5
```

De **664 candidatos, 2** llegaron a `evidence_verified`. El pipeline diseñado es
`candidate → evaluated → internally_checked → validated_in_runs →
consolidated` (documentado en `neurons/education_cycle.py:206`), pero el 99,7 %
se queda en el penúltimo escalón antes de `validated_in_runs`.

### Transiciones, una por una

- **extracción** → funciona (662 candidatos existen).
- **deduplicación** → funciona (hay tarea dedicada `learning_candidate_dedup`).
- **evidencia** → funciona parcialmente: 2 `improved`, 5 `pending` sin cerrar.
- **validación en runs** → **es el cuello**: exige que la neurona se active en
  runs con `verification_reports`, y las neuronas educables no lo hacen (ver el
  corte 2/3 de `docs/LIVE_EDUCATION_OBSERVATION_20260802.md`).
- **rollback** → implementado y correcto (`education_resolver.py:199`,
  `governed_capability` con backup).
- **resolver / medición** → correcto y conservador; responde
  `insufficient_evidence` cuando no hay runs, que es lo honesto.

### Conclusión

Ninguna transición está **rota** en código; la de validación **no puede
dispararse** por falta de sujeto medible. Es el mismo diagnóstico de los tres
cortes de la educación neuronal, visto desde la cola: el circuito está completo,
pero la población que podría recorrerlo entera no existe todavía.

---

# HALLAZGO 10 · Mapa de arquitectura

Estado por componente, medido por: ¿se usa en runtime? ¿tiene tests? ¿la base
viva muestra actividad real?

| Componente | Archivo(s) | Madurez | Evidencia |
|------------|-----------|---------|-----------|
| **Central** (planeación/prompt) | `core/central.py` | **Maduro** | usado en cada chat; PlanGraph con estados |
| **Hipotálamo** (sensores) | `hypothalamus/senses.py` | **Maduro** (con bug corregido esta sesión) | regula carga; leía cola muerta hasta hoy |
| **Bodega** (memoria semántica) | `core/bodega.py` | **Maduro** | recall gobernado con filtro de seguridad |
| **Cristal** (Q-crystal/regulación) | `core/*crystal*` | **Experimental** | señales presentes, efecto difícil de medir |
| **Autonomía** (niveles/budget) | `constitution/autonomy.py`, `core/autonomy_budget.py` | **Maduro** | gating real por zona y acción |
| **Goal Engine** | `core/goal_orchestrator.py`, `planning_graph` | **Maduro** | plan → step → task con aprobación humana |
| **Capability Resolver** | `core/capability_resolver.py` | **Experimental** | regex sobre texto; frágil ante fraseo |
| **Worker / Scheduler** | `workers/worker_loop.py`, `runtime/task_leases.py` | **Maduro** | cola v2 con lease atómico, fencing, 1.497 tareas/24h |
| **Memory / Runtime** | `core/internal_runtime.py`, `services/supervisor.py` | **Maduro** | siempre-activo; 15 arranques/día observados |
| **Sandbox** | `sandbox/*` | **Prototipo** | vivo = 9 funciones puras; el resto muerto (H1, H8) |
| **Federación** | `federation/*` | **Experimental** | v2 con tablas sin poblar; observabilidad cerrada esta sesión |
| **Aprendizaje** | `learning/*`, `neurons/*` | **Experimental** | pipeline completo, transición final atascada (H9) |
| **Evolución/ingeniería** | `evolution/engineering_worker.py` | **Experimental** | corre pytest en worktree; disparado por governance |

**Resumen:** el **núcleo operativo** (runtime, workers, cola, memoria, goal
engine, autonomía) está **maduro y es real** — la base viva lo confirma con
tráfico. Las capas **cognitivas superiores** (cristal, aprendizaje que cuaja,
federación v2) y **toda la seguridad de ejecución de SO** son **experimentales o
prototipo**. El sistema es más sólido como orquestador gobernado que como
sandbox aislado.

---

# NUEVOS HALLAZGOS

## P0 · La API pública no está autenticada y la clave de escritura está vacía

**Estado: VERIFIED.** **Riesgo: CRÍTICO.**

`.env` de producción tiene `TRIADE_PUBLIC_GUARDED=false`, así que el middleware
de auth (`single_port_app.py:167-174`) **se salta entero**: cualquiera en
Internet llega a los endpoints. Verificado en vivo contra la URL pública:

```
POST /api/files/create        → 200  {"status":"blocked_budget"...}   (sin auth)
POST /api/system/safe-shell/run → 200  {"status":"error"...}          (sin auth)
```

El segundo cerrojo, para escrituras reales, es `require_key`
(`apps/routes/api.py:142`):

```python
def require_key(value):
    expected = os.getenv("TRIADE_API_KEY")
    if expected and value != expected:      # si expected es "" o None → no entra
        raise HTTPException(401, ...)
```

Y `TRIADE_API_KEY` está **vacía** en el `.env` y **ausente** en el proceso vivo
(verificado leyendo `/proc/<pid>/environ`). Con `expected` falsy, `require_key`
**no lanza nada**: fail-open. Reproducido:

```
clave ausente,  atacante no envía nada → PASA
clave vacía '', atacante no envía nada → PASA
```

**Cadena de explotación completa (no ejecutada contra el runtime real):**

1. Sin auth de sesión (`PUBLIC_GUARDED=false`).
2. `POST /api/files/patch` con `{"dry_run":false, "human_approved":true,
   "budget_level":"full_local_guarded", "path":"tests/test_zzz.py",
   "content":"<python>"}`. `human_approved` lo pone el atacante; `require_key`
   falla abierto; `tests/` es amarilla → **se escribe**.
3. `POST /api/system/safe-shell/run` con `{"command_key":"test_quick"}` →
   `pytest` colecta y ejecuta `tests/test_zzz.py` → **RCE**.

**Impacto:** ejecución remota de código, no autenticada, desde Internet, sobre
la máquina del runtime (L4 con la DB de producción y las claves de firma en
`.git/`).

**Corrección (P0, inmediata):**
- Poner `TRIADE_PUBLIC_GUARDED=true` **ya** en el `.env` de producción, o cortar
  la exposición pública del puerto 8010.
- Hacer `require_key` **fail-closed**: si `TRIADE_API_KEY` no está configurada,
  **denegar** las operaciones que la exigen, en vez de permitirlas.
- `human_approved` no puede ser un campo que el llamante se autoconcede; debe
  atarse a un token de aprobación emitido server-side.

## P1 · `authorized_root` viaja en el mismo payload que el target

**Estado: VERIFIED.** **Riesgo: ALTO.**

`GovernedFileWriteCapability` confina la escritura a `authorized_root`
(`runtime/governed_capability.py:98-101`), pero `_write_governed_text_artifact`
toma **tanto `target` como `authorized_root` del mismo `task.payload`**
(`worker_loop.py:1981-1983`). Quien controle el payload elige la jaula y el preso
a la vez: `{"target":"/etc/x","authorized_root":"/etc"}` pasa la comprobación.
La contención real depende, otra vez, de que solo el orquestador construya ese
payload — no de una raíz fijada por el sistema.

**Corrección:** `authorized_root` debe derivarse server-side de la zona/goal, no
aceptarse del payload.

## P1 · El Artículo VI de la constitución afirma límites que no se aplican

**Estado: VERIFIED.** **Riesgo: ALTO** (afirmación de seguridad falsa).

`constitution.py:75` declara, como artículo **inmutable y "critical"**:

> *"Ninguna ejecución usa shell=True. Todo pasa por sandboxes whitelistados con
> límites de CPU, RAM, PID y tiempo."*

La primera mitad es cierta (H3). La segunda **no**: la ruta viva de ejecución
(`safe_shell.run_autonomous` → `subprocess.run`) aplica **solo `timeout`**.
No hay `setrlimit` de CPU, RAM ni PID en ninguna ruta que se ejecute — el único
`setrlimit` real vive en `secure_executor.py`, que está muerto (H8). El sistema
afirma una garantía de contención de recursos que no tiene.

**Corrección:** o cablear `setrlimit` (RLIMIT_CPU/AS/NPROC) en la ruta viva vía
`preexec_fn`, o corregir el texto del artículo para que no afirme una protección
inexistente. Un sistema que se autogobierna leyendo su constitución no debe leer
una garantía falsa.

## P2 · `isolation.enforce()` es un no-op que reporta "enforced"

**Estado: VERIFIED.** **Riesgo: MEDIO.**

`sandbox/isolation.py:115-121`:

```python
def enforce(self, limits):
    violations = []          # nunca se rellena
    return {"status": "enforced" if not violations else ...}
```

Siempre devuelve `"enforced"` sin comprobar ni aplicar nada. Está en la isla
muerta (H8), así que hoy no engaña a nadie en runtime, pero es exactamente el
patrón de "seguridad que reporta éxito sin actuar" que esta auditoría busca.

**Corrección:** borrar con el resto de la isla muerta, o implementarlo de verdad
si se rescata el paquete.

---

# Cierre

El estado real de Tríade Ω: **un orquestador gobernado, maduro y honesto en su
núcleo** (runtime, cola, memoria, goal engine, con gating de autonomía y zonas
que sí se aplican), envuelto en una **capa de seguridad de ejecución que promete
aislamiento de sistema operativo que no existe** y con **una exposición pública
sin autenticar** que convierte la buena gobernanza interna en insuficiente frente
a Internet.

El sistema no miente sobre lo que hace su núcleo — la base viva confirma su
actividad. Miente (en docstrings y en un artículo constitucional) sobre el
aislamiento de su sandbox, y esa distancia entre lo declarado y lo real es,
junto al P0 de la API abierta, lo más urgente que arreglar.

Prioridad de acción: **P0 API** → **P1 zonas de `tests/`/core + authorized_root +
constitución** → **P2 borrar sandbox muerto + lockfile + branch protection**.
