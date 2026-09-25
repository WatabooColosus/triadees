# Recarga autorizada y puerto exclusivo

Rama main; HEAD 9c1fd1187760e42335f58dbfa0bbe153fd52fc01; fetch origin
y comparación HEAD...origin/main: 0/0. Se preservan los cambios anteriores.

El primer intento abortó sin detener procesos: la identidad del listener había
cambiado. Se correlacionaron dos APIs: PID 17676, padre 26536, inicio
21:23:12 UTC; PID 28200, padre 17320, inicio 21:49:34 UTC. Los dos padres
ejecutaban scripts/triade_service_worker.ps1. El heartbeat alternaba de PID.

La implementación instalada de uvicorn.Config.bind_socket usa SO_REUSEADDR.
En Windows esto permite compartir forzosamente un puerto. El lanzador ahora
usa SO_EXCLUSIVEADDRUSE antes de bind en Windows, antes de importar la app.
Fuente: https://learn.microsoft.com/en-us/windows/win32/winsock/so-exclusiveaddruse
No cambia la ruta POSIX. Cuatro pruebas pasaron, incluyendo colisión con un
socket que usa SO_REUSEADDR; Ruff pasó.

El usuario autorizó la recarga. Tras validar PID, fecha de creación, comando,
padres y listener, se detuvieron únicamente las dos APIs a las 22:50:43 UTC.
Se preservaron supervisores, Ollama, Docker y datos. Los procesos compartían
consola; se usó Stop-Process sobre los PIDs exactos. No se borraron leases.
La API nueva PID 35180, padre 26536, inició a las 22:50:48 UTC.

Observaciones 22:51:12 y 22:52:25 UTC: /health HTTP 200, Ollama disponible.
Heartbeat del nuevo PID avanzó de 22:51:02 a 22:52:09; metabolismo completó
ciclos 2334 a 2338. El contador heartbeat continúa en 1: no se usa como prueba
de progreso. Qualia/Cristal no avanzaron en esa ventana. RAM libre 0,54–0,63 GB;
el runner registra resource_cooldown. Los cinco endpoints de diagnóstico
protegidos devolvieron 403; no se eludió autenticación.

El arranque reconcilió 17 tareas completion_uncertain anteriores, pasando
completed de 121 a 138. No son 17 ejecuciones nuevas. Los workers esperan
leases anteriores (último vencimiento observado: pulse_check 22:53:03 UTC).

El supervisor duplicado sigue intentando arrancar; sus APIs nuevas se rechazan
antes del lifespan con WinError 10048. Ambos supervisores comparten archivos
de logs y el duplicado los sobrescribe: limita la auditoría de logs del servidor
activo. No se afirma que todos los errores estén resueltos. No se detuvieron
supervisores porque la autorización se refiere a la API. Sigue pendiente reparar
el proveedor general de búsqueda y verificar el chat autenticado.

Evidencia en artifacts/audit-20260921: exclusive-reload-result.json,
exclusive-reload-observation-2.json a -4.json; before-exclusive-reload.stderr.log.
Comando de observación: python artifacts/audit-20260921/observe_runtime.py NOMBRE.
Lecturas SQLite con mode=ro; sin tareas artificiales. El campo agregado
events_since_reload del observador conserva un límite histórico anterior;
se revisó además worker_events con created_at >= 2026-09-21T22:50:43.

Diff completo de los dos archivos nuevos respecto de Git: exclusive-launcher.patch
y exclusive-tests.patch; estado: exclusive-reload-git-status.txt, en el mismo
directorio de evidencia. Sin commit ni push.

Actualización 22:53:40 UTC, exclusive-reload-observation-5.json: el worker nuevo
inició automáticamente a las 22:53:03.215 UTC. Dos tareas finalizaron después
del arranque (completed 138→140 y task_completed 32→34); Qualia 336→337;
heartbeat ciclo 7, PID 35180; metabolismo ciclo 2343 completado. Queda una
tarea completion_uncertain marcada durante la recuperación a las 22:53:03;
no se afirma que la cola esté totalmente sana. API 200 y Ollama disponible.
