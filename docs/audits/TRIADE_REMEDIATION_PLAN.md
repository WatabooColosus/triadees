# TRIADE_REMEDIATION_PLAN.md — Ruta de corrección ordenada, mínima y verificable

**SHA base:** `e3cba75` · **Fecha:** 2026-07-31
**Origen:** hallazgos de `TRIADE_GAPS_AND_RISKS.md` (2×P0, 5×P1, 10×P2, 1×P3),
todos con evidencia de archivo:línea y datos de la DB real.

**Este documento es un plan. No se ha ejecutado ninguna corrección.**

---

## 0. Principios que sigue este plan

1. **Mínimo:** cada arreglo toca lo menos posible. Se rechaza explícitamente
   cualquier refactor grande (ver §5).
2. **Verificable:** cada punto trae un comando o consulta concreta que demuestra
   el antes y el después.
3. **Sin motores nuevos:** no se añade ningún scheduler, store, cola ni sistema
   paralelo, conforme a la regla del encargo.
4. **Separación crítica:** se distingue entre *corrección de defecto* (arreglar
   algo que miente o se pierde) y *expansión de autonomía* (hacer que el sistema
   haga más cosas solo). **Lo segundo no es una decisión de auditoría.** Ver §3.

---

## 1. Bloque A — Correcciones seguras y mecánicas (recomendadas ya)

Ninguna cambia lo que el sistema *decide*; solo hacen que deje de perder datos o
de afirmar cosas falsas.

### A1 · P1-04 — Garantizar WAL desde el código
**Prioridad 1. Es el de mayor relación beneficio/riesgo de todo el plan.**

**Problema:** la DB de producción está en `journal_mode=wal`, pero **ningún código
lo establece**; se activó a mano. Un despliegue nuevo, un restore a fichero nuevo o
CI arrancarían en `journal_mode=delete`, con bloqueos bajo la concurrencia real.

**Dato que condiciona la solución [E]:** hay **286 llamadas directas a
`sqlite3.connect()`** en `triade/` + `apps/` y **no existe un helper central de
conexión**. Cada módulo aplica su propia migración con `executescript`.

**Por tanto, el arreglo mínimo NO es centralizar conexiones** (sería un refactor de
286 sitios). Como `journal_mode=WAL` es una **propiedad persistente del fichero**,
basta ejecutarlo **una vez, temprano y de forma idempotente**:

- Lugar propuesto: `apps/single_port_app.py`, en el `lifespan`, **antes** de la
  verificación de identidad (`:41`), y en `scripts/runtime_workers.py` antes de
  arrancar el servicio (para el caso de que los workers creen la DB primero).
- Cambio: abrir la conexión y ejecutar `PRAGMA journal_mode=WAL;`.

**Verificación:**
```bash
# antes/después, sobre una copia limpia:
python3 -c "import sqlite3;print(sqlite3.connect('<db>').execute('PRAGMA journal_mode').fetchone())"
# debe devolver ('wal',) en una DB recién creada por el arranque
```
**Riesgo:** muy bajo. `PRAGMA journal_mode=WAL` es idempotente y no destructivo.

---

### A2 · P1-01 — Que el watchdog deje de declarar éxitos no verificados

**Problema:** `runtime_recovery.py:60` hace
`heartbeat_ok = verify_heartbeat() if verify_heartbeat else True` → en producción
siempre `True`, y `:64` marca `runtime_recovered`. Resultado real: **510 falsos
éxitos** en `runtime_recovery_events`.

**Arreglo mínimo (dos partes, ambas pequeñas):**

1. En `scripts/runtime_watchdog.py:19`, pasar un `verify_heartbeat` real. Ya existe
   la pieza necesaria: `LiveHeartbeat.snapshot()` (`triade/runtime/live_heartbeat.py:73`).
   El callable debe comprobar que el timestamp del heartbeat **avanzó** respecto al
   momento previo a la recuperación.
2. En `runtime_recovery.py:60`, cambiar el valor por defecto: si **no** hay
   verificador, el estado final **no debe ser `runtime_recovered`** sino
   `unverified`. Un watchdog no debe poder declarar éxito sin comprobarlo.

**Verificación:**
```sql
-- tras el cambio, las nuevas filas deben distinguir:
SELECT state, COUNT(*) FROM runtime_recovery_events
 WHERE created_at > '<fecha del cambio>' GROUP BY state;
-- esperado: 'runtime_recovered' solo si el heartbeat avanzó de verdad
```
**Riesgo:** bajo. Hace el sistema **más** estricto, no más permisivo.

---

### A3 · P1-03 — Rescatar las 93 necesidades metabólicas huérfanas

**Problema:** `metabolism/recovery.py:16-23` solo escanea ciclos
`WHERE status IN ('running','starting') AND finished_at IS NULL`. Las needs de
ciclos ya cerrados (`failed`/`completed`) nunca se recuperan. Hay **93 atascadas**
desde el 30-jul.

**Arreglo mínimo:** al cerrar un ciclo (a `completed` o `failed`), reconciliar en
**la misma transacción** sus needs no terminales → `recovered`. Es un `UPDATE`
adicional en el cierre, no un barrido nuevo ni un proceso nuevo.

**Migración de datos existentes:** las 93 actuales necesitan un `UPDATE` puntual.
**No ejecutar sobre producción sin backup** (existe backup cifrado diario).

**Verificación:**
```sql
SELECT status, COUNT(*) FROM metabolic_needs
 WHERE status IN ('running','pending')
   AND cycle_id IN (SELECT cycle_id FROM metabolic_cycle WHERE finished_at IS NOT NULL);
-- debe ser 0 tras el arreglo
```
**Riesgo:** bajo, pero toca datos. Requiere backup previo verificado.

---

### A4 · P2-01 — Que el endpoint de workers no reporte un hilo muerto como vivo

**Problema:** `worker_autostart.py:219`
`raw_active = bool(thread_alive or service_status.get("running"))` mezcla "este
hilo" con "el dueño del lock, que es otro proceso" → informa `status=running` con
`thread_alive=False`.

**Arreglo mínimo:** separar los dos conceptos en la respuesta, sin cambiar la
lógica de arranque:
- `thread_alive` → este proceso (ya existe).
- `workers_running_elsewhere` → dueño del lock.
- `status` debe reflejar el hilo local; el hecho global va en un campo aparte.

**Verificación:** `GET /api/runtime/workers-always-on/status` no debe poder
devolver `status=running` con `thread_alive=false`.
**Riesgo:** muy bajo (solo presentación). **Nota:** ajustar el frontend si consume
`status`.

---

### A5 · P2-08 — `CHECK` sobre `autonomous_tasks.status`

**Problema:** el vocabulario de estados no está restringido; un typo crearía un
estado inválido invisible para los barridos de recuperación.

**Arreglo:** migración aditiva nueva que recree la tabla con
`CHECK (status IN (...))` con la lista real verificada.
**Advertencia [I]:** SQLite no permite añadir `CHECK` con `ALTER TABLE`; exige
recrear la tabla y copiar datos. **Deja de ser "mínimo".** Alternativa más barata y
casi tan efectiva: validar en el borde de escritura (`AutonomousTaskStore`) contra
una constante `VALID_STATUSES`.

**Recomendación:** hacer la validación en código, **no** la migración.
**Riesgo:** bajo en la opción de código; medio-alto en la de migración.

---

### A6 · P2-10 — Retención para las tablas Qualia

**Problema:** ~10.800 filas acumuladas, sin `DELETE`/retención, y solo se releen
las 20 más recientes.

**Arreglo mínimo:** política de retención por antigüedad o por número de filas,
ejecutada por una necesidad metabólica ya existente **o** por el worker de
mantenimiento. **No crear un proceso nuevo.**

**Decisión previa necesaria:** ¿se conserva el histórico como archivo (entonces no
es un bug, solo hay que documentarlo) o se poda? Es una decisión de producto.

**Riesgo:** medio — borra datos. Requiere decisión explícita + backup.

---

## 2. Bloque B — Corrección de honestidad de estado (recomendada, decisión ligera)

### B1 · P0-01 — El LoRA "active" que no sirve tráfico

**Problema:** `peft_serving_state` dice `slot=production, status=active`, pero
**ningún componente de la ruta de inferencia lee ese slot**; las conversaciones
salen a Ollama, que no recibe adaptador.

**El arreglo real (cerrar el ciclo) es grande** y hay dos vías, ambas fuera de
"mínimo":
1. Fusionar el adaptador y registrarlo como modelo Ollama (`ollama create`), y que
   el router lo seleccione por nombre.
2. Mover la inferencia de producción al motor PEFT en proceso.

**Arreglo mínimo e inmediato (lo que sí recomiendo ahora): dejar de mentir.**
Introducir un estado intermedio explícito, p. ej. `approved_not_served`, y **no
permitir** `active` mientras no exista una ruta real de servicio. Añadir al
endpoint de estado un campo `served_by_inference: false` con su motivo.

**Verificación:** `GET /api/governance/peft/status` debe reflejar que el adaptador
está aprobado pero **no servido**, y ningún panel debe poder mostrar "activo en
producción".

**Riesgo:** bajo. No toca pesos, no activa nada, no desactiva nada.
**Cumple la regla 10 del encargo ("no actives LoRA").**

---

## 3. Bloque C — NO es una corrección: es una decisión tuya

### C1 · P0-02 — Conectar el evaluador que cerraría el ciclo educativo

**Hecho verificado:** la evidencia de aprendizaje queda en `decision='pending'`
para siempre porque su único evaluador (`NeuronEvaluationCoordinator` →
`SelfImprovementOrchestrator`) **solo lo invocan los tests**.

**Podría "arreglarse" en pocas líneas**: invocar el orquestador desde un task type
del ciclo 24/7. **No lo recomiendo como corrección automática, y no lo haría sin
que lo decidas explícitamente.** Razón:

Eso no repara un defecto: **enciende el bucle de automejora**. Haría que Tríade
evalúe sus propias lecciones, decida que mejoró, y promueva neuronas — de forma
autónoma y continua. Es exactamente el tipo de cambio que merece una decisión
deliberada tuya, no un `commit` de auditoría.

**Preguntas que hay que responder antes de conectarlo:**
1. ¿Qué umbral de evidencia exige promover una neurona, y quién lo fija?
2. ¿Hay rollback verificado si una promoción degrada el sistema?
   (`regression_reports` y `regression_quarantine` están **vacías** — el sistema
   de regresión existe pero nunca ha corrido.)
3. ¿El evaluador es independiente de lo evaluado, o el sistema se califica a sí
   mismo? (`evaluation_role: "independent_required"` aparece en el contrato de la
   lección, pero **[NV]** no se verificó que se cumpla.)

**Recomendación:** antes de conectar C1, ejecutar A1–A4 y **activar de verdad el
sistema de regresión**, para que exista red de seguridad medible. Conectar la
automejora sin regresión verificada es el escenario de riesgo más alto de todo el
sistema.

---

## 4. Orden de ejecución propuesto

```
1. A1  WAL garantizado           ← primero: protege todo lo demás
2. A2  Watchdog honesto          ← deja de enmascarar problemas reales
3. A3  Needs huérfanas           ← con backup previo
4. A4  Endpoint de workers       ← presentación
5. B1  LoRA: estado honesto      ← quita una afirmación falsa
6. A5  Validación de estados     ← en código, no migración
7. A6  Retención Qualia          ← requiere decisión de producto
   ─────────────────────────────
8. C1  SOLO tras decisión humana explícita + regresión activa
```

**Regla de verificación transversal:** tras cada punto, `pytest -q` completo debe
seguir en verde (la suite completa pasó en esta sesión, exit 0) y los 4 servicios
systemd deben seguir activos con `/api/health` 200.

---

## 5. Lo que este plan rechaza explícitamente

- **Centralizar las 286 conexiones SQLite** en un helper: correcto a largo plazo,
  pero desproporcionado como remediación. A1 logra el objetivo real sin tocarlas.
- **Recrear `autonomous_tasks`** para añadir `CHECK`: riesgo desproporcionado
  (ver A5).
- **Implementar las 6 necesidades metabólicas inertes** (`memory_maintenance`,
  `contradiction_detection`, etc.): son funcionalidad nueva, no deuda. Deben
  decidirse por valor, no "porque están en un diccionario".
- **Conectar `GovernedPlanDispatcher`, `neuron_factory` o los sandboxes no usados**:
  todos están probados pero sin caller de producción. Conectarlos es diseño, no
  reparación.
- **Cualquier acción sobre `identity_core`**: está correctamente protegido; no se
  toca.

---

## 6. Lo que este plan NO cubre [NV]

Fases 10 y 13–16 del encargo siguen sin auditar (Model Router en detalle, matriz
completa de conexiones, pruebas E2E de coherencia contextual, censo exhaustivo de
excepciones silenciosas). **Pueden aparecer riesgos nuevos que cambien este orden.**
