# Android Node · Compilacion en VS Code y prueba contra 8010

Esta guia deja el flujo operativo para construir la APK `Triade Android Node`, copiarla al servidor local `8010`, instalarla en un dispositivo Android real y validar registro, heartbeat y jobs federados.

## 1. Objetivo

El nodo Android no suma su RAM al proceso de Ollama como memoria unica. Su funcion actual es actuar como worker autorizado:

- registrarse contra el `8010` local o relay publico;
- reportar capacidades reales del dispositivo;
- mantener heartbeat;
- tomar jobs sandbox;
- ejecutar tareas como `browser_benchmark`, `preprocess_text`, `android_model_doctor` y, si existe runtime nativo, `android_local_generate`.

## 2. Archivos importantes

```text
android/triade-node/                         # Fuente Android
android/triade-node/app/build/outputs/apk/debug/app-debug.apk
apps/static/triade-android-node.apk          # APK servida por 8010
apps/static/android-runtime/llama-cli         # Runtime opcional Android
apps/static/android-runtime/triade-base.gguf  # Modelo GGUF opcional
.github/workflows/android-node-apk.yml        # GitHub Action para construir APK
```

El APK final no se versiona normalmente porque `.gitignore` ignora `apps/static/*.apk`. Si se necesita servir desde `8010`, se copia manualmente a `apps/static/triade-android-node.apk`.

## 3. Compilar localmente en VS Code

### 3.1 Requisitos

En el PC:

- VS Code
- JDK 17+
- Android SDK instalado
- Gradle disponible, o usar el Gradle configurado por Android Studio/VS Code

Comprobar:

```bash
java -version
gradle -v
```

### 3.2 Abrir proyecto

Abrir en VS Code la carpeta raiz del repo:

```bash
cd ~/triadees
code .
```

La app Android esta en:

```text
android/triade-node
```

### 3.3 Build debug

Desde terminal de VS Code:

```bash
cd ~/triadees
gradle -p android/triade-node assembleDebug
```

APK esperado:

```text
android/triade-node/app/build/outputs/apk/debug/app-debug.apk
```

### 3.4 Publicar APK para descarga desde 8010

```bash
cd ~/triadees
mkdir -p apps/static
cp android/triade-node/app/build/outputs/apk/debug/app-debug.apk apps/static/triade-android-node.apk
ls -lah apps/static/triade-android-node.apk
```

## 4. Compilar con GitHub Actions

Workflow:

```text
.github/workflows/android-node-apk.yml
```

Ruta en GitHub:

```text
Actions -> Build Android Node APK -> Run workflow
```

Artifact generado:

```text
triade-android-node-debug
```

Despues de descargar y descomprimir el artifact, copiar el APK al repo local:

```bash
cd ~/triadees
mkdir -p apps/static
cp /ruta/del/artifact/app-debug.apk apps/static/triade-android-node.apk
```

## 5. Levantar 8010 en LAN

El servidor debe escuchar en toda la red, no solo en localhost:

```bash
cd ~/triadees
source .venv/bin/activate
export PYTHONPATH=.
uvicorn apps.single_port_app:app --host 0.0.0.0 --port 8010
```

Debe verse:

```text
Uvicorn running on http://0.0.0.0:8010
```

IP actual usada en esta maquina:

```text
http://192.168.31.135:8010
```

Si la IP cambia, obtenerla con:

```bash
hostname -I
```

## 6. Probar desde el PC

```bash
curl http://127.0.0.1:8010/health
curl http://192.168.31.135:8010/health
curl -I http://192.168.31.135:8010/downloads/triade-android-node.apk
curl http://127.0.0.1:8010/api/federation/resource-lease
```

`/downloads/triade-android-node.apk` debe devolver `200 OK`. Si devuelve `404`, falta `apps/static/triade-android-node.apk`.

## 7. Probar desde el celular

En el navegador del celular, abrir:

```text
http://192.168.31.135:8010/health
```

Luego probar descarga:

```text
http://192.168.31.135:8010/downloads/triade-android-node.apk
```

Si no abre desde el celular:

1. Confirmar que PC y celular estan en la misma red.
2. Confirmar que Uvicorn esta en `--host 0.0.0.0`.
3. Revisar firewall:

```bash
sudo ufw status
sudo ufw allow 8010/tcp
sudo ufw reload
```

## 8. Configurar APK

En la APK, la URL debe incluir protocolo:

```text
http://192.168.31.135:8010
```

No usar:

```text
192.168.31.135:8010
127.0.0.1:8010
localhost:8010
https://192.168.31.135:8010
```

Desde Android, `127.0.0.1` apunta al celular, no al PC.

Despues de configurar URL:

1. Registrar/conectar nodo.
2. Activar servicio en primer plano.
3. Permitir optimizacion de bateria si Android pregunta.
4. Mantener la notificacion visible del servicio.

## 9. Validar registro real

Mientras se activa la APK, mirar la terminal de Uvicorn. Deben aparecer solicitudes como:

```text
POST /api/register
POST /api/heartbeat
GET /api/jobs/next
```

Revisar tokens locales:

```bash
cd ~/triadees
cat triade/memory/local_node_tokens.json
```

Si el archivo no existe o esta vacio, la APK no hizo registro contra `/api/register`.

Revisar pulso:

```bash
curl http://127.0.0.1:8010/api/system/pulse
curl http://127.0.0.1:8010/api/federation/resource-lease
```

Resultado esperado cuando conecta:

```json
{
  "totals": {
    "devices": 1,
    "direct_lan_devices": 1
  }
}
```

## 10. Probar backend con nodo falso

Si la APK no registra, validar que el backend si acepta nodos:

```bash
curl -X POST http://127.0.0.1:8010/api/register \
  -H "Content-Type: application/json" \
  -d '{"display_name":"test-node","capabilities":{"native_android":true,"online":true,"federation_complete":true,"allowed_tasks":["browser_benchmark","preprocess_text"],"cpu_count":2,"cpu_authorized_count":2,"ram_available_gb":2,"ram_authorized_gb":2}}'
```

Luego:

```bash
curl http://127.0.0.1:8010/api/federation/resource-lease
```

Si aparece `devices: 1`, el backend esta bien y el problema esta en la APK, URL, permisos o servicio Android.

## 11. Probar job de benchmark

Cuando el nodo real aparezca en `resource-lease`:

```bash
curl -X POST "http://127.0.0.1:8010/api/local-federation/benchmark?seconds=1&wait_timeout=20"
```

Resultado esperado:

```json
{
  "status": "ok",
  "node_id": "...",
  "job": {
    "status": "completed"
  }
}
```

## 12. Diagnostico comun

### Caso A: `/health` abre en PC pero no en celular

Problema de red/firewall/host.

Solucion:

- usar `--host 0.0.0.0`;
- permitir puerto `8010`;
- confirmar misma red WiFi/LAN.

### Caso B: `/health` abre en celular pero APK no registra

Problema de configuracion o servicio APK.

Revisar:

- URL exacta con `http://`;
- permisos de servicio en primer plano;
- bateria sin restriccion;
- logs de Uvicorn;
- si aparece `POST /api/register`.

### Caso C: registra pero `resource-lease` sigue en cero

El nodo existe pero sus capacidades no cumplen filtro de worker.

Debe reportar al menos:

```json
{
  "native_android": true,
  "online": true,
  "federation_complete": true,
  "allowed_tasks": ["browser_benchmark", "preprocess_text"],
  "cpu_authorized_count": 1,
  "ram_authorized_gb": 1
}
```

### Caso D: APK descarga pero no hostea LLM

Normal. Para host LLM Android real faltan dos piezas dentro de la app:

```text
bin/llama-cli
models/triade-base.gguf
```

Se valida con `android_model_doctor` y debe devolver `can_run_local_llm=true`.

## 13. Estado esperado por fases

1. APK descarga desde `8010`.
2. APK instala y abre.
3. APK registra `/api/register`.
4. APK envia heartbeat.
5. `resource-lease` muestra `devices >= 1`.
6. Benchmark local completa.
7. Preprocess local completa.
8. Doctor LLM local detecta runtime si existe.
9. `android_local_generate` solo funciona si hay `llama-cli` y `.gguf` reales.

## 14. Nota de seguridad

La APK no debe ejecutar shell remoto ni comandos arbitrarios. Solo jobs sandbox definidos por Tríade. Cualquier capacidad nueva debe pasar por revision humana, tests y evidencia de run.
