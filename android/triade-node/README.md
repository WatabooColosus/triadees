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

Desde `0.7.0`, la pantalla principal permite preparar el host sin copiar rutas manualmente:

- `Doctor LLM local` muestra `bin_dir`, `models_dir`, backend detectado y si `can_run_local_llm` esta activo.
- `Importar llama-cli` abre el selector de archivos de Android y copia el binario seleccionado como `bin/llama-cli`, marcandolo ejecutable.
- `Importar modelo GGUF` abre el selector de archivos y copia el `.gguf` seleccionado a `models/`.

Despues de importar ambos archivos, toca `Doctor LLM local`; si devuelve `can_run_local_llm=true`, el siguiente heartbeat del servicio hara que el `8010` pueda usar el nodo como host LLM Android real.

Desde `0.8.0`, la APK usa modo dedicado: reporta 100% de la CPU/RAM disponible del dispositivo y elimina el selector 60/90/95. Android conserva sus limites reales de bateria, temperatura, memoria por proceso y permisos del sistema.

Permisos expuestos por la app:

- servicio en primer plano y wake lock para mantener el nodo conectado;
- exclusión de optimizacion de bateria, si el usuario la concede;
- acceso amplio a archivos mediante la pantalla de permisos de Android, si el usuario lo concede;
- selector de archivos Android para importar `llama-cli` y `.gguf`.

La APK no pide camara porque la camara no alimenta inferencia LLM ni CPU/RAM/GPU. Si en el futuro un modulo visual necesita camara, debe agregarse como permiso separado y visible.

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
