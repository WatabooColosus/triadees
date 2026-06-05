# Ruta de trabajo: APK Android como alimentador real de modelos locales

Fecha: 2026-06-04

Actualizacion de ejecucion: 2026-06-05.

## Objetivo

Convertir `Triade Android Node` en un alimentador real para Tríade local:

- CPU Android para preproceso, chunking, hashing, embeddings ligeros y probes.
- RAM Android para cargar modelos locales pequeños dentro del propio dispositivo, no como RAM unificada de Ollama.
- GPU/NPU Android cuando exista backend compatible.
- Procesamiento local en Android con retorno auditable al 8010.

Importante: varios Android no se convierten automáticamente en una sola memoria de Ollama. Para eso se necesita un runtime distribuido real. La ruta correcta es avanzar por contratos verificables.

## Requisito no negociable: runtime real

El runtime debe ser real, no simulado.

Para marcar un nodo Android como runtime de modelos, debe existir evidencia tecnica de:

1. Backend nativo cargado en el dispositivo.
   - llama.cpp, ONNX Runtime, MediaPipe LLM Inference u otro motor local verificable.
   - No cuenta un mock, benchmark, preproceso o respuesta por plantilla.

2. Modelo local cargado desde Android.
   - Inventario de archivo real `.gguf`, `.onnx` u otro formato soportado.
   - Tamaño, ruta privada/permitida y hash del modelo.

3. Generacion local comprobada.
   - `android_local_generate` debe devolver texto generado por el backend nativo.
   - Debe incluir `backend`, `model`, `tokens_generated`, `elapsed_ms` y `ok=true`.

4. Doctor verificable.
   - `android_model_doctor` solo puede reportar `can_run_local_llm=true` si paso un smoke test real.
   - Si no hay backend, debe responder `backend=none`, `can_run_local_llm=false`.

5. Evidencia en 8010.
   - El tablero solo puede mostrar `can_host_llm=true` cuando el nodo cumple lo anterior.
   - Los jobs de preproceso/probe siguen siendo utiles, pero no cuentan como inferencia local.

6. Auditoria por run.
   - Cada uso del runtime debe guardar nodo, APK, backend, modelo, hashes, tiempos y resultado.

Regla: si no genera tokens en el dispositivo con un motor local verificable, no es runtime real de modelos.

## Fase 0: Estado base ya logrado

Hecho:

- APK nativa con servicio en primer plano.
- Registro/heartbeat contra 8010 o relay público.
- Modo dedicado reportando 100% de CPU/RAM disponible para Triade dentro de los limites reales de Android. Ya no debe describirse como selector 60/90/95.
- Jobs:
  - `preprocess_text`
  - `federated_inference_probe`
  - `android_model_doctor`
  - `android_local_generate`
- 8010 con:
  - `/api/distributed-runtime/preprocess`
  - `/api/distributed-runtime/probe`
  - `/api/distributed-runtime/android-model-doctor`
- Contrato honesto de runtime Android:
  - `edge_model_runtime`
  - `model_runtime_backend`
  - `can_run_local_llm`
  - `local_model_runtime_ready`
  - `supported_model_formats`
  - `available_local_models`

Pendiente inmediato: instalar el artifact actual `triade-android-node-debug` en dispositivos fisicos y confirmar que `android_model_doctor` responde desde el relay/8010.

Actualizacion historica 0.5.0:

- La APK puede autorizar hasta 95% de recursos.
- Solicita `largeHeap` para ampliar margen de procesos pesados.
- Reporta `memoryClass`, `largeMemoryClass`, heap Java y baja memoria.
- El 8010 expone `/api/federation/resource-lease` para ver recursos federados arrendables.

Esto permitio aprovechar mejor dispositivos con mas de 2 GB libres, sin afirmar que Android entregue toda la RAM total al proceso. En el estado actual, el modo dedicado reporta 100% disponible, pero Android conserva el control real de heap, memoria por proceso, temperatura, bateria y planificador.

## Estado real 2026-06-05

Lo que hace hoy:

- Registra nodo Android y mantiene foreground service.
- Publica capacidades de CPU/RAM/heap y estado de runtime local.
- Ejecuta jobs sandbox como `sha256`, `preprocess_text`, `federated_inference_probe`, `android_model_doctor` y `android_local_generate`.
- Intenta transporte firmado hacia 8010 y conserva fallback legacy cuando el servidor no soporta el transporte nuevo.
- Puede descargar artefactos desde 8010 si existen localmente.

Lo que no hace todavia:

- No convierte varios Android en una sola RAM para Ollama.
- No reparte capas/tensores de un mismo modelo entre dispositivos.
- No instala Termux ni paquetes del sistema desde la APK.
- No tiene GPU/NPU Android validado.
- No incluye backend/modelo LLM por defecto en el APK.
- No tiene prueba instrumentada automatica con dispositivo real.

Clasificacion:

- Alimentador CPU/preproceso: MVP funcional.
- Host LLM Android: experimental.
- Inferencia distribuida real: investigacion futura.
- Producto de produccion: no.

## Fase 1: Consolidar alimentador CPU real

Meta: que Android aporte CPU de forma repetible a modelos locales sin requerir inferencia nativa todavía.

Tareas:

1. Mejorar `preprocess_text`
   - Partición por nodos.
   - Medición de tiempo por nodo.
   - Retorno de chunks normalizados.
   - Top keywords y resumen extractivo simple.

2. Agregar jobs CPU:
   - `context_rank`
   - `deduplicate_chunks`
   - `token_estimate`
   - `semantic_candidate_filter`

3. En 8010:
   - Planificador que elija nodos por CPU/RAM autorizada.
   - Timeout por nodo.
   - Reintento en otro nodo.
   - Métrica `cpu_feed_score`.

Resultado esperado:

- El modelo local en PC recibe menos contexto basura.
- La PC usa menos CPU en preparación.
- El tablero evidencia aporte real por nodo.

## Fase 2: Modelo local pequeño dentro de Android

Meta: que un Android pueda ejecutar un modelo pequeño propio y devolver respuesta.

Backend recomendado inicial:

- llama.cpp Android/JNI con GGUF cuantizado.

Alternativas:

- ONNX Runtime Mobile.
- MediaPipe LLM Inference si encaja con los modelos disponibles.

Tareas:

1. Crear módulo nativo:
   - `android/triade-node/app/src/main/cpp/`
   - JNI wrapper `TriadeLlamaBridge`.
   - ABI inicial: `arm64-v8a`.

2. Modelo:
   - Carpeta app-private: `Android/data/local.triade.node/files/models`.
   - Inventario `.gguf`.
   - Smoke test de carga.

3. Implementar `android_local_generate`:
   - Input: `model`, `prompt`, `max_tokens`, `temperature`.
   - Output: `ok`, `text`, `tokens_generated`, `elapsed_ms`, `backend`.

4. Cambiar doctor:
   - `can_run_local_llm=true` solo si carga modelo y genera una respuesta mínima.

Resultado esperado:

- Android puede hospedar modelos 0.5B-1.5B cuantizados si la RAM libre alcanza.
- 8010 puede marcar `can_host_llm=true`.

## Fase 3: Alimentador de embeddings

Meta: descargar trabajo de memoria semántica a Android cuando sea viable.

Tareas:

1. Job nuevo:
   - `android_embed_text`

2. Backends posibles:
   - ONNX embedding pequeño.
   - llama.cpp embedding si el modelo lo soporta.

3. 8010:
   - Integrar con `SemanticEmbeddingEngine`.
   - Guardar metadata del nodo que generó embedding.
   - Validar dimensiones/modelo antes de mezclar vectores.

Resultado esperado:

- Android ayuda a construir memoria semántica.
- La PC local queda más libre para generación central.

## Fase 4: GPU/NPU Android

Meta: aprovechar aceleración real del dispositivo cuando exista backend disponible.

Tareas:

1. Detectar capacidades:
   - Vulkan disponible.
   - NNAPI disponible.
   - GPU vendor/model.
   - memoria estimada accesible.

2. Reportar:
   - `android_gpu_available`
   - `android_npu_available`
   - `accelerators`

3. Backend:
   - llama.cpp Vulkan si viable.
   - ONNX Runtime NNAPI/CoreML-equivalente Android.

4. Tablero:
   - No sumar GPU como VRAM de PC.
   - Mostrarla como acelerador remoto por jobs/modelos Android.

Resultado esperado:

- Algunos modelos corren mejor en Android.
- 8010 puede decidir si mandar generación al teléfono o mantenerla en PC.

## Fase 5: Orquestación multi-nodo

Meta: coordinar varios Android sin fingir memoria compartida.

Tareas:

1. Scheduler:
   - `least_busy`
   - `highest_score`
   - `model_available`
   - `battery_safe`

2. Jobs paralelos:
   - varios prompts/chunks a varios nodos.
   - merge de respuestas.
   - consenso o ranking.

3. Auditoría:
   - run id por job.
   - node id.
   - versión APK.
   - backend.
   - modelo.
   - hashes de prompt/resultado.

Resultado esperado:

- Tríade usa una federación de dispositivos para trabajo paralelo real.
- Cada aporte queda auditable.

## Fase 6: Distribución de inferencia real

Meta avanzada: dividir una inferencia de un modelo entre dispositivos.

No empezar aquí.

Requisitos:

- Runtime tensor-paralelo o RPC diseñado para ello.
- Sincronización de pesos/capas.
- Transporte rápido y estable.
- Manejo de latencia.

Opciones a investigar:

- llama.cpp RPC si Android puede compilar/servir workers.
- Worker propio por capas solo para modelos muy pequeños.
- Arquitectura mixture-of-experts local por nodos, no memoria unificada.

Resultado esperado:

- Investigación, no promesa inmediata.

## Criterio de éxito

La APK será considerada alimentador real cuando:

1. `android_model_doctor` responda desde un dispositivo real.
2. `android_local_generate` genere texto localmente en Android.
3. 8010 muestre `can_host_llm=true` para ese nodo.
4. Un run de Tríade pueda usar ese nodo como modelo o coprocesador.
5. El resultado quede auditado con nodo, backend, modelo y tiempos.

## Primer próximo paso

Cuando se retome:

1. Instalar APK `0.4.0`.
2. Ejecutar en 8010: `Doctor modelos Android`.
3. Confirmar que aparece `android_model_doctor`.
4. Integrar llama.cpp Android como backend nativo mínimo.
5. Probar un GGUF pequeño con `android_local_generate`.
