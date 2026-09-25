# Búsqueda y recuperación

## Proveedor preparado

Por indicación del usuario se preparó RapidAPI Real-Time Web Search (OpenWeb
Ninja). La página pública y la interfaz consultadas el 2026-09-21 muestran
BASIC $0/mes, 100 solicitudes/mes, límite estricto, 1 solicitud/segundo. Hay
además una cuota de transferencia de plataforma de 10240 MB con excedentes;
no se contrató ningún plan ni se introdujo tarjeta.

Fuente: https://rapidapi.com/letscrape-6bRBa3QguO5/api/real-time-web-search/pricing
Contrato: https://rapidapi.com/letscrape-6bRBa3QguO5/api/real-time-web-search

Se integró GET https://real-time-web-search.p.rapidapi.com/search-light con q,
num=8, hl=es y encabezados X-RapidAPI-Key / X-RapidAPI-Host. No usa resúmenes
de IA como fuente; recupera páginas de los resultados con el control de URLs
públicas existente. No hay reintentos ni upgrades automáticos. Redirecciones
del endpoint autenticado bloqueadas para no reenviar la clave a otros hosts.
Credenciales nunca se envían a las páginas de resultados. Respuesta acotada a
350000 bytes. 403/429 quedan como fallos; no se dan por resultados verificados.

Configuración necesaria en el entorno de usuario de Windows:
TRIADE_SEARCH_PROVIDER=rapidapi y RAPIDAPI_KEY con una clave de la cuenta
suscrita al plan BASIC. Configurar mediante el editor de variables de entorno,
sin pegar secretos en chat ni archivos versionados. El supervisor lee estos
valores al arrancar. Posterior activación requiere recarga autorizada.
Brave queda disponible opcionalmente con TRIADE_SEARCH_PROVIDER=brave y
BRAVE_SEARCH_API_KEY, conforme a la autorización previa de preparar sin clave.

La sesión de navegador disponible no está autenticada. Se abrió la pantalla
de login; no hay credenciales rellenadas. Pendientes login, suscripción gratuita,
configuración de clave y prueba real de RapidAPI. No se afirma que esté activo.

La prueba de DuckDuckGo devolvió challenge (anomaly-modal), sin enlaces.
Ahora queda status=degraded/search_warning=search_provider_challenge. El fallback
Wikipedia rechaza resultados con escaso solapamiento temático. La consulta
«5 presidentes de latinoamerica actuales» devolvió cero fuentes tras el filtro,
en lugar de páginas de canales de televisión. El filtro léxico no garantiza
exactitud; la corroboración y las citas siguen siendo necesarias. El preflight
ya no repite una consulta explícita fallida, evitando doble consumo de cuota.

## Supervisor y tarea

Se añadió bloqueo de archivo exclusivo al inicio del supervisor, antes de leer
claves, tocar logs o crear una API. Lo retiene el proceso y el SO lo libera al
salir; no se elimina el archivo ni se interpreta su presencia como un lock vivo.
Prueba real con dos PowerShell: el segundo se rechaza; tras cerrar el primero,
un tercero entra. La API conserva además exclusividad de puerto.

Con autorización explícita del usuario se validaron PIDs/creación/comandos y
se detuvieron los supervisores 17320/26536 y la API 35180 a las 23:09 UTC.
Supervisor nuevo 30552 (23:09:02.372 UTC), API 520 (23:09:02.796 UTC).
Los tres PIDs antiguos ya no estaban presentes en la observación posterior.
Logs: startup complete, sin repetición de colisión de puerto en la ventana.

La recuperación automática cerró task-d8c8d4d323424309a6686b98b702ff01
(pulse_check) como dead_letter a las 23:09:15 UTC por ausencia de artefacto,
conservando errores e historial. No se marcó completada ni se reencoló.
Se reparó además la causa del limbo: running expirado sin artefacto se
cuarentena en la misma recuperación, en lugar de esperar un siguiente arranque.
No se ejecutó SQL manual para cambiar estados operativos.

67 pruebas pasaron: search_provider, guarded_web, orphaned_task_recovery,
uncertain_completion_leak, worker_runtime_recovery, windows_supervisor_singleton,
autonomous_research, expression_cortex_runner. Ruff y parser PowerShell pasaron.
Una ejecución inicial tuvo un basetemp demasiado largo para Windows; la corrida
final usó C:/Users/sven6/Documents/Triade/artifacts/t58.

Observación 23:09:30 UTC: /health=200, Ollama disponible; worker nuevo running
desde 23:09:15.785 UTC, heartbeat PID 520; metabolismo 2399 completado.
Endpoints live/deep/Always-On/workers/heartbeat: 403 por autenticación.
RAM libre 1,03 GB, aún existe resource_cooldown. No se certifica salud total.

Evidencia: artifacts/audit-20260921/single-supervisor-reload.json,
single-supervisor-1.json y single-supervisor-2.json; logs en artifacts/service_logs.
Git: main, HEAD 9c1fd1187760e42335f58dbfa0bbe153fd52fc01, fetch origin y
divergencia 0/0. Sin commit/push. Diffs y estado en artifacts/audit-20260921.

Segunda observación 23:10:44 UTC (single-supervisor-3.json): misma API PID 520,
heartbeat timestamp 23:10:42, metabolismo 2399→2404, heartbeat de tarea activa
actualizado 23:10:31. /health=200, Ollama disponible. Sin nuevas finalizaciones
en esa ventana ni avance de Qualia/Cristal; no se confunde actividad con éxito.
El log de API conserva startup complete y no presenta colisiones ni traceback.
