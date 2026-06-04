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

Desde `0.4.0`, la APK publica un contrato de runtime local de modelos (`android_model_doctor` y `android_local_generate`).

Desde `0.5.0`, la APK permite autorizar hasta 95% de recursos, solicita `largeHeap` y reporta memoria disponible, memoria total, umbral de baja memoria, `memoryClass`, `largeMemoryClass` y heap Java. Esto no garantiza RAM ilimitada: Android decide cuanta memoria entrega al proceso, pero Tríade ahora puede auditar y planificar con datos reales.

Desde `0.6.0`, la APK puede hospedar LLM local si el dispositivo tiene:

- un binario nativo ejecutable `llama-cli`, `llama-cli-arm64-v8a` o `main` en el directorio `bin/` de la app;
- al menos un modelo `.gguf` en el directorio `models/` de la app.

El doctor devuelve `can_run_local_llm=true` solo cuando ambas piezas existen. Si falta cualquiera, el nodo sigue sirviendo para jobs de CPU/preproceso, pero no cuenta como host LLM real. La generacion usa `ProcessBuilder` contra el binario nativo y limita hilos/tokens segun el job enviado desde `8010`.

Rutas internas reportadas por `android_model_doctor`:

```text
bin_dir
models_dir
backend_executable
install_contract
```

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
