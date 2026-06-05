# Public Deployment Risk

Archivos revisados:

- `Dockerfile`
- `Procfile`
- `railway.json`
- `render.yaml`

Decision: conservar en PR #9 como soporte experimental de relay publico, no como declaracion de produccion.

## Estado real

Estos archivos levantan `apps.public_relay_entrypoint` o `apps.public_relay_app` para exponer el relay publico. Son utiles para pruebas controladas de nodos Android/navegador, pero amplian la superficie de despliegue y deben tratarse como experimental hasta completar Fase E.

## Riesgos

- Exponer el relay sin `TRIADE_RELAY_PAIRING_TOKEN` o `TRIADE_RELAY_ADMIN_TOKEN` fuertes deja el servicio inutil o inseguro.
- SQLite local en contenedores efimeros puede perder nodos, jobs y auditoria si no hay volumen persistente.
- El relay todavia conserva payload/result completos en la tabla operacional `relay_jobs`; la tabla nueva `relay_job_audit` guarda hashes, pero no reemplaza la cola operacional.
- El camino legacy de token en query sigue disponible temporalmente para compatibilidad.
- No hay rate limit, WAF, captcha ni proteccion contra abuso de registro si el pairing token se filtra.
- No hay rotacion automatica de node tokens.

## Requisitos minimos antes de uso publico sostenido

- HTTPS obligatorio.
- `TRIADE_RELAY_PAIRING_TOKEN` y `TRIADE_RELAY_ADMIN_TOKEN` generados con alta entropia.
- Base de datos persistente fuera del filesystem efimero.
- Logs de aplicacion sin query strings sensibles.
- Monitoreo de errores 401/403/5xx.
- Plan de rotacion/revocacion de nodos.
- Migracion de `/api/jobs/next` a Bearer/firma como camino unico.

## Criterio para mover a produccion

No marcar produccion hasta que:

- El query string legacy de node token este retirado o apagable por configuracion.
- Compute jobs locales y publicos tengan auditoria completa.
- Exista proteccion anti-replay para mensajes firmados.
- Existan pruebas de despliegue con DB persistente.
- La documentacion de operacion indique backup, rotacion de secretos y revocacion de nodos.
