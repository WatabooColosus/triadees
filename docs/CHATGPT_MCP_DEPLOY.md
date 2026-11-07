# Tríade Ω — Plugin ChatGPT y observatorio seguro (v0.2)

Creado por **Agencia Digital Wataboo**.

## Lo que está desplegado y probado

- Render gratuito: `https://triade-omega-mcp.onrender.com/mcp`.
- Proceso: `apps.chatgpt_mcp_app:app` sirve exclusivamente
  `apps.triade_public_mcp_app.build_public_app()`.
- Servicio MCP sin login solo para datos **públicos**. No conecta el runtime
  original ni incluye herramientas para escribir/leer SQLite, Drive, Colab,
  tokens privados o ejecutar ciclos de Tríade.
- Herramientas: `triade_estado_publico`, `triade_codigo_publico`,
  `triade_plan_publico`.
- La consulta de GitHub puede quedar degradada por limitaciones de acceso
  HTTP desde la nube. `verified: false` significa que el SHA no se confirmó.
- Pruebas automatizadas: `tests/test_triade_public_mcp_app.py` y
  `.github/workflows/triade-public-mcp-live-smoke.yml`.
- Plugin privado de ChatGPT `triade-omega`, versión 0.2.0, con una
  habilidad bajo `plugin/skills/` y conexión `plugin/mcp.json`.
  Importar y actualizar un plugin no lo instala necesariamente en cada sesión.

## Cómo usar la instancia existente

1. Entra al [plugin Tríade Ω](https://chatgpt.com/plugins/plugins_6aee9dc8916c8191a1fc03de14f63558).
2. Selecciona **Instalar** si todavía aparece como no instalado.
3. Inicia una nueva conversación en una superficie de ChatGPT compatible
   con plugins (por ejemplo, Work). Selecciona `@triade-omega`.
4. Solicita: «Consulta el estado del observatorio Tríade y el último
   commit público. Indica cualquier fuente no disponible».
5. Verifica que la herramienta ejecutada sea MCP y el resultado indique
   `runtime_original_conectado: false`, no un organismo completo ficticio.

**No hace falta agregar otro MCP manualmente**: el paquete ya contiene
`mcp.json` con el endpoint público.

## Por qué no se debe conectar el runtime con un token manual

ChatGPT espera **OAuth 2.1 authorization code + PKCE S256** para las
herramientas privadas, con metadata de recurso protegido y servidor de
autorización. Un Bearer fijo escrito en Render por sí solo no completa
la conexión privada. La pasarela histórica `build_app()` está conservada,
pero no se publica como ruta accesible en el servicio actual.

Referencias oficiales:
- https://developers.openai.com/plugins/build/auth
- https://developers.openai.com/plugins/deploy/connect-chatgpt

## Qué se necesita para Tríade real

- Endpoint estable HTTPS de la instancia original, con permisos de lectura
  claramente delimitados y autenticación OAuth bien implementada.
- Backups y controles de continuidad de Bodega SQLite/Drive; Render free no
  sustituye el almacenamiento persistente original.
- Verificación de workers, ciclo educativo real, evaluador independiente,
  pruebas de aprendizaje y gates CI antes de declarar una sesión efectiva.
- La acción de ejecución/escritura permanecerá desactivada hasta autorización
  específica, autenticación y comprobación de seguridad.

## Seguridad

No publiques secretos en Git ni chat. No fuerces un gate de aprendizaje
para mejorar estadísticas. El observatorio puede operar sin autenticación
porque nunca recibe datos privados ni ejecuta acciones con efectos laterales.
