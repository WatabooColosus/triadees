# Certificación del runtime completo

Fecha: 2026-08-07
Rama: `fix/revive-triade-phase1`

Qué se exigía: que **frontend + backend + runtime de Tríade** funcionen a la vez
detrás de la URL real, con el organismo encendido. No que la suite pase, ni que
el puerto esté abierto, ni que Ollama conteste por su cuenta.

## Fuente única de verdad

Está en [`STATUS_CURRENT.md`](../../STATUS_CURRENT.md#2--cómo-se-levanta) y se
resume en un comando: `scripts/triade_runtime.sh up`. Entrypoint
`apps.single_port_app:app`, host `0.0.0.0`, puerto `8010`, chat en `/api/run`,
frontend servido desde `frontend/dist/` por la misma app.

## Los dos defectos que impedían certificar

### 1 · Un endpoint de salud que ejecutaba trabajo real

`/health/deep` y `/api/runtime/heartbeat` no respondían: más de 120 s sin
devolver nada, con el resto de la app viva. `py-spy` sobre el proceso señaló
`supervisor.py:528`, dentro de `_build_services_snapshot`:

```python
"next_plan_preview": [
    item.to_dict()
    for item in MissionPlanner(db_path=self.db_path).plan_cycle(...)[:5]
],
```

El snapshot **ejecutaba un ciclo completo de planificación de misiones** para
pintar una previsualización. `plan_cycle()` cuesta 13,4 s medidos en reposo, de
los cuales 8,6 s son `_debt_snapshot()` → `build_alias_debt()` → un escaneo del
AST de los 737 ficheros Python del repositorio. Con el organismo encendido había
tres hilos haciendo ese mismo escaneo a la vez —el worker `mission_planner`, la
ruta `/api/internal-graphs/debt` y el dashboard—, peleando por el GIL.

Además el plan devuelto **no era el que se iba a ejecutar**: con el worker
activo, `_mission_service` se delega (`status: delegated`) y quien planifica de
verdad es `WorkerScheduler`, que encola en `autonomous_tasks`.

Arreglado en `_next_plan_preview()`: se lee la cabeza de la cola viva
(`autonomous_tasks` pendientes por prioridad), que es la respuesta veraz a "qué
viene ahora", y se declara la procedencia en `next_plan_source`. Si no hay cola
—porque planifica el propio supervisor— cae a `last_planned_tasks`, que ahora
`_mission_service` guarda con su marca de tiempo. Planificar sigue ocurriendo en
el worker; lo que deja de ocurrir es planificar dentro de una petición HTTP.

| | antes | después |
|---|---|---|
| `/health/deep` | sin respuesta a los 120 s | 4,8 s |
| `/api/runtime/heartbeat` | sin respuesta a los 120 s | 5,0 s |

### 2 · El modo reducido no existía, pero la documentación lo daba por hecho

`triade.yml` declaraba `runtime.conversation_only: true`, y
`docs/recovery/PHASE_1_MINIMAL_CONVERSATION.md` afirmaba que durante esa fase no
se arrancaban workers, runner continuo ni metabolismo.

Nunca fue verdad. `load_always_on_config()` copia de `triade.yml` **sólo las
claves presentes en `YML_DEFAULTS`**, y `conversation_only` no estaba:

```python
conversation_only = bool(load_always_on_config().get("conversation_only", False))
```

leía `False` siempre. El gate de `single_port_app.py` era código muerto y el
runtime llevaba semanas arrancando completo mientras el repositorio afirmaba lo
contrario. El cuelgue del punto 1 ocurría, por tanto, en modo full: la reducción
que supuestamente lo evitaba no estaba aplicada.

Corregido añadiendo `conversation_only` a `YML_DEFAULTS`. La bandera es ahora
real —y por eso comprobable—, y queda en `false`: la certificación exige el
organismo entero.

### Reducciones retiradas

- `triade.yml`: `conversation_only` a `false`.
- `frontend/src/App.tsx`: la SPA forzaba `semantic_recall_enabled: false` en cada
  mensaje. Retirado; se usa el contrato por defecto (recall gobernado activo).
- `tests/test_chat_end_to_end_real.py`: la prueba fijaba `semantic_recall_enabled`
  en `False`, es decir, certificaba una ruta que ningún usuario recorre.

## Evidencia

Runtime levantado con `scripts/triade_runtime.sh up`, modo `full_local_guarded`.

### URL, frontend y bundle

```text
GET /                          200  text/html   373 b   0,03 s
GET /assets/index-Cx18hFb_.js  200  260 210 b
GET /assets/index-GW-I3jgM.css 200    1 542 b
```

El bundle servido es el build actual, no un artefacto viejo: `npm ci && npm run
build` reproduce el mismo hash y `md5sum` del fichero servido coincide con el de
`frontend/dist/` (`d9e3916b7c745a37af929920fd23a1d0`).

### Navegador real (Puppeteer, Chrome headless)

```text
http_status 200 · carga 803 ms · React montado · CSS aplicado
pantalla en blanco: no · errores de página: 0 · peticiones fallidas: 0
3 conversaciones seguidas: respuesta visible en pantalla en las 3
interfaz sigue aceptando entrada después
```

El único 404 de consola era `/favicon.ico`; corregido con un favicon embebido en
`frontend/index.html`.

### Chat end-to-end

```text
POST /api/run  ·  200  ·  15,5 s
response  : TRIADA_VIVA
run_id    : run-20260807-204338-d92c4587
central   : ollama / qwen2.5:3b-instruct / ok: true
hipotálamo: ollama / qwen2.5:3b-instruct / ok: true
Bodega    : episode_id 292 en triade/memory/triade.db
cristal 292 · señal 293 · tarea de aprendizaje encolada
proveedor externo: ninguno
```

### Órganos activos a la vez

```text
mode                full_local_guarded      metabolismo    running, modo full, 20 ciclos
workers_active      true                    LIFE_PULSE     running
always_on           running, hilo vivo      runner continuo running, 1 ciclo/min
ollama_health       ok, 6/6 modelos         Bodega         ok
degraded_components []                      worker_loop    ok
```

### Estabilidad con el organismo trabajando

```text
10 × /health          10/10 · 200 · 0,60-0,91 s
5 conversaciones      5/5 · 200 · 12,8-16,9 s · episodios 296-300
URL durante cada una  / = 200 · /health/live = 200
hilos                 18 → 18 (sin fuga)
listeners en 8010     1 (sin instancia duplicada)
cola autonomous_tasks se procesa: +8 completadas en 120 s
SQLite                WAL · lock de escritura adquirido en 0,00 s
```

## Prueba automatizada

`tests/test_chat_end_to_end_real.py`, en dos niveles:

- `TRIADE_REAL_E2E=1` — circuito conversacional (`/`, bundle, `/api/run`,
  Central, Ollama local, persistencia en Bodega).
- `TRIADE_FULL_CERT=1` — certificación full: falla si `conversation_only` está
  activo, si workers, LIFE_PULSE o metabolismo no corren, o si Ollama, la API o
  el frontend no son accesibles.

```bash
./scripts/triade_runtime.sh up
TRIADE_REAL_E2E=1 TRIADE_FULL_CERT=1 pytest -q tests/test_chat_end_to_end_real.py
```

El gate se comprobó por ambos lados. Con `conversation_only: true` y la bandera
ya viva, la certificación **falla** en tres pruebas (modo reducido, órganos
apagados, metabolismo apagado) mientras la prueba conversacional sigue pasando
—que es exactamente por qué un runtime recortado podía pasar por completo—. Con
`false`, las cinco pasan.

Para que la certificación pueda ver el modo de arranque desde fuera del proceso,
`/health/deep` publica ahora `runtime_mode`: hasta ahora `conversation_only` no
era observable por HTTP.

## Límite

Lo medido es este Studio (L4 24 GB, 8 CPU, 31 GB RAM) con los 6 modelos locales.
`/health/deep` y el heartbeat tardan ~5 s con el organismo encendido frente a
~3 s en reposo: es contención real del proceso completo, no un cuelgue. Las
rutas rápidas (`/`, `/health/live`, `/health/ready`) responden por debajo de
50 ms.

Pendiente, detectado y no reparado aquí: el proceso no cierra limpio con SIGTERM
en modo full (libera el puerto, pero los hilos de fondo siguen vivos >30 s y hay
que rematar con SIGKILL).
