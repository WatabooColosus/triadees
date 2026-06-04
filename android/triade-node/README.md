# Triade Android Node

Nodo Android nativo para alimentar la Tríade local/federada desde dispositivos autorizados.

## Rol

- Se registra contra el relay público de Tríade.
- Mantiene un servicio en primer plano con notificación visible.
- Publica capacidades del dispositivo.
- Ejecuta tareas CPU ligeras:
  - `echo`
  - `sha256`
  - `browser_benchmark`
  - `preprocess_text`
  - `federated_inference_probe`
  - `android_model_doctor`
  - `android_local_generate`

Este nodo no instala modelos ni accede a archivos privados por defecto. Es el primer puente nativo para usar CPU/RAM del dispositivo de forma consentida. El runtime distribuido actual ejecuta jobs verificables y devuelve contexto/resultados al 8010; todavia no convierte la RAM del telefono en RAM unificada de Ollama.

Desde `0.4.0`, la APK publica un contrato de runtime local de modelos (`android_model_doctor` y `android_local_generate`). La generacion local devuelve `unavailable` hasta integrar un backend nativo real como llama.cpp u ONNX Runtime.

Desde `0.5.0`, la APK permite autorizar hasta 95% de recursos, solicita `largeHeap` y reporta memoria disponible, memoria total, umbral de baja memoria, `memoryClass`, `largeMemoryClass` y heap Java. Esto no garantiza RAM ilimitada: Android decide cuanta memoria entrega al proceso, pero Tríade ahora puede auditar y planificar con datos reales.

## Build

Requiere JDK 17+ y Android SDK. Desde `android/triade-node`:

```bash
gradle assembleDebug
```

APK esperado:

```text
app/build/outputs/apk/debug/app-debug.apk
```

Cuando exista, se puede publicar como descarga del relay en:

```text
apps/static/triade-android-node.apk
```
