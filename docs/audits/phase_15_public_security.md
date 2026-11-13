# Fase 15 — seguridad pública

Fecha UTC: 2026-07-29

Base: `f8a6811`

Estado: `partial` para producción pública; controles locales y backend
distribuido implementados y probados.

`public_guarded` exige ahora usuarios y sesiones reales, no una API key global.
Se añadieron Argon2, roles viewer/operator/admin, tenant, expiración, tokens
aleatorios almacenados solo por hash, revocación, lockout, rate limit, auditoría,
validación anti prompt-injection, egress HTTPS allowlist y headers defensivos.

El cliente usa Bearer, por lo que no existe cookie de sesión susceptible a CSRF.
CORS permanece same-origin por defecto. Los secretos no se guardan en claro y la
revocación permite rotar sesiones sin cambiar una clave global.

## Reproducción

```bash
pytest -q tests/test_public_security.py tests/test_single_port_app.py
python scripts/run_phase_15_public_security.py
```

Evidencia: `artifacts/triade_verify/phase_15/public_security.json`.

El modo incident puede implementarse deshabilitando usuarios y revocando todas
las sesiones; falta todavía un endpoint nominal para esa operación masiva y una
evaluación externa adversarial de abuso, prompt injection y egress.

## Estado distribuido Redis

Cuando `TRIADE_REDIS_URL` está configurado, las sesiones, revocaciones y cuotas
de 60 segundos se comparten entre réplicas mediante Redis. La cuota usa un
sorted set y una operación Lua atómica. Si Redis no está disponible,
`public_guarded` falla cerrado con HTTP 503; no vuelve silenciosamente al estado
local. Sin esa variable se conserva SQLite para operación local compatible.

Se validó contra `redis:7-alpine` real con dos instancias de `PublicAuthStore`,
cada una usando una SQLite distinta: la sesión creada por A fue aceptada por B,
ambas consumieron la misma cuota y una revocación en B fue aplicada
inmediatamente en A. El contenedor temporal fue retirado después de la prueba.

## Recuperación del servicio web

Durante la fase se verificó que no existía proceso escuchando en `8010`: local
devolvía conexión rechazada y el proxy público `502`. Se ejecutó el entrypoint
canónico `scripts/start_studio_web.sh`. Después del arranque:

```text
GET http://127.0.0.1:8010/health/live                    200
GET http://127.0.0.1:8010/                               200
GET https://8010-01kyngxf5vrjegqz9xrck5fwrf.cloudspaces.litng.ai/  200
```

El primer arranque con `nohup` no persistió al terminar su shell padre y el
proxy volvió a 502. Se corrigió arrancando Uvicorn en una sesión persistente;
PID `919611`, escucha `0.0.0.0:8010`. Dos verificaciones posteriores confirmaron
local y público en 200. La causa observable fue ausencia de proceso persistente,
no fallo del proxy. No se hizo despliegue ni se modificó infraestructura externa.

## Validación ejecutada

```text
python -m compileall -q triade apps scripts tests              PASS
ruff check (archivos modificados)                               PASS
ruff format --check .                                           PASS (782 files)
pytest -q tests/test_public_security.py tests/test_single_port_app.py
                                                               PASS (39)
pytest -q tests/operational_truth                              PASS (18)
python scripts/run_runtime_concurrency_test.py                 PASS
python scripts/run_phase_15_public_security.py                 PASS
```

Validación adicional 2026-07-30: Ruff global 0, mypy 0 en 324 módulos, seis
pruebas de seguridad pública verdes y backend Redis real verificado entre dos
réplicas. GitHub Actions y pruebas externas siguen siendo gates independientes.
