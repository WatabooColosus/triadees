# Triade Node Runtime

Estado objetivo: nodos Android dedicados entregan CPU, RAM disponible y posibles aceleradores locales a Tríade por trabajos sandbox firmados. El puerto `8010` sigue siendo el coordinador local.

## Contrato real

- El nodo Android no suma su RAM al proceso de Ollama en Windows como memoria única. Android ejecuta trabajo propio y devuelve resultados al coordinador.
- El `8010` puede alimentar modelos locales con preproceso, probes, contexto preparado y resultados generados por nodos que soporten runtime nativo.
- La APK recibe tareas y configuración desde `8010`; para cambios de código Java o permisos Android sigue siendo necesaria una APK nueva o un canal de actualización instalado por el usuario.
- La APK no ejecuta comandos arbitrarios. Solo acepta tareas en el sandbox federado.

## Transporte firmado

Endpoints locales:

- `GET /api/federation/transport/doctor`
- `POST /api/federation/transport/next`
- `POST /api/federation/transport/result`

Cada mensaje usa un sobre:

```json
{
  "node_id": "local-node",
  "timestamp": 1760000000,
  "nonce": "nonce-unico",
  "payload": {"request": "next_job"},
  "signature": "hmac-sha256-hex",
  "public_key": "identidad-auditable-del-nodo",
  "signature_alg": "hmac-sha256"
}
```

La firma se calcula sobre:

```text
node_id.timestamp.nonce.canonical_payload
```

El secreto actual es `node_token`, emitido durante pairing. `public_key` queda registrado para auditoría y migración futura a firma asimétrica.

## Sandbox

Tareas permitidas:

- `echo`
- `sha256`
- `browser_benchmark`
- `preprocess_text`
- `federated_inference_probe`
- `android_model_doctor`
- `android_local_generate`

No existe endpoint para shell remoto, instalación silenciosa, cámara, root ni administración del sistema. Si se necesita instalar runtime nativo, el usuario debe aceptar el APK y los permisos de Android de forma explícita.

## Runtime Android

La APK reporta:

- CPU total y CPU autorizada.
- RAM disponible, RAM total y heap máximo real del proceso Android.
- `largeHeap`, foreground service y estado de memoria baja.
- Backend de modelo local si existe.

Para que Android hospede LLM real se necesita backend nativo dentro de la app o librería compatible empaquetada. Sin eso, Android alimenta al modelo local mediante tareas distribuidas, no mediante inferencia local completa.

## Actualización sin reinstalar APK

Permitido:

- Cambiar tareas, manifiesto runtime, configuración y assets descargables desde `8010`.
- Descargar scripts o binarios auxiliares a almacenamiento autorizado por Android.

No permitido por Android estándar:

- Reemplazar código Java/Kotlin de la APK sin instalar una APK nueva.
- Instalar Termux o paquetes del sistema desde otra app sin intervención del usuario.
- Saltar límites térmicos, heap, permisos o políticas de batería.

## APK y artefactos

El APK debug no se versiona en Git. La fuente vive en `android/triade-node/` y el binario se genera con el workflow `Build Android Node APK`, que publica el artifact `triade-android-node-debug`.

Para servirlo desde `8010` en una instalación local, copia el APK generado a:

```text
apps/static/triade-android-node.apk
```

Si el archivo no existe, `/downloads/triade-android-node.apk` responde 404 con un mensaje claro.
