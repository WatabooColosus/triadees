# Tríade Ω — enlace privado al organismo original (etapa 1)

Creado por **Agencia Digital Wataboo**.

El panel de la tablet `https://triade-omega-mcp.onrender.com/` añade
una sección **Organismo**. Permite consultar por HTTPS **solo estado y
métricas de aprendizaje** del runtime original, si la instancia original
está conectada y respondiendo. No aloja modelos, no copia la Bodega y
no ejecuta ciclos de aprendizaje.

## Flujo de datos

```
Chrome tablet -- HTTPS, Bearer efímero --> Render triade-omega-mcp
       |                                |
       |                                +-- /api/private/connection (autenticación/config.)
       |                                +-- /api/private/status -- HTTPS --> runtime original
       |                                |       GET /health/live
       |                                |       GET /api/runtime/heartbeat
       |                                +-- /api/private/learning -- HTTPS --> runtime original
       |                                        GET /api/runtime/learning-journal
       |
       +-- sin escribir contraseñas en localStorage, URL o Git
```

Las tres rutas requieren autenticación `Authorization: Bearer`. La
configuración de las credenciales es manual y segura dentro de Render.
La página almacena el token **solo temporalmente en memoria JS**,
descartándolo al desconectar o cerrar la página. No lo copies a
conversaciones, ni a capturas de pantalla ni al laboratorio público.

## Condiciones necesarias

1. **Runtime original encendido**, por ejemplo el proceso en Colab o
   un servidor propio ejecutando `apps.single_port_app:app`.
2. **Una URL HTTPS pública estable y controlada** del runtime original,
   protegida por la autenticación de Tríade. El `localhost:8010` de
   Colab no puede consultarse directamente desde Render.
3. En el servicio Render `triade-omega-mcp` → **Environment**, configurar
   en campos secretos (no en Git):
   - `TRIADE_ACTIONS_TOKEN`: clave aleatoria de **32 caracteres o más**.
   - `TRIADE_ACTIONS_UPSTREAM_URL`: URL HTTPS de la API original, sin
     subruta, secretos ni query parameters (ej. `https://runtime.example.org`).
   - `TRIADE_ACTIONS_UPSTREAM_KEY`: solo si el runtime usa
     `X-Triade-Api-Key` y la aplicación original está configurada
     para comprobar esa clave.
   - `TRIADE_ACTIONS_ALLOW_RUN=0` (no habilitar escrituras).
4. Publicar la configuración mediante el flujo de **Deploy** de Render.
   El servicio tiene despliegues automáticos desactivados.
5. En la tablet, abrir la sección **Organismo** e introducir la clave
   de operador únicamente en el campo privado. Pulsa **Verificar acceso**;
   si la URL está configurada, el panel consultará estado y bitácora.

Si no hay endpoint original accesible, se mostrará «Falta runtime»,
«Endpoint no configurado» o una conexión no disponible. Es un estado
legítimo: no es un error que deba ocultarse ni un aprendizaje falsificado.

## Protecciones verificadas

- Token inexistente o de longitud insuficiente: error seguro.
- Token incorrecto: `401`, sin acceso a upstream.
- Solo `GET`, únicamente tres endpoints fijos. No se exponen rutas
  para escribir, ejecutar, arrancar, reiniciar workers o consultar Bodega.
- Las métricas proceden de un conjunto cerrado de campos conocidos
  de `triade.core.learning_journal.build_learning_journal`.
- Nunca se muestran `latest_events`, `latest_learning_candidates`,
  `input_summary`, `content`, referencias, títulos o registros del
  almacén original. Las métricas no certifican aprendizaje.
- No se guardan tokens o diagnósticos privados en el almacenamiento
  de la tablet; solo las misiones públicas quedan en `localStorage`.
- Si upstream no responde, se muestra indisponibilidad y se evita
  presentar contadores anteriores como actuales.
- El endpoint público `/api/public/status` sigue diciendo
  `runtime_original_conectado=false`, porque la salud privada nunca
  se publica anónimamente.
- `full_runtime_verified=false`, `full_learning_certified=false`
  y `writes_enabled=false` hasta certificación independiente.

## Limitación de Colab

Google Drive conserva archivos, pero acceder a Drive **no proporciona**
conexión a un kernel Colab activo. Un entorno Colab se puede apagar o
perder su URL temporal; no garantiza disponibilidad continua.
Nunca exponer sin autorización una URL de Colab que permita ejecutar
comandos o consultar datos de memoria. Preferir un backend estable
controlado, o un adaptador de telemetría solo de salida con
autenticación y datos agregados para sesiones temporales.

## Pruebas

```bash
pip install -e '.[dev]' -r requirements-mcp.txt
pytest -q tests/test_triade_private_runtime.py tests/test_triade_tablet_app.py
```

Se prueba la autenticación fail-closed, la selectividad de rutas GET,
el filtrado de métricas frente a respuestas con contenido privado y
la permanencia de las herramientas MCP públicas sin acceso a secretos.

**Una API original accesible no demuestra por sí sola continuidad de
Bodega, sesiones educativas exitosas ni aprendizaje generalizado.**
