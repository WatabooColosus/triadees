# Tríade Ω + ChatGPT Actions: puente mínimo y seguro

**Estado**: implementación preparada, no equivale a un despliegue activo ni a que ChatGPT pueda ejecutar modelos por sí solo. La API de Tríade debe estar funcionando en un servicio externo (por ejemplo Colab mientras esté activo o una VPS).

## Arquitectura

ChatGPT (GPT personalizado con Actions) --HTTPS/Bearer--> `apps.chatgpt_actions_app` --HTTPS + `X-Triade-Api-Key`--> API Tríade (`/api/run`, `/api/runtime/heartbeat`, `/api/runtime/learning-journal`).

- Acceso mediante token independiente `TRIADE_ACTIONS_TOKEN`, **nunca** incluido en Git ni en el esquema público.
- Solo se permite HTTPS hacia un runtime remoto, o HTTP a `127.0.0.1`/localhost/`::1`.
- Consultas `status` y `learning`: resúmenes acotados; nunca exponen el contenido bruto de Bodega, ni credenciales.
- Acción `run`: **desactivada por defecto**. Cuando se habilita, puede escribir en la Bodega del runtime original y debe habilitarse solo tras verificar backups, estado y gates. Nunca se ejecuta contra la Bodega desde la pasarela.
- No hay modelo GPT-6 gratuito disponible mediante API por el mero hecho de usar ChatGPT. Sin Ollama o un proveedor de modelos compatible, el runtime original operará en fallback.

## Ejecución local aislada

Instalar `requirements.txt` en un entorno separado. Configurar:

```bash
export TRIADE_ACTIONS_TOKEN='un-secreto-aleatorio-largo'
export TRIADE_ACTIONS_UPSTREAM_URL='http://127.0.0.1:8010'
export TRIADE_ACTIONS_UPSTREAM_KEY='clave-del-runtime-local'
export TRIADE_ACTIONS_ALLOW_RUN=0
uvicorn apps.chatgpt_actions_app:app --host 127.0.0.1 --port 8011
```

Prueba (las credenciales van en cabecera HTTP, no en URL):

```bash
curl -H "Authorization: Bearer $TRIADE_ACTIONS_TOKEN" http://127.0.0.1:8011/actions/status
pytest -q tests/test_chatgpt_actions_app.py
```

## Despliegue opcional en Render

`render.chatgpt.yaml` crea una pasarela nueva, **separada** del relay de nodos. Puede requerir cupo gratuito disponible; no inicia un modelo completo en 512 MB ni mantiene un runtime de Colab activo. Configurar URL HTTPS real del runtime Tríade y clave interna desde el panel seguro de Render. La pasarela no debe apuntar a una URL arbitraria que el cliente determine.

## Conectar a ChatGPT

En un GPT personalizado, configurar una Action con esquema OpenAPI obtenido desde `https://DOMINIO-DE-TU-PASARELA/openapi.json`. En autenticación elegir **API Key**, encabezado `Authorization`, tipo **Bearer**, y registrar el secreto de pasarela. La pasarela no se instala por sí sola dentro de este chat: la conexión y sus credenciales requieren la configuración explícita del titular del GPT.

Cuando la API pública de Tríade responda y la autenticación esté configurada, las Actions pueden consultar el estado real y resumen de aprendizaje. Solo habilitar `TRIADE_ACTIONS_ALLOW_RUN=1` después de revisar los tests, los gates y un respaldo verificable de la Bodega.

## Límites

Sin URL accesible del runtime ni sus credenciales, la pasarela responde error de configuración. Ni GitHub Actions ni Render gratuito proporcionan un servidor continuo de modelos grandes por defecto. Un test simulado de la pasarela **no** certifica integración extremo a extremo; faltan conexión real, autorización en ChatGPT y una prueba frente al runtime vivo.
