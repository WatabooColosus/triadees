# Auditoria tecnica: runtime Android para modelos locales

Fecha: 2026-06-04

## Estado actual

Triadees ya tiene federacion operativa para registrar nodos Android, recibir heartbeats, ejecutar jobs CPU ligeros y devolver resultados al 8010. La APK `Triade Android Node` funciona como servicio en primer plano y reporta CPU/RAM autorizadas.

Lo que todavia no existe es un backend nativo de inferencia LLM dentro del APK. Por eso la federacion puede alimentar contexto y ejecutar probes, pero no puede cargar un GGUF/ONNX ni ejecutar tokens localmente en Android.

## Deudas tecnicas principales

1. Backend nativo ausente
   - No hay llama.cpp, ONNX Runtime, MediaPipe LLM Inference ni otro motor nativo embebido.
   - La APK no puede cargar modelos reales todavia.

2. Protocolo de modelo incompleto
   - Faltaban tareas explicitas para doctor/inventario/generacion local Android.
   - Sin contrato estable, el backend web no podia distinguir "nodo que preprocesa" de "nodo que hospeda modelo".

3. Transporte mixto
   - LAN directo al 8010 es ideal para jobs locales.
   - Relay publico funciona como puente, pero agrega latencia y no representa memoria local compartida.

4. Recursos reportados
   - Android reporta RAM disponible, no RAM total.
   - Cuando el relay publico no preserva `resource_limit_percent`, el local asume 60%.

5. Versionado Android
   - `versionName` de Gradle estaba desalineado frente a `app_version` reportado por heartbeat.

## Corte minimo recomendado

El siguiente corte sano es preparar la APK para runtime local de modelos sin fingir inferencia:

- `android_model_doctor`: devuelve backend, modelos disponibles, formatos soportados y si puede generar.
- `android_local_generate`: acepta prompt/modelo, pero falla de forma estructurada si no hay backend nativo.
- Capacidades nuevas: `edge_model_runtime`, `model_runtime_backend`, `can_run_local_llm`, `supported_model_formats`.

Con eso el 8010 puede planificar correctamente y el siguiente programador puede integrar llama.cpp/ONNX detras del mismo contrato.

## Siguiente fase real

Para que Android ejecute modelos de verdad:

1. Integrar llama.cpp como libreria nativa Android o binario JNI.
2. Usar modelos GGUF cuantizados pequenos, por ejemplo 0.5B-1.5B en Q4/Q5.
3. Guardar modelos en almacenamiento privado de la app o permitir seleccion explicita por Storage Access Framework.
4. Implementar `android_local_generate` llamando al backend nativo.
5. Reportar `can_run_local_llm=true` solo cuando el backend cargue un modelo y pase un smoke test.

No es correcto afirmar que la RAM/CPU de varios Android se suma como una sola memoria de Ollama. Eso requiere inferencia distribuida real/tensor-paralela o un runtime tipo RPC disenado para ello.
