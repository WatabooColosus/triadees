# Tríade Ω · Estado 1.1

## Nombre de fase

```text
TRIADE_N8N_WORKFLOW_1.1
```

## Objetivo

Conectar n8n con Tríade API en entorno local controlado.

## Archivos agregados

```text
n8n/triade_basic_webhook_workflow.json
docs/N8N_SYSTEMD_SERVICE.md
docs/GITHUB_CI_TRIAD.md
```

## Flujo base

```text
Webhook n8n → HTTP Request → Tríade API → respuesta JSON
```

## Validación local

1. Confirmar Tríade API:

```bash
sudo systemctl status triade-api
curl http://127.0.0.1:8000/health
```

2. Confirmar n8n:

```bash
which n8n
n8n --version
```

3. Levantar n8n o instalarlo como servicio siguiendo:

```text
docs/N8N_SYSTEMD_SERVICE.md
```

4. Importar en n8n el archivo:

```text
n8n/triade_basic_webhook_workflow.json
```

5. Configurar la variable local `TRIADE_API_KEY` en el entorno de n8n con la misma clave del servicio Tríade.

6. Ejecutar el workflow desde la interfaz de n8n y revisar que Tríade devuelva un JSON con:

```text
run_id
response
memory_diff
models
run_path
```

## Criterio de cierre

La fase se considera validada cuando:

- `triade-api.service` está activo.
- n8n está activo.
- El workflow importa correctamente.
- Un mensaje enviado desde n8n genera un run en Tríade.
- Los contadores de `doctor` aumentan.

## Siguiente fase

```text
TRIADE_N8N_PRODUCTION_WORKFLOWS_1.2
```
