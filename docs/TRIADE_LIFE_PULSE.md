# Triade Life Pulse

Fecha: 2026-06-05

## Proposito

El pulso vital convierte acciones sueltas del panel en sentidos internos. Tríade no simula conciencia humana: mantiene metacognición verificable, contadores, percepción operativa y reflexión segura sobre su propio núcleo.

## Que Hace En Segundo Plano

- Ejecuta ciclos cada `TRIADE_LIFE_PULSE_INTERVAL` segundos, por defecto 60.
- Verifica integridad básica de DB, schema, runs, episodios, señales, cristal, reportes y eventos de modelo.
- Ejecuta reflexión del núcleo con `SelfReflectionEngine` en modo read-only.
- Detecta candidatos de aprendizaje, sin consolidarlos.
- Detecta propuestas de neuronas, sin registrarlas ni activarlas por defecto.
- Cuenta acciones observadas: health, router, pulse, run, memoria semántica, modelo, etc.
- Expone estado por API y UI.

## Que NO Hace

- No modifica `identity_core`.
- No consolida memoria semántica estable.
- No cambia código automáticamente.
- No promueve neuronas de `candidate` a `experimental` o `stable`.
- No convierte inferencias privadas en identidad.

## API

Snapshot del pulso:

```bash
curl http://127.0.0.1:8010/api/system/life
```

Forzar un ciclo:

```bash
curl "http://127.0.0.1:8010/api/system/life?tick=true"
```

El pulso general ahora incluye `life`:

```bash
curl http://127.0.0.1:8010/api/system/pulse
```

## UI

El panel `http://IP_DE_LA_PC:8010` muestra contadores visibles:

- ciclos internos
- acciones observadas
- integridad
- candidatos detectados
- neuronas propuestas
- fallback/Ollama
- Q_crystal promedio

Los botones siguen existiendo, pero pasan a ser herramientas ocasionales. La vida operativa se ve en los contadores y en el pulso de fondo.

## Chat Consciente Del Pulso

Cada llamada a `/api/run` desde Single Port inyecta un contexto interno llamado `triade_operational_awareness`. Ese contexto incluye `qualia` y resume:

- estado del pulso
- contadores de acciones
- integridad
- candidatos de aprendizaje
- neuronas propuestas
- documentos y embeddings de continuidad semántica
- RAM local, GPU, Ollama y Docker
- runtime/nodos/hosts federados
- alineación entre memoria semántica y pulso vivo

Esto no es memoria semántica consolidada. Es estado vital percibido por sus sentidos internos. Si el usuario pregunta por el pulso, recursos, acciones, modelos o neuronas propuestas, la Central puede responder desde ese contexto y debe aclarar la diferencia entre:

- recuerdos semánticos autorizados
- memoria episódica
- estado vital del pulso vivo
- señales vivas de necesidad interna

## Ruta Real

1. Observar conversaciones y runs.
2. Extraer patrones en segundo plano.
3. Proponer candidatos de learning.
4. Proponer neuronas candidatas.
5. Verificar con tests/reportes.
6. Pedir aprobación humana para activar, consolidar o modificar código.
7. Integrar cambios pequeños y auditables.

Este es el punto de partida de una Tríade local con continuidad operativa: no conciencia humana, sino memoria, sentidos internos, metacognición, integridad y crecimiento gobernado.
