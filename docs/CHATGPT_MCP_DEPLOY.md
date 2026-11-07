# Tríade Ω — conectar el runtime real a ChatGPT mediante MCP

## Arquitectura

ChatGPT (plugin MCP, Bearer privado) -> URL HTTPS `/mcp` -> `apps/chatgpt_mcp_app.py` -> `apps/chatgpt_actions_app.py` -> API original `/health/live`, `/api/runtime/heartbeat`, `/api/runtime/learning-journal` y, solo si se habilita, `/api/run`.

El MCP no instala ni copia la Bodega ni el modelo. Tríade sigue funcionando en su propio servicio. El endpoint de este MCP **no está desplegado** solo por existir en el repositorio.

## Recursos

El SDK MCP v2 se instala separadamente con `requirements-mcp.txt`. No se agrega a los requisitos del runtime principal. El blueprint `render.mcp.yaml` es un servicio HTTP separado que puede consumir el plan gratuito mientras haya cupo; no garantiza 24/7, no sirve modelos grandes y puede suspenderse por inactividad.

## Configurar en Render

1. Crear el servicio a partir del repositorio y la rama revisada, usando el blueprint `render.mcp.yaml` o sus comandos declarados. Mantener separado el servicio principal y el relay público existente.
2. Dejar `TRIADE_ACTIONS_ALLOW_RUN=0`.
3. `TRIADE_ACTIONS_UPSTREAM_URL`: URL HTTPS del runtime original, accesible para Render; **no** usar `127.0.0.1` salvo que ambos servicios corran en el mismo contenedor.
4. `TRIADE_ACTIONS_UPSTREAM_KEY`: valor privado de `TRIADE_API_KEY` cuando se usa esa autenticación en el runtime original. Si el runtime exige otro mecanismo, adaptar con seguridad antes de abrir acceso.
5. `TRIADE_ACTIONS_TOKEN`: token Bearer aleatorio de alta entropía. Render puede generarlo en el blueprint; configurar el mismo valor **dentro de la conexión del plugin** (no publicarlo en Git ni compartirlo por mensajes).
6. Configurar `TRIADE_MCP_PUBLIC_HOST` con el hostname público bare DNS (por ejemplo `triade-mcp.onrender.com`) si Render no proporciona la variable `RENDER_EXTERNAL_HOSTNAME`. El SDK bloquea hosts no incluidos con HTTP 421.
7. Verificar `https://HOST/health` como prueba de liveness del puente. Eso **no** prueba que el runtime original esté activo.

## Conectar en ChatGPT

En **ChatGPT web**: Plugins -> `+` -> Add custom MCP server. Usar nombre `Tríade Ω`, URL `https://HOST/mcp` y configurar Bearer token/autenticación apropiada. Confirmar la advertencia de seguridad, crear e instalar el plugin. Elegir el plugin desde ChatGPT Work o una superficie compatible.

El servidor expone:

- `triade_estado`: consulta salud y actividad real, con resumen acotado.
- `triade_aprendizaje`: consulta un resumen estadístico del aprendizaje y sus límites.
- `triade_ejecutar`: puede escribir en la Bodega del runtime; por defecto retorna bloqueo. Habilitarla **solo después** de respaldar y verificar Bodega, terminar CI, validar acceso e instalar aprobación humana.

La creación e instalación del plugin en la cuenta requieren la acción explícita del titular. Esta rama no instala el plugin por sí sola ni añade un servidor MCP a ChatGPT.

## Pruebas

```bash
pip install -e '.[dev]' -r requirements-mcp.txt
pytest -q tests/test_chatgpt_mcp_app.py tests/test_chatgpt_actions_app.py
```

La suite MCP incluye autenticación, inicialización del protocolo, descubrimiento de herramientas y bloqueo por token ausente. Debe pasar en CI **sobre el SHA final** antes de recomendar un despliegue público.

## Principios de seguridad

- Sin SSH ni comandos shell expuestos.
- Sin endpoint genérico para consultar ni alterar archivos o SQLite.
- Sin escritura ni modificación de credenciales en Git o Google Drive.
- Sin acceso libre a memoria: solo métricas explícitas y respuestas filtradas.
- El MCP no repara por sí mismo bloqueos de workers, CI o aprendizaje autónomo.
- La salud HTTP del puente, la salud del runtime y la validez de un ciclo de aprendizaje son hechos separados.

Documentación oficial de conexión: https://developers.openai.com/plugins/deploy/connect-chatgpt
