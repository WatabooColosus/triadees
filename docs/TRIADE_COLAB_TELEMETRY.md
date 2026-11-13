# Tríade Ω — telemetría saliente desde Colab

**Objetivo**: observar el organismo original desde el Centro de Control de la
tablet sin exponer un puerto HTTP de Colab ni trasladar su Bodega a Render.

## Estado de la arquitectura

- El receptor `apps/triade_colab_telemetry.py` acepta únicamente resúmenes
  validados en `POST /api/telemetry/ingest`.
- El visor `GET /api/private/telemetry` requiere la clave de operador
  `TRIADE_TABLET_OPERATOR_TOKEN`, independiente del token emisor.
- La memoria del receptor es **volátil**: solo conserva el último informe en
  RAM de Render. Después de cinco minutos sin datos se declara `stale` y no
  devuelve los contadores antiguos como actuales.
- Los únicos campos admitidos son booleanos de estado, contador de pulso,
  identificador corto del modo y contadores educativos agregados.
- Todos los informes dicen `runtime_identity_certified=false` y
  `full_learning_certified=false`: una declaración autenticada no equivale
  a certificación independiente.

## Configuración una sola vez

En el servicio Render `triade-omega-mcp`, sección Environment:

1. Mantener `TRIADE_TABLET_OPERATOR_TOKEN` con su valor privado largo.
2. Crear `TRIADE_TELEMETRY_INGEST_TOKEN` con **otra clave aleatoria de
   mínimo 32 caracteres**; no usar la misma clave de operador.
3. Guardar y desplegar el servicio. No pegar ninguna de estas claves en
   GitHub, comentarios o conversaciones.

En Google Colab, guardar la misma clave emisor en **Secretos** bajo
`TRIADE_TELEMETRY_INGEST_TOKEN`. Esa sección es privada de Colab y debe
tener habilitado el acceso de la notebook.

El asistente puede configurar Render y editar código a través de los
conectores autorizados, pero **no puede iniciar el kernel interactivo de
Google Colab** con las herramientas disponibles. El titular debe abrir y
ejecutar su panel de Tríade en Colab cuando necesite ese runtime.

## Emisor Colab (sin túnel entrante)

Después de encender y verificar Tríade en el **panel único habitual**,
se puede ejecutar este pequeño *sidecar* una vez por sesión Colab:

```python
import os
import threading
from google.colab import userdata
from tools.triade_colab_outbound_telemetry import run_while_colab_active

# Usa el almacén de Secretos de Colab. Nunca imprime ni guarda el token.
os.environ["TRIADE_TELEMETRY_INGEST_TOKEN"] = userdata.get(
    "TRIADE_TELEMETRY_INGEST_TOKEN"
)
if not any(
    t.name == "triade-observability" and t.is_alive() for t in threading.enumerate()
):
    threading.Thread(
        name="triade-observability",
        target=run_while_colab_active,
        kwargs={"interval_seconds": 60},
        daemon=True,
    ).start()
```

Esta celda solo conecta la telemetría cuando Colab está en ejecución;
no inicia Tríade ni la API original y no sobreescribe ninguna Bodega.
Si el operador prefiere no usar celdas adicionales, incorporar el
*sidecar* al panel R7 requiere una revisión separada de su arranque
y continuidad para evitar nuevas regresiones.

Para verificar desde la tablet: abrir
`https://triade-omega-mcp.onrender.com/#organismo`,
autenticarse con **clave de operador** y pulsar
**Consultar reporte saliente de Colab**. El panel diferencia
`no_reports`, `stale` y `fresh`.

## Invariantes

- No existe ruta para ejecutar workers, comandos, aprendizaje ni migraciones.
- No se envían textos de sesiones, eventos, rutas, identificaciones, datos de
  usuario ni contenidos de memoria.
- No se usa el puerto público 8010 de Colab desde Render. El emisor solo
  consulta tres rutas de `127.0.0.1:8010` y envía HTTPS al receptor fijo.
- No se persisten claves ni métricas en Drive/SQLite.
- Un token emisor robado permitiría falsificar contadores en RAM, por lo que
  la telemetría **nunca equivale a certificación de identidad ni aprendizaje**.
- Si Render Free reinicia o duerme la instancia, los informes se pierden;
  ello se notifica como ausencia de información, no como un reinicio del
  organismo ni como pérdida de la Bodega.

Pruebas: `tests/test_triade_colab_telemetry.py` y
`tests/test_triade_colab_sender.py`.
