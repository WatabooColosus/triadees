# Revision de arquitectura Tríade - 2026-06

## Resumen ejecutivo

PR #9 deja a Tríade en una fase de alpha tecnica avanzada. El MVP local es real: la CLI, el runner auditable, doctor, learning, federacion local, memoria semantica gobernada, single port app y CI de Python funcionan. La federacion Android tambien existe como puente operativo para registro, heartbeat, jobs sandbox y reporte de capacidades.

El sistema aun no es produccion ni inferencia distribuida real. No hay RAM/CPU/GPU unificada para Ollama, no hay tensor parallel distribuido, no hay consolidacion automatica de aprendizaje y el host LLM Android depende de artefactos externos (`llama-cli` y modelo `.gguf`) presentes en el dispositivo.

## Estado actual del sistema

- Core local: operativo para runs auditables, Safety, Hipotalamo, Cristal, Bodega y Neurona Central.
- CLI: `run`, `doctor`, `learn` y `federate` se mantienen como superficie estable.
- Single port app: concentra el tablero local, APIs de memoria semantica, federacion local, router, runtime distribuido y descargas Android.
- LearningPipeline: candidato, evaluacion, verificacion y consolidacion controlada. No consolida automaticamente.
- Federacion local: registra nodos, bloquea permisos prohibidos, permite pausa/revocacion y deriva conocimiento entrante a `learning_queue`.
- Relay publico: registra nodos con pairing token, usa Bearer admin para administracion y mantiene una cola SQLite de jobs.
- Android Node: APK nativa con foreground service, heartbeat, jobs sandbox, transporte firmado hacia 8010 y fallback legado.
- CI: `Python Tests` y `Build Android Node APK` pasan en el head `0e5d6f15c6cc7bd5ea87f271bfc0196a8393b27b`.

## Que ya funciona

- Runs auditables con artefactos en `runs/`.
- Doctor local sin Ollama.
- Aprendizaje controlado como cola, no como memoria estable inmediata.
- Proteccion conceptual y tecnica de `identity_core` dentro de LearningPipeline.
- Bloqueo de permisos federados prohibidos como `modify_identity_core`, `execute_system_commands`, `access_private_files`, `access_credentials` y `write_stable_memory`.
- Logs de intercambio federado en `federated_exchange_log`.
- Entrada de conocimiento federado a `learning_queue` con `consolidated=false`.
- Transporte firmado HMAC para endpoints locales `/api/federation/transport/next` y `/api/federation/transport/result`.
- Build de APK debug como artifact de GitHub Actions, no como binario versionado.
- `.gitignore` excluye APKs, DBs locales, tokens, `.env`, backups, builds Android y estados locales.

## Que sigue siendo experimental

- Runtime LLM Android: existe contrato y ejecucion via `ProcessBuilder`, pero solo funciona si el usuario instala/importa un `llama-cli` ejecutable y un modelo `.gguf` dentro de los directorios privados de la app.
- Inferencia distribuida: hoy son jobs verificables, preproceso, probes y generacion local por nodo cuando el backend existe. No es RAM unificada ni Ollama distribuido.
- Relay publico: util para pruebas controladas, pero requiere endurecimiento antes de operar como infraestructura publica permanente.
- Web learning: el aprendizaje post-run esta controlado y candidato-only, pero no hay aprendizaje web autonomo estable.
- Multiples modelos especializados: hay router y recomendaciones, pero no una orquestacion robusta multi-modelo por organo.
- Cristal Morfologico: tiene estado temporal y formula Q, pero aun no gobierna operativamente como controlador autonomo completo.

## Riesgos tecnicos

- `apps/single_port_app.py` concentra demasiadas responsabilidades y mantiene HTML historico duplicado dentro del mismo archivo.
- Hay superficies redundantes entre `apps/api_app.py`, `apps/chat_ui_app.py`, `apps/chat_ui_router_app.py`, `apps/model_router_api.py`, `apps/federation_pairing_app.py`, `apps/public_relay_app.py` y `apps/single_port_app.py`.
- Los contratos core siguen en dataclasses, mientras federation ya migro una parte a Pydantic.
- La cola local de jobs vive en memoria dentro de 8010 y se pierde al reiniciar.
- Las migraciones SQLite son defensivas e incrementales, pero no existe una estrategia formal versionada de migracion.
- No hay pruebas instrumentadas Android ni smoke test real de generacion LLM en CI.
- No hay linter activo para imports muertos o complejidad, aunque la suite de pytest pasa.

## Riesgos de seguridad

- `apps/public_relay_app.py` conserva compatibilidad con `/api/jobs/next?node_id=...&node_token=...`; los tokens en query pueden filtrarse por logs, historial o proxies.
- El cliente Android intenta primero transporte firmado, pero si falla cae al endpoint legado con token en query.
- El transporte firmado HMAC local valida timestamp, firma y cachea nonces en memoria dentro de la ventana temporal; falta persistir nonces/revocaciones si se quiere tolerar reinicios o operar como infraestructura publica.
- El relay guarda tokens de nodo en SQLite en texto claro.
- `apps/single_port_app.py` permite registro local de nodos de forma permisiva en LAN; debe tratarse como entorno local confiable, no como exposicion publica.
- Varias APIs locales dependen de `TRIADE_API_KEY`; si no esta definida, la superficie queda abierta por diseno local.
- La APK puede ejecutar un binario importado por el usuario mediante `ProcessBuilder`; antes de produccion debe exigir procedencia, hash o manifiesto firmado del runtime.

## Riesgos arquitectonicos

- Mezclar relay publico, panel 8010, descarga de runtime, federacion local, memoria semantica y UI en una sola app aumenta el acoplamiento.
- La federacion de compute jobs del relay publico no queda reflejada todavia con la misma profundidad que `federated_exchange_log`.
- Hay dos caminos de nodo movil: agente Termux y APK nativa. La APK es el camino recomendado, pero el codigo legado sigue existiendo.
- La documentacion historica puede inducir a pensar que ciertas fases estan completas cuando hoy son experimentales.
- La vision conceptual supera al runtime actual. El repo debe seguir distinguiendo contrato, prototipo y capacidad real medida.

## Revision especifica de `apps/public_relay_app.py`

`/api/jobs/next?node_token=...` debe migrarse. La recomendacion concreta es:

1. Corto plazo: aceptar `Authorization: Bearer <node_token>` para polling de jobs y resultados, manteniendo el query param solo como compatibilidad temporal marcada como deprecated.
2. Fase E: usar exclusivamente transporte firmado HMAC para claim/result de jobs, aprovechando `SignedEnvelope` y `verify_envelope`.
3. Produccion: persistir cache de nonces/revocaciones, rotar tokens por nodo y registrar auditoria por intento fallido.

Bearer reduce filtrado accidental de tokens. Firma criptografica agrega integridad de payload, frescura temporal y defensa parcial contra suplantacion. Para Tríade, el destino correcto es firma criptografica; Bearer es solo el escalon minimo de compatibilidad.

## Clasificacion Android Node

Clasificacion global: Prototipo funcional.

Motivos:

- Compila en CI y genera un APK debug real.
- Tiene UI, configuracion, foreground service, wake lock, registro, heartbeat y ejecucion de jobs sandbox.
- Reporta CPU/RAM disponibles y capacidades del runtime local.
- Implementa doctor y generacion local Android si existen backend nativo y modelo.
- No incluye backend ni modelo por defecto.
- No tiene pruebas instrumentadas en dispositivos fisicos.
- No demuestra en CI que `android_local_generate` produzca tokens con un GGUF real.
- No usa GPU/NPU Android.
- No puede garantizar 100% de recursos reales porque Android impone limites de proceso, bateria, temperatura y memoria.

Subclasificacion:

- Nodo Android para jobs CPU/preproceso: MVP funcional.
- Host LLM Android: Experimental.
- Producto Android de produccion: No.

## Proximas fases recomendadas

- Fase E: estabilizar federacion, cerrar transporte firmado como camino unico y auditar jobs compute.
- Fase F: aprendizaje web controlado con permisos, fuentes, evidencia y cola candidate-only.
- Fase G: multiples modelos especializados con contratos por organo y fallback medible.
- Fase H: nodos distribuidos con scheduler, cuotas, telemetria y pruebas reales de workload.
- Fase I: memoria semantica avanzada con migraciones versionadas, calidad de embeddings y gobernanza operacional.
- Fase J: Cristal Morfologico operativo con criterios medibles de influencia y rollback.

## Recomendacion de release

PR #9 puede pasar a revision humana, pero no debe fusionarse como produccion. La recomendacion es Ready For Review condicionado: mantener el alcance como arquitectura evolutiva, documentar lo experimental y abrir issues/PRs separados para endurecimiento de transporte, Android runtime real, observabilidad y reduccion de duplicacion.
