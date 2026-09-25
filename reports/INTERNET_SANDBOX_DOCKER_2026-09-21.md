# Internet, umbral y sandbox de Tríade

## Alcance y estado

Verificación del 2026-09-21, UTC. Rama `main`, HEAD `9c1fd1187760e42335f58dbfa0bbe153fd52fc01`; tras `git fetch origin`, `git rev-list --left-right --count HEAD...origin/main` devolvió `0 0`. Se conservaron los cambios anteriores. No se hicieron commits, push ni escrituras diagnósticas en la base operativa.

El usuario confirmó que el umbral solicitado es **0,96 = 96%** y autorizó instalar Docker y las herramientas necesarias.

## Instalación observada

- Docker Desktop 4.91.0 instalado con `winget install --id Docker.DockerDesktop --exact --source winget --silent --accept-package-agreements --accept-source-agreements --disable-interactivity`.
- Microsoft WSL 2.7.13 instalado con el mismo procedimiento para `Microsoft.WSL`, elevado tras el rechazo inicial por falta de privilegios. Kernel 6.18.33.2-2; VirtualMachinePlatform observado `Enabled`; la instalación no requirió reiniciar Windows para arrancar Docker.
- `docker --host npipe:////./pipe/docker_engine info --format '{{.OSType}} {{.ServerVersion}}'`: `linux 29.8.0`. Docker Compose: `v5.5.1`.
- Imagen oficial `python:3.12-slim` descargada; ID fijado en `config/code_sandbox.json`: `sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9`. El ejecutor no descarga imágenes ni acepta etiquetas flotantes.
- Git, Node/npm, Ollama y las dependencias Python declaradas ya estaban instalados. `python -m pip check`: `No broken requirements found`. `npm.cmd ls --depth=0 --prefix frontend` sin dependencias faltantes. No se instalaron herramientas opcionales sin necesidad demostrada.

La instalación sigue la documentación de [Docker para Windows](https://docs.docker.com/desktop/setup/install/windows-install/) y [Microsoft WSL](https://learn.microsoft.com/windows/wsl/install). Los límites de ejecución utilizan las opciones documentadas de [Docker run](https://docs.docker.com/engine/containers/run/).

## Cambios de código

1. El gate compartido por planner y worker exige confianza finita >= 0,96; las variables de entorno pueden elevarlo, pero no rebajarlo. Rechaza NaN, infinito, booleanos y valores fuera de 0–1. Esto aprueba propuestas de investigación, no certifica estabilidad.
2. La extracción de resultados web admite distinto orden de atributos HTML, comillas y clases múltiples. Se valida cada redirección antes de contactar el destino; se limita también el número de fuentes de respaldo. El resultado identifica correctamente el respaldo curado/Wikipedia.
3. `DockerCodeSandbox` ejecuta Python exclusivamente en el motor local, sin red, como UID 65534, con filesystem de solo lectura, capacidades eliminadas y límites de memoria, CPU, procesos, almacenamiento temporal, salida y tiempo. El montaje contiene únicamente el archivo candidato, no el repositorio ni la base. El contenedor se elimina al terminar o fallar.
4. La especificación debe autorizar `training_policy="python_code"`. Factory, orquestador y worker aceptan `code_source`; guardan un recibo y exigen evaluación posterior. Una salida exitosa del código no prueba calidad: `quality_verified=false`. La comparación independiente puede enviar el candidato a cuarentena. No se implementó despliegue automático del código.

## Evidencia de verificación

- Suite proporcional: **76 pruebas pasaron**, incluyendo gate, investigación, fábrica, evaluación, orquestador y protecciones de workers/puerto. Después de añadir el caso de ejecución con regresión, **10 pruebas dirigidas pasaron**. Los conteos se solapan; no representan 86 pruebas diferentes.
- Ruff sin hallazgos en los archivos nuevos y modificados de esta etapa revisados.
- A las **21:15:51 UTC**, prueba real Docker: código ejecutado con UID 65534; escrituras en `/workspace/changed.txt` y `/root/changed.txt` rechazadas; conexión a `1.1.1.1:443` bloqueada; bucle infinito cancelado con presupuesto de 1 segundo. `docker ps -a --filter name=triade-code-` no mostró contenedores remanentes. Es diagnóstico explícito, no actividad autónoma ni evidencia de aprendizaje.
- A las **21:11:26 UTC**, `guarded_web_research(..., timeout=5, max_sources=2)` recuperó documentación de Python unittest y pytest. Resultado `ok`, proveedor `curated_and_wikipedia_fallback`, advertencia `primary_search_returned_no_results`. Hay conectividad real; no se ha demostrado una búsqueda general confiable para cualquier tema.

Evidencias locales: `artifacts/audit-20260921/install-wsl-result.json`, `install-wsl-admin.log`, `code-sandbox-live.json`, `after-docker-1.json`, `after-docker-2.json`.

## Estado efectivo y pendientes

El usuario autorizó después recargar exclusivamente la API. Se completó el reinicio a las 21:23 UTC, conservando su supervisor. La señal de cierre suave se rechazó porque la consola era compartida: enviarla habría afectado otros procesos. Se terminó únicamente la API cuya identidad, fecha de creación, padre y puerto habían sido verificados. No se modificaron manualmente colas, locks ni filas operativas.

La nueva API terminó startup y `/health` respondió 200. SQLite `PRAGMA quick_check` en conexión de solo lectura devolvió `ok`. Entre **21:23:47 y 21:25:02 UTC**, el heartbeat del nuevo proceso avanzó de 21:23:39 a 21:24:45 y el metabolismo de 1805 a 1809 completados (1810 estaba en curso). Ollama seguía accesible. Los endpoints protegidos continuaron devolviendo 403.

El watchdog registró `workers_thread_dead` y reintentos. La causa comprobada de que no abra un nuevo worker run es `recover_orphaned_tasks`: devuelve `live_lease` mientras hay reservas no vencidas. Las tareas antiguas `system_debt_scan` y `pulse_check` conservaban reservas hasta **21:31:15 y 21:39:07 UTC** (16:31 y 16:39 Colombia). No se forzó su vencimiento. La recuperación completa de workers queda pendiente de observar después de esas reservas.

Durante el arranque, la recuperación propia del sistema reconcilió 16 resultados inciertos: el total de completadas pasó de 106 a 121 y dead letters de 192 a 193. **Esto es reconciliación de resultados previos, no 15 trabajos nuevos ejecutados tras el reinicio.** La RAM disponible tras reiniciar seguía en 0,43–0,73 GB. Qualia/Cristal no avanzaron en estas dos observaciones.

Pruebas reales adicionales a las **21:20:22 UTC**: un programa con salida 7 fue rechazado y otro que excedía 64 KiB de salida también fue rechazado. Evidencia: `code-sandbox-failures-live.json`. Recarga: `code-reload-result.json`, `code-reload-signal.log`, `code-reload-finish.json`, `after-code-reload-1.json`, `after-code-reload-2.json`.

Observaciones anteriores a la recarga, a las **21:16:09 y 21:18:20 UTC**:

- Mismo PID API/heartbeat; heartbeat actualizado de 21:16:04 a 21:18:18. El contador se mantiene en 1, por el problema de múltiples escritores ya documentado.
- Metabolismo avanzó del ciclo **1779 al 1787**, ambos completados. `/health` respondió 200 y Ollama fue accesible en ambas observaciones.
- Cola: 106 completadas, 16 `completion_uncertain`, 192 `dead_letter`, 2 pendientes y 2 en ejecución, sin incremento de completadas entre esas observaciones. Un registro worker `running` por sí solo no certifica que finalice trabajo correctamente.
- Qualia quedó en 275 experiencias; Cristal último ID 43, `q_crystal=0.444`, de 21:09:20 UTC. Sin nuevos registros entre las dos observaciones. Ese score no es la confianza del gate de propuestas.
- RAM disponible observada: **0,39–0,49 GB de 7,21 GB**. Continúan pausas por recursos. Docker no elimina esta degradación.
- Liveness, salud profunda, Always-On, workers y heartbeat HTTP devolvieron **403** por autenticación; no se atribuye salud completa a endpoints que no pudieron inspeccionarse.

Pendientes importantes: búsqueda general cuando el proveedor primario no responde; atribución causal y métricas calibradas para promoción estable al 96%; recuperación de resultados inciertos sin duplicar efectos; presión de RAM; contador heartbeat; verificar arranque desatendido. El canary actual declara correlación temporal y el verificador usa varias puntuaciones heurísticas fijas. No se elevaron artificialmente esas puntuaciones ni se promovieron neuronas para aparentar el 96%.

La promoción estable conserva su gate independiente existente. No debe confundirse esta entrega con estabilidad automática al 96% ya demostrada.
