# PR9 Audit Report

## Resumen ejecutivo

Auditoria tecnica del PR #9 `codex/auditoria-evolutiva-triade` contra `main`.

Resultado: **merge condicionado**.

El PR queda mucho mas estable despues de la correccion de higiene y seguridad aplicada en esta auditoria:

- `pytest -q` pasa.
- CLI base (`doctor`, `run --no-ollama`, `learn doctor`, `federate doctor`) responde OK.
- Se eliminaron archivos basura y binarios/DBs locales versionados.
- El APK debug deja de estar versionado y pasa a ser artifact de GitHub Actions.
- Relay publico y pairing local ya no tienen tokens por defecto seguros ni exponen pairing token en pagina/script.
- El admin del agente movil queda desactivado por defecto.

Condicion antes de merge: ejecutar CI en GitHub y confirmar que el workflow Android publica el artifact `triade-android-node-debug`.

## Archivos revisados

- `.github/workflows/android-node-apk.yml`
- `.github/workflows/python-tests.yml`
- `.gitignore`
- `apps/public_relay_app.py`
- `apps/mobile_node_agent.py`
- `apps/federation_pairing_app.py`
- `apps/single_port_app.py`
- `apps/static/`
- `android/triade-node/**`
- `triade/federation/federation.py`
- `triade/federation/contracts.py`
- `triade/federation/relay_client.py`
- `triade/learning/pipeline.py`
- `triade/memory/schemas.sql`
- `triade_digimon.py`
- `tests/test_public_relay_app.py`
- `tests/test_mobile_node_agent.py`
- `tests/test_federation_pairing_app.py`
- `tests/test_single_port_app.py`
- documentos de federacion, relay, Android runtime y agente movil.

## Problemas encontrados

### P0 corregidos

1. Archivos basura versionados:
   - `nonexistent_file.txt`
   - `not_exist.txt`
   - `estructura.txt`

2. DB local versionada:
   - `backups/triade-before-systemd.db`

3. APK debug versionado:
   - `apps/static/triade-android-node.apk`

4. `.gitignore` permitia versionar especificamente el APK debug:
   - `!apps/static/triade-android-node.apk`

5. Relay publico tenia tokens por defecto conocidos:
   - `triade-public-pair`
   - `triade-public-admin`

6. Portal de pairing exponia token de emparejamiento en `/admin` y en `termux-bootstrap.sh`.

7. Agente movil tenia `admin_enabled=True` por defecto, lo que dejaba endpoints de lectura de archivos/comandos allowlist disponibles si el token local era debil.

### Riesgos observados

- El relay web legado usa `node_token` en query string para `/api/jobs/next`; esto puede filtrarse en logs HTTP. No bloquea merge si el despliegue esta detras de HTTPS y admin token fuerte, pero conviene migrarlo a transporte firmado tambien.
- Los jobs compute de relay/single port quedan en colas locales, no en `federated_exchange_log`. Los intercambios de conocimiento si pasan por `Federation.receive_exchange` con Safety, log y LearningPipeline.
- El APK Android actual alimenta con jobs (`preprocess_text`, `sha256`, benchmark, probes) y no convierte la RAM Android en RAM unica para Ollama. Esto esta documentado como estado real.

## Cambios aplicados

- Eliminados del control de versiones:
  - `nonexistent_file.txt`
  - `not_exist.txt`
  - `estructura.txt`
  - `backups/triade-before-systemd.db`
  - `apps/static/triade-android-node.apk`

- `.gitignore` reforzado:
  - ignora APKs en `apps/static/`
  - ignora DBs SQLite en `backups/`
  - mantiene ignorados tokens locales, `.env`, `.venv`, builds Android y estados locales.

- Workflow Android:
  - ahora corre tambien en `pull_request`.
  - `upload-artifact` falla si no encuentra APK.
  - artifact esperado: `triade-android-node-debug`.

- `apps/public_relay_app.py`:
  - sin tokens por defecto.
  - `/health` informa si pairing/admin estan configurados.
  - registro responde 503 si falta `TRIADE_RELAY_PAIRING_TOKEN`.
  - admin responde 503 si falta `TRIADE_RELAY_ADMIN_TOKEN`.

- `apps/federation_pairing_app.py`:
  - sin token por defecto.
  - `/admin` ya no muestra `PAIRING_TOKEN`.
  - bootstrap Termux ya no incrusta `PAIRING_TOKEN`.
  - pairing responde 503 si falta `TRIADE_PAIRING_TOKEN`.

- `apps/mobile_node_agent.py`:
  - `admin_enabled=False` por defecto.
  - token local aleatorio si no se define `TRIADE_NODE_TOKEN`.
  - `--admin-root` habilita admin de forma explicita.

- Tests actualizados/agregados:
  - relay exige tokens configurados.
  - pairing no expone token en HTML/script.
  - agente movil admin desactivado por defecto.
  - APK servido solo si artifact existe localmente.

- Documentacion actualizada:
  - `docs/TRIADE_NODE_RUNTIME.md`
  - `docs/PUBLIC_RELAY_DEPLOYMENT.md`
  - `docs/MOBILE_NODE_AGENT.md`

## Tests ejecutados

Comandos:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_public_relay_app.py tests\test_federation_pairing_app.py tests\test_mobile_node_agent.py tests\test_single_port_app.py::test_single_port_android_apk_missing_until_artifact_is_copied tests\test_single_port_app.py::test_single_port_serves_android_apk_when_artifact_exists -q
.\.venv\Scripts\python.exe -m pytest -q
```

Resultado:

- Tests enfocados: OK.
- Suite completa: OK.
- Advertencia unica: `StarletteDeprecationWarning` por `fastapi.testclient`/`httpx`, no bloqueante.

Validaciones CLI:

```powershell
.\.venv\Scripts\python.exe triade_digimon.py doctor --no-ollama
.\.venv\Scripts\python.exe triade_digimon.py run "Prueba PR9 auditoria sin Ollama" --no-ollama
.\.venv\Scripts\python.exe triade_digimon.py learn doctor
.\.venv\Scripts\python.exe triade_digimon.py federate doctor
```

Resultado:

- `doctor`: OK.
- `run --no-ollama`: OK, run auditable creado.
- `learn doctor`: OK, LearningPipeline reporta `identity_core_protected=true`.
- `federate doctor`: OK, permisos prohibidos listados y `auto_consolidation=false`.

## Resultado de APK

Decision: **no versionar APK debug en Git**.

Validacion local del artifact equivalente al workflow:

- Archivo local generado por Gradle:
  - `android/triade-node/app/build/outputs/apk/debug/app-debug.apk`
- Tamano:
  - `29553` bytes
- SHA256:
  - `3E0551A31605089A2F3F5F646C2E35BC3857B11E5F13A659FA18FC73AED3F33A`
- Estructura ZIP/APK inspeccionada:
  - `META-INF/com/android/build/gradle/app-metadata.properties`
  - `classes.dex`
  - `classes2.dex`
  - `AndroidManifest.xml`
  - `resources.arsc`

Workflow revisado:

- `.github/workflows/android-node-apk.yml`
- compila con Java 17, Android SDK y Gradle 8.10.2.
- sube artifact `triade-android-node-debug`.
- ahora corre en `pull_request`.
- `if-no-files-found: error`.

Pendiente externo antes de merge: confirmar en GitHub Actions que el artifact `triade-android-node-debug` se genero en el PR.

## Seguridad

### Confirmado

- `apps/public_relay_app.py`:
  - admin requiere Bearer token.
  - pairing requiere token configurado.
  - no expone archivos locales ni DBs.
  - jobs permitidos estan limitados por Pydantic a tareas sandbox.

- `apps/mobile_node_agent.py`:
  - endpoints de capacidades/config/jobs requieren Bearer token.
  - admin desactivado por defecto.
  - lectura de archivos limitada a `admin_root`.
  - comandos limitados a allowlist; no hay endpoint de shell arbitraria.

- `apps/federation_pairing_app.py`:
  - pairing requiere token configurado.
  - permisos se intersectan con allowlist minima.
  - permisos prohibidos siguen bloqueados por `Federation.register_node`.
  - ya no publica token en `/admin` ni en bootstrap.

- `triade/federation/federation.py`:
  - bloquea permisos prohibidos:
    - `read_full_memory`
    - `write_stable_memory`
    - `modify_identity_core`
    - `execute_system_commands`
    - `access_private_files`
    - `access_credentials`
  - nodos pausados/revocados no intercambian.
  - intercambios entrantes pasan por decision Safety.
  - todo intercambio de conocimiento queda en `federated_exchange_log`.
  - conocimiento recibido entra a `learning_queue` como `candidate`.
  - `consolidated=false` por diseno.

- `triade/learning/pipeline.py`:
  - no escribe en `identity_core`.
  - consolidacion exige `verified`, `approved_by`, `source_ref` y riesgo no critical.

### No expuesto

No se encontro endpoint que exponga directamente:

- `identity_core`
- DB SQLite local
- `.env`
- claves `.pem`/`.key`
- archivos privados fuera de `admin_root`
- ejecucion arbitraria de comandos
- consolidacion automatica de aprendizaje recibido

## Arquitectura

Confirmado estable:

- CLI `triade_digimon.py run`
- `doctor`
- `learn`
- `federate`
- `apps/single_port_app.py`

Federation local mantiene:

- permisos minimos por allowlist;
- permisos prohibidos bloqueados;
- pausa/revocacion de nodos;
- logs en `federated_exchange_log`;
- entrada a `learning_queue`;
- LearningPipeline como candidato, no consolidacion automatica.

## Riesgos pendientes

1. Confirmar artifact remoto de GitHub Actions en PR #9.
2. Migrar `/api/jobs/next?node_token=...` del relay publico a transporte firmado o header Bearer para evitar tokens en query string.
3. Definir si los jobs compute deben tener una tabla de auditoria persistente propia, separada de `federated_exchange_log`.
4. Revisar con el dueno del proyecto si `Dockerfile`, `Procfile`, `railway.json` y `render.yaml` deben vivir en este PR o separarse; no son inseguros, pero amplian superficie de despliegue.

## Recomendacion final

**Merge condicionado.**

Condiciones:

1. GitHub Actions debe pasar `Python Tests`.
2. GitHub Actions debe ejecutar `Build Android Node APK`.
3. El artifact `triade-android-node-debug` debe existir y contener `app-debug.apk`.
4. Mantener fuera del repo APKs, DBs locales, tokens, estados locales y basura.

No recomiendo merge directo hasta verificar el artifact remoto del APK en Actions.
