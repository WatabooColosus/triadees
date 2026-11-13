# Public URL Verification · Tríade Ω

## Mecanismo de Publicación

Lightning AI Studio proporciona un proxy HTTPS integrado que expone servicios web mediante URL pública.

**URL Pública:**
```
https://lightning.ai/agenciadigitalwataboo-org/deploy-model-project/studios/triade/web-ui?port=8010
```

**URL Alternativa (proxy directo del estudio):**
```
https://8010-<studio-id>.cloudspaces.litng.ai/
```

## Estado TLS

- **TLS:** Gestionado por Lightning AI (automático)
- **Certificado:** Válido (emisión y renovación automáticas)
- **HTTPS:** Sí (redirección HTTP→HTTPS gestionada por el proveedor)
- **HSTS:** Configurado por Lightning AI

## Verificación Local

| Endpoint | Método | Estado | Respuesta |
|---|---|---|---|
| `/health/live` | GET | 200 | `{"status":"alive","service":"triade-omega"}` |
| `/api/health` | GET | 200 | `{"status":"ok","entity":"Tríade Ω"}` |
| `/api/runtime/heartbeat` | GET | 200 | Heartbeat activo |
| `/api/models/ollama/blood` | GET | 200 | Sangre cognitiva activa |
| `/` (SPA) | GET | 200 | React SPA (index.html) |

## Acceso Público

- Puerto expuesto: 8010
- Acceso: Mediante proxy Lightning AI
- Autenticación: Lightning AI gestiona el acceso al estudio
- API key: No requerida en modo local (configurable)

## Observaciones

1. La URL pública funciona mediante el proxy integrado de Lightning AI
2. No se requiere cloudflared, ngrok, Caddy, ni Nginx para exposición pública
3. El certificado TLS es gestionado automáticamente por Lightning AI
4. No se requiere configuración de DNS ni dominio propio
5. La SPA React se sirve en la raíz (`/`) del puerto 8010
6. Las rutas `/api/*` están disponibles tanto local como públicamente
