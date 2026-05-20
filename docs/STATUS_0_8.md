# Tríade Ω · Estado 0.8

## Nombre de fase

```text
TRIADE_API_SECURITY_AND_N8N_0.8
```

---

## Objetivo

Agregar seguridad local mínima a la API, preparar CORS controlado para n8n y documentar el uso de Tríade Ω como servicio HTTP en red local.

---

## Qué agrega esta fase

- API key opcional mediante variable de entorno `TRIADE_API_KEY`.
- Header de seguridad:

```text
X-TRIADE-API-Key
```

- CORS controlado mediante `TRIADE_CORS_ORIGINS`.
- `.env.example`.
- Tests para validar bloqueo y acceso con API key.
- Documentación base para integración n8n.

---

## Seguridad actual

### Endpoints públicos

```text
GET /health
```

`/health` se mantiene público para diagnóstico básico local.

### Endpoints protegibles

Si `TRIADE_API_KEY` está definida, estos endpoints requieren header:

```text
POST /triade/run
GET  /triade/recall
GET  /triade/doctor
```

---

## Activar API key

En la terminal donde se levanta la API:

```bash
export TRIADE_API_KEY="mi-clave-local-segura"
python triade_digimon.py api
```

O con host LAN:

```bash
export TRIADE_API_KEY="mi-clave-local-segura"
python triade_digimon.py api --host 0.0.0.0 --port 8000
```

---

## Probar con curl

### Health sin key

```bash
curl http://127.0.0.1:8000/health
```

### Run con API key

```bash
curl -X POST http://127.0.0.1:8000/triade/run \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: mi-clave-local-segura" \
  -d '{
    "text": "Run protegido desde API local",
    "source": "curl-secure",
    "use_ollama": false
  }'
```

### Doctor con API key

```bash
curl "http://127.0.0.1:8000/triade/doctor?use_ollama=true" \
  -H "X-TRIADE-API-Key: mi-clave-local-segura"
```

---

## CORS para n8n

Por defecto se permiten:

```text
http://127.0.0.1:5678
http://localhost:5678
```

Para personalizar:

```bash
export TRIADE_CORS_ORIGINS="http://127.0.0.1:5678,http://localhost:5678,http://192.168.0.126:5678"
```

---

## Ejemplo de nodo HTTP Request en n8n

Método:

```text
POST
```

URL:

```text
http://127.0.0.1:8000/triade/run
```

Headers:

```json
{
  "Content-Type": "application/json",
  "X-TRIADE-API-Key": "mi-clave-local-segura"
}
```

Body JSON:

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

## Acceso desde red local

Levantar API escuchando en todas las interfaces:

```bash
python triade_digimon.py api --host 0.0.0.0 --port 8000
```

Desde otra máquina de la red:

```text
http://IP_DE_LA_PC:8000/health
```

Ejemplo si la PC es `192.168.0.126`:

```bash
curl http://192.168.0.126:8000/health
```

---

## Advertencia de seguridad

No exponer esta API directamente a internet todavía.

Antes de exposición externa se requiere:

- Autenticación más robusta.
- HTTPS o túnel seguro.
- Rate limit.
- Logs de acceso.
- Política de permisos.
- Firewall.

---

## Validación local

```bash
cd ~/triadees
source .venv/bin/activate
git pull
pip install -r requirements.txt
pytest

export TRIADE_API_KEY="test-local"
python triade_digimon.py api
```

En otra terminal:

```bash
curl http://127.0.0.1:8000/health

curl -X POST http://127.0.0.1:8000/triade/run \
  -H "Content-Type: application/json" \
  -d '{"text":"Debe fallar sin key","use_ollama":false}'

curl -X POST http://127.0.0.1:8000/triade/run \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: test-local" \
  -d '{"text":"Debe funcionar con key","use_ollama":false}'
```

---

## Estado

```text
TRIADE_API_LOCAL_FASTAPI_0.7 → TRIADE_API_SECURITY_AND_N8N_0.8
```

---

## Siguiente fase sugerida

```text
TRIADE_SYSTEMD_SERVICE_0.9
```

Prioridades:

1. Crear archivo ejemplo `systemd/triade-api.service`.
2. Documentar instalación como servicio 24/7.
3. Agregar script de backup de SQLite.
4. Documentar firewall local.
5. Preparar modo producción local.
