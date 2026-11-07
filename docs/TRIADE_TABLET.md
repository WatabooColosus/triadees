# Tríade Ω · Centro de Control para tablet (observatorio público)

Desarrollado por **Agencia Digital Wataboo**.

## Abrir desde Android, iPad o PC

En Chrome, entra a **https://triade-omega-mcp.onrender.com/**. No necesitas
la aplicación de escritorio de ChatGPT ni abrir el complemento para usar
esta primera instancia web.

En la tablet, puedes tocar el menú **⋮ → Agregar a pantalla principal**
(o «Instalar aplicación» cuando el navegador lo ofrezca). La PWA incluye
manifest e interfaz adaptable, con una pantalla sin conexión limitada a
recursos estáticos. El servicio gratuito puede tardar en despertar después
de períodos de inactividad.

## Qué sí funciona

- Interfaz visual con tres núcleos: Neurona Central, Hipotálamo Emocional y
  Bodega (conceptual; sin acceso al almacén original).
- Consulta de estado público en `GET /api/public/status`.
- Consulta de evidencia pública de `main` con API y feed Atom de GitHub en
  `GET /api/public/code`; cuando la fuente falla no se inventa SHA.
- Planificador triádico en `POST /api/public/plan`. Estructura misiones de
  hasta 500 caracteres mediante un procedimiento **determinista y público**.
  No es un modelo LLM y no ejecuta workers.
- Historial de hasta 10 misiones en `localStorage` del navegador; el botón
  Borrar solo elimina ese almacenamiento local.
- MCP original permanece disponible en `POST /mcp` con herramientas
  `triade_estado_publico`, `triade_codigo_publico`,
  `triade_plan_publico`.
- Página, estilos, Javascript, manifiesto SVG y service worker servidos
  directamente por el mismo proceso de Render, sin un segundo servicio.

## Enlace privado al organismo original

La sección **Organismo** incorpora un formulario privado para consultar
solo salud, workers y contadores educativos del runtime original. Requiere
una clave de operador larga configurada en Render y la URL HTTPS real del
runtime. El token no se guarda en la tablet. Este enlace puede estar
no configurado aunque el observatorio público esté en línea.

Consulta `docs/TRIADE_PRIVATE_RUNTIME_LINK.md` para el procedimiento,
los permisos y los límites de verificación.

## Seguridad y límites

- No publiques claves, credenciales ni información privada en el laboratorio:
  es un servicio público.
- No hay conexión automática al Colab original, a Drive ni a la Bodega SQLite.
- No hay ejecución de ciclos educativos en segundo plano desde este panel.
- La salud del MCP no demuestra aprendizaje autónomo. La memoria local en
  el navegador no sustituye la Bodega original.
- Código reutiliza exactamente las funciones del MCP público; las rutas
  web no introducen funciones de escritura.
- Entradas JSON aceptadas exclusivamente: `{"objetivo":"texto"}`, entre 1
  y 500 caracteres; límite de cuerpo 2 KiB. CSP sin scripts remotos,
  anti-framing, respuestas no-cache y sin CORS remoto.
- Archivos estáticos solo de nombres fijos: no lectura arbitraria de archivos
  desde el servidor.

## Pruebas

```bash
pip install -e '.[dev]' -r requirements-mcp.txt
pytest -q tests/test_triade_tablet_app.py tests/test_triade_public_mcp_app.py
node --check apps/tablet_assets/ui.js
node --check apps/tablet_assets/sw.js
```

Para certificar versión desplegada, Render debe indicar **live** en el SHA
esperado y un cliente independiente debe comprobar GET /, las APIs públicas,
las tres llamadas MCP y la ausencia de rutas privadas. El PR se mantiene en
borrador hasta que todos los gates estén verdes y exista revisión final.

## Próxima etapa: organismo real

La conexión con el runtime original exige un endpoint HTTPS estable,
OAuth 2.1 con PKCE para recursos privados, continuidad verificada de la
Bodega, gobernanza de cambios y pruebas de aprendizaje. Ninguno de estos
requisitos se satisface simplemente publicando una interfaz web.
