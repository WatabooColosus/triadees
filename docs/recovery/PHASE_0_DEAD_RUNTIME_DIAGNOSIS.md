# FASE 0 — Diagnóstico del runtime conversacional muerto

Fecha UTC: 2026-08-06

## Veredicto

**Tríade no queda declarada conversacionalmente viva.** Una petición API aislada
logró recorrer Runner, Hipotálamo, Central, Ollama y Bodega y devolvió
`TRIADA_VIVA`, pero la interfaz real no pudo cargar durante la reproducción del
fallo. El proceso seguía escuchando en 8010 y había publicado salud HTTP 200;
ninguno de esos hechos evitó la indisponibilidad conversacional.

## Punto principal de ruptura

El punto principal está entre **frontend/transporte y la admisión de trabajo por
la API**: el único proceso Uvicorn agota su pool AnyIO con reconstrucciones
concurrentes de deuda disparadas por `GET /api/internal-graphs/debt` y por ciclos
internos. En el muestreo del proceso 12717, los 40 threads AnyIO estaban dentro
de `build_debt_report()` → `build_alias_debt()` → `find_dead_status_values()` →
`iter_python_files()` → `Path.rglob()`. Había además un ciclo continuo y el
worker always-on ejecutando el mismo escaneo. Con el pool ocupado, `/`, el JS y
el CSS dieron 0 bytes y timeout a 10 s; Chromium no alcanzó ni
`DOMContentLoaded` en 30 s. Por tanto el usuario no puede llegar de forma
fiable al endpoint de conversación aunque el socket y el heartbeat existan.

## Fallas secundarias

1. `POST /api/run` tardó 32.156 s aun con Ollama caliente; la inferencia directa
   equivalente en Ollama tardó 0.571 s. El coste dominante está en el runtime,
   recuperación/enriquecimiento, ciclos posteriores y serialización.
2. La respuesta de chat fue de 3,298,090 bytes para el texto visible de 11 bytes.
   Incluye snapshots y trazas internas masivas que la SPA no necesita para
   mostrar la respuesta. Los artefactos del run también muestran amplificación:
   `input.json` 1,944,072 bytes, `output.json` 1,496,097 bytes,
   `memory_diff.json` 1,435,568 bytes y `triadic_cycle_trace.json` 3,607,905 bytes.
3. `X-Request-ID` no se devuelve ni se registra en el access log. El identificador
   enviado solo sobrevivió porque se duplicó manualmente dentro de
   `context.request_id`; no existe correlación uniforme frontend → API → Runner →
   Central → router → Ollama → respuesta → Bodega.
4. Los logs HTTP solo contienen `POST /api/run 200 OK`; los logs Ollama contienen
   llamadas `/api/generate` sin `request_id`. No permiten unir por sí solos ambos
   lados del recorrido.
5. El endpoint devuelve metadatos de modelo dentro de estructuras anidadas, pero
   no mantiene un contrato compacto y estable de traza para el cliente.
6. El polling de la SPA (`/api/safety/pending` cada 5 s y otros paneles) aumenta
   presión y conexiones. El endpoint de deuda hace trabajo CPU/FS caro por cada
   lectura concurrente.

## Contrato real descubierto

- Entrypoint oficial: `python triade_digimon.py api --host 127.0.0.1 --port 8010`.
- Aplicación real: `apps.single_port_app:app`.
- Frontend: React SPA compilada en `frontend/dist/`, servida por
  `apps/routes/ui.py` en `/`; JS `/assets/index-Cx18hFb_.js`; CSS
  `/assets/index-GW-I3jgM.css`.
- Chat: same-origin HTTP, sin WebSocket ni streaming; `POST /api/run`.
- Payload: `text`, `source`, `use_ollama`, modelos opcionales,
  `auto_select_models`, `conversation_history` y opciones semánticas.
- Headers: `Content-Type: application/json`; `X-TRIADE-API-Key` solo si está
  configurada. En la prueba local no se requirió autenticación. No se necesita
  CORS al ser same-origin y no se encontró middleware CORS.
- Receptor: `apps.routes.api.run_triade()`.
- Runtime: `TriadeRunner.run()`.
- Hipotálamo: `triade.core.hypothalamus.Hypothalamus`.
- Central: `triade.core.central.CentralNeuron`; Central no es el modelo.
- Router: `triade.models.model_router.ModelRouter`.
- Proveedor cognitivo observado: `ollama`, modelo local exacto
  `qwen2.5:3b-instruct`; embeddings `nomic-embed-text:latest`.
- Persistencia observada: episodio 281, señal 282 y cristal 281 en
  `triade/memory/triade.db`, más artefactos en
  `runs/run-20260806-002401-34bfaa1c`.
- Respuesta visible prevista por la SPA: campo JSON `response`.

## Evidencia de ejecución

| Prueba | Resultado |
| --- | --- |
| `GET /health/live` | 200, `status=alive` al inicio |
| `GET /health/ready` | 200, memoria y runs escribibles |
| `GET /` | 200, `text/html`, SPA y assets declarados al inicio |
| `POST /api/run` | 200 en 32.156 s, 3,298,090 bytes |
| respuesta API | `TRIADA_VIVA` |
| Hipotálamo | Ollama `qwen2.5:3b-instruct`, `ok=true` en el run |
| Central | Ollama `qwen2.5:3b-instruct`, `ok=true` en el run |
| Bodega | `stored=true`, episodio 281 |
| Ollama directo | `TRIADA_VIVA`, `done=true`, 0.571 s |
| repetición `GET /`, JS, CSS | timeout 10 s, 0 bytes |
| Chromium | timeout 30 s antes de `DOMContentLoaded`; sin estado final |
| proceso 8010 | 53 threads, RSS 1,190,904 KiB, pool AnyIO saturado |

Que una petición aislada haya tenido éxito no satisface el cierre de FASE 1:
la interfaz no mostró la respuesta en la reproducción y no existe un test E2E
real estable.

## Gate local previo al PR

- `python -m compileall -q triade apps scripts tests`: pasa.
- `ruff check .`: falla por deuda preexistente, 697 `EXE002` (archivos Python
  marcados ejecutables sin shebang); este PR no cambia esos permisos.
- `ruff format --check .`: pasa, 960 archivos formateados.
- `mypy triade`: pasa, 341 archivos sin errores.
- `pytest -q`: bloqueado al 3 % en `tests/test_api_app.py::test_triade_run_endpoint`.
  El volcado de pila mostró `TriadeRunner` → `EdgeRouter` →
  `get_resource_lease()` leyendo por HTTP del mismo 8010 saturado. Se interrumpió
  solo el pytest iniciado para el diagnóstico; no se alteró el proceso 8010.

El gate completo no está verde y no se presenta como tal. Estos resultados
refuerzan `DO_NOT_MERGE` como recuperación funcional.

## Modelo local

Ollama 0.32.5 estaba disponible en `127.0.0.1:11434`. Se observaron seis modelos
instalados. `ollama ps` mostró `qwen2.5:3b-instruct` y
`nomic-embed-text:latest` cargados al 100 % en GPU. La llamada directa a
`qwen2.5:3b-instruct` devolvió exactamente `TRIADA_VIVA`. No se observó un
proveedor remoto en el recorrido ejecutado; `triade.yml` configura `ollama`.

## Errores de navegador y servidor

- Navegador: timeout de navegación de 30 s; al no recibirse el documento no hubo
  consola de aplicación ni petición `/api/run` desde la SPA.
- Servidor: no hubo traceback correlacionado. El access log muestra una gran
  frecuencia de polling y muchas conexiones establecidas. El volcado `py-spy`
  demuestra contención en escaneos de deuda, evidencia que no aparece como error
  en los logs.

## Git: contraste local/remoto

- `local_sha` inicial: `9d1c7273d8b4be7deee7c9c1e909cb60be6c6417`
- `remote_main_sha` inicial: `9d1c7273d8b4be7deee7c9c1e909cb60be6c6417`
- SHA base usado: `9d1c7273d8b4be7deee7c9c1e909cb60be6c6417`
- rama inicial: `main`
- rama de trabajo: `fix/revive-triade-runtime`
- ahead/behind inicial: `0/0`
- working tree inicial: limpio
- archivos modificados iniciales: ninguno
- archivos no rastreados iniciales: ninguno
- diff inicial `origin/main...HEAD`: vacío
- remoto: `origin` = `https://github.com/WatabooColosus/triadees.git`

El commit, SHA final, diff final, estado remoto y PR se registrarán al publicar
esta fase.

## Alcance y recomendación

Esta fase solo añade diagnóstico y evidencia; no modifica código funcional, no
reinicia procesos y no avanza a Bodega, anatomía, modelos, aprendizaje ni Unidad
01. Recomendación: **DO_NOT_MERGE como recuperación**. El PR de FASE 0 puede
integrarse únicamente como evidencia diagnóstica; FASE 1 debe corregir primero
la saturación del pool, limitar/cachar el endpoint de deuda, compactar el contrato
de chat y propagar `request_id`, y después demostrar navegador → respuesta.

## Riesgos y rollback

- Riesgo de esta fase: bajo; solo documentación y un artefacto JSON.
- Estado operativo no recuperado: el proceso 8010 continúa degradado/saturado.
- Rollback del commit: `git revert <sha-del-commit-de-fase-0>`; no borrar los
  runs ni la base viva usados como evidencia.
