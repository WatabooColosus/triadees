# Phase E Execution Backlog

Objetivo: mover Tríade desde `FASE_D_PLUS_ALPHA` hacia `FASE_E_STABLE` con cambios pequenos, testeados y auditables.

## Epica E1 - Transporte federado seguro

### E1.1 Bearer preferente para relay jobs

- Prioridad: P0
- Archivos afectados: `apps/public_relay_app.py`, `tests/test_public_relay_app.py`
- Riesgo: bajo
- Tarea: permitir `Authorization: Bearer <node_token>` en `/api/jobs/next` como camino preferente.
- Criterio de aceptacion: un nodo registrado puede reclamar job con Bearer; Bearer invalido responde 401; el query string legacy sigue funcionando temporalmente.
- Test esperado: tests de Bearer valido, Bearer invalido y legacy query.
- Estado: implementado en PR9 Phase E prep.

### E1.2 Deprecar token en query string

- Prioridad: P0
- Archivos afectados: `apps/public_relay_app.py`, Android Node `RelayClient`, docs de relay.
- Riesgo: medio
- Tarea: mantener compatibilidad legacy por una ventana corta y emitir documentacion de deprecacion.
- Criterio de aceptacion: clientes modernos usan Bearer o transporte firmado; docs declaran query string como legacy.
- Test esperado: test legacy sigue pasando mientras exista compatibilidad; nuevo test asegura que el HTML del navegador usa Bearer.
- Estado: parcialmente implementado. El HTML del relay ya usa Bearer; Android intenta transporte firmado primero y fallback legacy.

### E1.3 Firma criptografica como camino final

- Prioridad: P1
- Archivos afectados: `triade/federation/contracts.py`, `apps/public_relay_app.py`, `apps/single_port_app.py`, Android Node `RelayClient`.
- Riesgo: alto
- Tarea: unificar claim/result de jobs con `SignedEnvelope` HMAC y cache de nonces.
- Criterio de aceptacion: firma invalida, timestamp expirado y nonce repetido son rechazados.
- Test esperado: tests unitarios de verify envelope y tests API de replay.
- Estado: pendiente.

## Epica E2 - Auditoria de compute jobs

### E2.1 Tabla hash-only de auditoria en relay publico

- Prioridad: P0
- Archivos afectados: `apps/public_relay_app.py`, `tests/test_public_relay_app.py`
- Riesgo: bajo
- Tarea: registrar job_id, node_id, task, status, timestamps y hashes de payload/result/error sin duplicar contenido sensible completo.
- Criterio de aceptacion: cada create/claim/result actualiza `relay_job_audit`; hashes tienen 64 caracteres; texto sensible no aparece en hashes.
- Test esperado: test de ciclo job completo consulta `relay_job_audit`.
- Estado: implementado en PR9 Phase E prep.

### E2.2 Auditoria equivalente en 8010 local

- Prioridad: P1
- Archivos afectados: `apps/single_port_app.py`, `triade/memory/schemas.sql`, tests single port.
- Riesgo: medio
- Tarea: llevar jobs locales de nodos a una tabla auditada con hashes y estado.
- Criterio de aceptacion: jobs locales y resultados quedan trazados aunque no entren a `federated_exchange_log`.
- Test esperado: crear job local, reclamarlo, enviar resultado y verificar fila auditada.
- Estado: pendiente.

### E2.3 Redaccion de payload/result operacional

- Prioridad: P1
- Archivos afectados: `apps/public_relay_app.py`, `apps/single_port_app.py`.
- Riesgo: alto
- Tarea: decidir si `relay_jobs.payload` y `relay_jobs.result` deben mantenerse completos, cifrarse, truncarse o moverse a refs.
- Criterio de aceptacion: la cola operacional sigue funcionando y la auditoria no conserva datos sensibles completos.
- Test esperado: pruebas de compatibilidad y redaccion.
- Estado: pendiente. La auditoria ya es hash-only, pero la tabla operacional aun conserva payload/result para ejecutar jobs.

## Epica E3 - Relay publico endurecido

### E3.1 No exponer tokens en listados

- Prioridad: P0
- Archivos afectados: `apps/public_relay_app.py`, `tests/test_public_relay_app.py`
- Riesgo: bajo
- Tarea: excluir `node_token` de `/api/nodes` y verificar que respuestas de jobs no devuelven token.
- Criterio de aceptacion: register sigue devolviendo el token inicial; listados y jobs no lo devuelven.
- Test esperado: assert de ausencia de token en `/api/nodes`, `/api/jobs/next` y `/api/jobs`.
- Estado: implementado.

### E3.2 Rotacion/revocacion de node tokens

- Prioridad: P1
- Archivos afectados: `apps/public_relay_app.py`, docs relay, tests.
- Riesgo: medio
- Tarea: agregar revocacion/rotacion admin sin borrar historial.
- Criterio de aceptacion: nodo revocado no puede reclamar jobs; audit log conserva historial.
- Test esperado: revocar nodo y comprobar 401.
- Estado: pendiente.

## Epica E4 - Android Node realidad tecnica

### E4.1 Clasificacion honesta

- Prioridad: P0
- Archivos afectados: `docs/TRIADE_NODE_RUNTIME.md`, `docs/android_apk_model_feeder_roadmap.md`, `docs/TRIADE_SCORECARD.md`
- Riesgo: bajo
- Tarea: declarar Android Node como MVP funcional para jobs CPU/preproceso y experimental para host LLM.
- Criterio de aceptacion: docs dicen que no hay RAM unificada, no hay GPU/NPU validado y LLM requiere backend/modelo reales.
- Test esperado: revision documental.
- Estado: implementado.

### E4.2 Smoke test fisico Android LLM

- Prioridad: P1
- Archivos afectados: Android Node, docs runtime, tests manuales.
- Riesgo: medio
- Tarea: instalar APK en dispositivo real, descargar/importar `llama-cli` y `.gguf`, ejecutar `android_model_doctor` y `android_local_generate`.
- Criterio de aceptacion: resultado incluye backend, modelo, elapsed_ms y texto generado en el dispositivo.
- Test esperado: reporte manual con hash de APK, modelo y salida.
- Estado: pendiente.

## Epica E5 - Superficie de despliegue

### E5.1 Documentar Docker/Railway/Render como experimental

- Prioridad: P0
- Archivos afectados: `Dockerfile`, `Procfile`, `railway.json`, `render.yaml`, `docs/PUBLIC_DEPLOYMENT_RISK.md`
- Riesgo: bajo
- Tarea: conservar archivos sin eliminarlos y documentar que el despliegue publico requiere tokens fuertes, HTTPS y DB persistente.
- Criterio de aceptacion: doc de riesgo existe y no promete produccion.
- Test esperado: revision documental.
- Estado: implementado.

## Epica E6 - CI y criterios de salida

### E6.1 Suite minima obligatoria

- Prioridad: P0
- Archivos afectados: tests existentes.
- Riesgo: bajo
- Tarea: ejecutar `pytest -q`, `doctor --no-ollama`, `learn doctor`, `federate doctor`.
- Criterio de aceptacion: todos pasan localmente.
- Test esperado: salida de comandos en reporte final.
- Estado: obligatorio en cada corte.

### E6.2 Criterio `FASE_E_STABLE`

- Prioridad: P0
- Archivos afectados: docs scorecard y reportes.
- Riesgo: bajo
- Tarea: no marcar Fase E stable hasta cerrar E1.3, E2.2, E3.2 y smoke Android minimo.
- Criterio de aceptacion: scorecard termina en un maturity level honesto.
- Test esperado: revision documental.
- Estado: pendiente.
