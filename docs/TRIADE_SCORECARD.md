# Scorecard Tríade - PR #9 Phase E prep

Escala: 0 a 10. La puntuacion mide el estado real del codigo presente, no la vision conceptual.

| Area | Puntaje | Lectura |
| --- | ---: | --- |
| Arquitectura | 7.5 | La separacion por organos, runner auditable, memoria y federacion esta clara. Sigue pendiente dividir responsabilidades de `apps/single_port_app.py` y apps historicas redundantes. |
| Seguridad | 7.4 | Mejora por Bearer preferente en relay, ocultamiento de `node_token` en listados y auditoria hash-only. Pendiente: retirar query legacy, anti-replay, rotacion de tokens y perfiles publicos. |
| Federacion | 7.0 | Federation local mantiene permisos, revocacion, logs y learning_queue. Relay publico avanza con Bearer y auditoria minima, pero falta contrato firmado unico. |
| Relay publico | 7.2 | Pairing/admin sin defaults, Bearer en `/api/jobs/next`, tokens no listados y `relay_job_audit` hash-only. Pendiente rate limit, rotacion y DB persistente para despliegue real. |
| Android Node | 6.2 | MVP funcional para jobs CPU/preproceso y artifact CI real. Host LLM Android sigue experimental hasta probar backend/modelo en dispositivo fisico. |
| Learning pipeline | 7.2 | Candidate/evaluated/verified/consolidated mantiene identidad protegida y no consolida automatico. Falta aprendizaje web controlado completo. |
| Testing | 8.2 | Suite Python y relay focal pasan; CI Python/Android estaba verde antes del corte. Falta instrumentacion Android y pruebas anti-replay. |
| Documentacion | 8.0 | Backlog Phase E, riesgos publicos, scorecard y runtime Android ahora distinguen real/experimental. Persisten docs historicos abundantes. |
| Observabilidad | 7.3 | Runs auditables, doctors, logs federados y nueva auditoria de jobs del relay. Falta telemetria consolidada 8010 y auditoria local equivalente. |
| Mantenibilidad | 6.4 | Cambios pequenos y testeados. Aun pesan duplicacion de apps, migraciones SQLite informales y single port monolitico. |

Nota global: 7.2 / 10

## Madurez

Nivel actual: FASE_E_PREP.

Lectura: Tríade ya empezo ejecucion tecnica hacia Fase E. No es `FASE_E_STABLE` porque faltan retiro del query legacy, firma criptografica obligatoria/anti-replay, auditoria equivalente en 8010, rotacion/revocacion de tokens del relay y prueba fisica Android LLM.

## Decision de release recomendada

PR #9 puede seguir como Draft mientras se valida el corte Phase E prep. Si la suite completa y CI quedan verdes, puede pasar a Ready For Review condicionado, sin merge automatico.

TRIADE_MATURITY_LEVEL = FASE_E_PREP
