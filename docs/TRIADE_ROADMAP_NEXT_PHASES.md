# Roadmap proximas fases Tríade

Este roadmap empieza despues de PR #9. No asume capacidades futuras como ya existentes. Cada fase debe cerrar con tests, logs o evidencia auditable.

## FASE E - Federacion estable

Objetivo: convertir la federacion local/publica en una superficie estable, trazable y segura para nodos autorizados.

Componentes:

- Transporte firmado HMAC como camino principal.
- Deprecacion de tokens en query.
- Cache de nonces para evitar replay.
- Registro de compute jobs en una bitacora auditable equivalente a `federated_exchange_log`.
- Revocacion, pausa, rotacion de tokens y estado operacional por nodo.
- Pruebas de permisos prohibidos, nodo pausado, nodo revocado, firma invalida y timestamp expirado.

Dependencias:

- `triade/federation/contracts.py`
- `apps/single_port_app.py`
- `apps/public_relay_app.py`
- Android Node `RelayClient`
- SQLite local/relay

Riesgos:

- Romper compatibilidad con nodos ya instalados.
- Duplicar contratos entre relay publico y 8010.
- Aceptar jobs sin trazabilidad completa.
- Mantener tokens persistidos sin rotacion.

Criterio de terminacion:

- Ningun endpoint de jobs requiere token en query.
- Todo job claim/result usa Bearer transitorio o firma HMAC, con plan de retiro de Bearer.
- Cada job aceptado genera log auditable.
- `pytest -q` pasa.
- Existe prueba de rechazo para firma invalida, nonce repetido y permiso prohibido.

## FASE F - Aprendizaje web controlado

Objetivo: permitir ingestion desde web/fuentes externas sin consolidacion automatica ni modificacion de identidad.

Componentes:

- Ingesta con fuente, hash, timestamp, riesgo y dominio.
- Cola `learning_queue` como unico punto de entrada.
- Evaluacion Safety antes de avanzar de estado.
- Verificacion con evidencia y aprobacion humana para consolidar.
- Politica explicita para contenido web no confiable.

Dependencias:

- `triade/learning/pipeline.py`
- `triade/safety.py`
- memoria semantica
- API key local si se expone via web

Riesgos:

- Poisoning de memoria semantica.
- Mezclar contenido externo con `identity_core`.
- Consolidar contenido sin fuente verificable.
- Usar scraping o navegador como autoridad automatica.

Criterio de terminacion:

- Todo aprendizaje web queda en candidate/evaluated, nunca stable por defecto.
- `identity_core` no tiene ruta de escritura desde LearningPipeline.
- Tests cubren red flags de identidad, fuente faltante y aprobacion requerida.
- El reporte de doctor indica aprendizaje web en modo controlado.

## FASE G - Multiples modelos especializados

Objetivo: separar roles de modelo por organo sin perder trazabilidad ni fallback local.

Componentes:

- Contratos por rol: central, hipotalamo, cristal, verifier, embeddings.
- Router con capacidad real de hardware y disponibilidad Ollama.
- Fallback sin Ollama para CLI y tests.
- Registro por run de modelo recomendado, modelo usado y motivo.

Dependencias:

- `triade/models/`
- `triade/core/runner.py`
- `triade/core/hypothalamus.py`
- `triade/core/central.py`
- Ollama local opcional

Riesgos:

- Aumentar complejidad sin medir calidad.
- Usar modelos no disponibles en la maquina local.
- Introducir dependencia de nube.
- Romper reproducibilidad de tests.

Criterio de terminacion:

- Cada organo declara modelo preferido y fallback.
- Runs guardan decision de router y resultado.
- Tests sin Ollama siguen pasando.
- Doctor muestra disponibilidad real, no aspiracional.

## FASE H - Nodos distribuidos

Objetivo: ejecutar trabajo real en nodos autorizados sin prometer memoria unificada ni control horizontal total.

Componentes:

- Scheduler de jobs con cuotas por nodo.
- Jobs CPU reales: preprocess, embeddings, probe, hash, validacion.
- Host LLM Android solo cuando `android_model_doctor` confirme backend y modelo.
- Telemetria: latencia, errores, recursos reportados, throughput.
- Backpressure y timeout.

Dependencias:

- Fase E completa.
- Android Node estable.
- Relay publico endurecido.
- Observabilidad en 8010.

Riesgos:

- Confundir federacion de jobs con tensor parallel.
- Sobrecargar dispositivos moviles.
- Dejar jobs colgados.
- Ejecutar binarios no verificados.

Criterio de terminacion:

- El 8010 puede asignar jobs a varios nodos y recibir resultados medibles.
- Los nodos no reciben tareas fuera de sandbox.
- Cada resultado queda auditado con nodo, tarea, duracion y estado.
- `android_local_generate` solo se marca disponible si genera en el dispositivo.

## FASE I - Memoria semantica avanzada

Objetivo: hacer que la memoria semantica sea util, gobernada y mantenible.

Componentes:

- Migraciones versionadas.
- Reindexado controlado.
- Calidad de embeddings por dominio.
- Politicas de retencion, archivo y rechazo.
- Auditoria de influencia en respuestas.

Dependencias:

- `triade/memory/semantic_store.py`
- `triade/memory/semantic_governance.py`
- `triade/core/bodega.py`
- `triade/learning/pipeline.py`

Riesgos:

- Recuperar memoria irrelevante.
- Dar autoridad a memoria experimental.
- Duplicar documentos sin control.
- Crecer SQLite sin mantenimiento.

Criterio de terminacion:

- Hay migraciones reproducibles.
- Search reporta fuentes y estado de gobernanza.
- Memoria experimental no influye salvo autorizacion explicita.
- Tests cubren transiciones candidate, experimental, stable, rejected y archived.

## FASE J - Cristal Morfologico operativo

Objetivo: convertir el Cristal en un organo operacional medible, no solo descriptivo.

Componentes:

- Estados temporales con influencia explicita.
- Formula Q trazable en cada run.
- Comparacion contextual por proyecto/neuron/contexto.
- Reglas de rollback o alerta cuando la estabilidad cae.
- Integracion con Safety y Runner sin control autonomo peligroso.

Dependencias:

- `triade/core/crystal.py`
- `triade/core/runner.py`
- memoria historica
- Safety

Riesgos:

- Sobredimensionar el Cristal como autoridad central.
- Ocultar decisiones bajo metrica no explicada.
- Influir respuestas sin evidencia.
- Crear automatismos que modifiquen memoria o identidad.

Criterio de terminacion:

- Cada run registra estado cristalino, Q y motivo.
- El Cristal influye solo dentro de reglas documentadas.
- Safety puede bloquear influencia riesgosa.
- Hay tests para estabilidad, transicion temporal y contexto.
