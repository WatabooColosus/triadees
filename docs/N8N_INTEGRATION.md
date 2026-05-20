# Integración básica n8n · Tríade Ω

## Objetivo

Permitir que n8n envíe mensajes a Tríade Ω mediante HTTP y reciba una respuesta auditable.

---

## Requisitos

- Tríade API corriendo:

```bash
sudo systemctl status triade-api
```

- API key configurada en `triade-api.service`.
- n8n corriendo en la misma PC o en la red local.

---

## Endpoint

```text
POST http://127.0.0.1:8000/triade/run
```

Si n8n está en otra máquina:

```text
POST http://IP_DE_LA_PC:8000/triade/run
```

---

## Nodo HTTP Request

### Method

```text
POST
```

### URL

```text
http://127.0.0.1:8000/triade/run
```

### Headers

```json
{
  "Content-Type": "application/json",
  "X-TRIADE-API-Key": "TU_CLAVE"
}
```

### Body JSON

```json
{
  "text": "{{$json.message}}",
  "source": "n8n",
  "use_ollama": true,
  "hypothalamus_model": "qwen2.5:3b-instruct",
  "central_model": "qwen2.5:3b-instruct"
}
```

---

## Ejemplo con Webhook n8n

1. Crear nodo `Webhook`.
2. Recibir un JSON como:

```json
{
  "message": "Hola Tríade desde n8n"
}
```

3. Conectar a nodo `HTTP Request`.
4. El body del HTTP Request usa:

```json
{
  "text": "{{$json.message}}",
  "source": "n8n-webhook",
  "use_ollama": true
}
```

5. Responder con el campo:

```text
{{$json.response}}
```

---

## Respuesta esperada

Tríade devuelve:

```json
{
  "run_id": "run-...",
  "response": "...",
  "safety": {},
  "report": {},
  "memory_diff": {},
  "models": {},
  "run_path": "runs/run-..."
}
```

---

## Validación con curl equivalente

```bash
curl -X POST http://127.0.0.1:8000/triade/run \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: TU_CLAVE" \
  -d '{
    "text": "Hola Tríade desde n8n",
    "source": "n8n-test",
    "use_ollama": true
  }'
```

---

## Seguridad

- No poner la API key en nodos públicos.
- No publicar workflows con la key visible.
- Usar credenciales de n8n cuando sea posible.
- No exponer Tríade directamente a internet.

---

## Siguiente mejora

Crear workflow exportable `.json` para n8n en fase 1.1.
