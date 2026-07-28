# Recuperación web de Studio · 2026-07-28

## Objetivo

Eliminar el 404 del proyecto Tríade en Lightning Studio y dejar su web con
arranque reproducible.

## Diagnóstico

- Rama de trabajo: `fix/web-404-20260728`.
- No existía un proceso escuchando en el puerto web 8010.
- `.lightning_studio/on_start.sh` no iniciaba Tríade después de reiniciar Studio.
- La ruta `/health/ready` usaba `/app/memory` y `/app/runs` incluso fuera del
  contenedor, y por ello devolvía 503 por permisos en Studio.
- Las antiguas URLs de Railway y Render devuelven 404 desde sus plataformas;
  no son solicitudes que alcancen FastAPI.

## Documentos fundacionales

Se localizaron `triade_formulas_v0_1.pdf` y `Base.docx`. Esta corrección es
operativa y no altera identidad, órganos ni arquitectura cognitiva.

## Cambios

- Se agregó `scripts/start_studio_web.sh` para iniciar de forma idempotente el
  runtime unificado en 8010 y comprobar `/health/live`.
- Readiness resuelve por defecto `memory/` y `runs/` desde el directorio de
  trabajo. En el contenedor se conserva `/app/memory` y `/app/runs` porque su
  `WORKDIR` continúa siendo `/app`.
- Se añadió una prueba de los paths locales de readiness.
- El hook de Studio apunta al script versionado del repositorio.

## Riesgos y rollback

El proceso sigue ligado a la vida del Studio. El rollback consiste en retirar
la llamada del hook, eliminar el script y restaurar los defaults absolutos de
readiness. No se modificaron datos, secretos ni documentos fundacionales.
