# Tríade Ω · Runtime local de bajo consumo

## Objetivo

Mantener Tríade realmente viva en un equipo de recursos limitados sin dejar un
LLM grande residente todo el tiempo. El principio es separar **vida operativa**
de **inferencia pesada**:

- vida: heartbeat, scheduler, seguridad, memoria SQLite, eventos, trazas y
  gobierno;
- cognición: Ollama sólo cuando una tarea necesita razonamiento/embedding;
- aprendizaje estable: evidencia + memoria + evaluación gobernada, no entrenamiento
  continuo de pesos.

Este perfil está pensado como referencia para un portátil con aproximadamente
8 GB de RAM y una GPU NVIDIA de 6 GB. Es un objetivo de despliegue, no una
medición certificada de ese hardware; debe validarse con telemetría real.

## Diseño

### 1. Núcleo siempre vivo sin LLM

El heartbeat y el scheduler continúan funcionando aunque Ollama esté descargado.
La identidad, Bodega, auditoría y colas permanecen en SQLite. La ausencia de
Ollama degrada capacidades cognitivas, pero no mata el proceso.

### 2. Un solo modelo a la vez

El perfil usa:

- `OLLAMA_MAX_LOADED_MODELS=1`
- `OLLAMA_NUM_PARALLEL=1`
- `TRIADE_OLLAMA_KEEP_ALIVE=0`

Con `keep_alive=0`, Tríade solicita a Ollama liberar el modelo tras completar
la operación. Esto sacrifica algo de latencia de recarga para recuperar RAM/VRAM
entre tareas.

### 3. Contexto acotado

`OLLAMA_CONTEXT_LENGTH=4096` es el punto de partida. No se debe usar la ventana
máxima de un modelo sólo porque esté disponible: el contexto consume memoria y
Tríade ya dispone de Bodega para recuperar únicamente evidencia relevante.

La política recomendada es:

1. consultar memoria/indexación;
2. seleccionar pocos fragmentos trazables;
3. construir un contexto corto;
4. llamar al modelo;
5. registrar resultado y descargar el modelo.

### 4. Modelo pequeño para continuidad

El runtime actual ya usa `qwen2.5:1.5b` para Central/Hipotálamo. Ollama Blood
ahora también lo reconoce como razonador válido. Además reconoce
`qwen3.5:0.8b` y `qwen3.5:2b` como opciones pequeñas instalables.

No se cambia automáticamente el modelo por documentación: cualquier sustitución
debe pasar un benchmark A/B de calidad, latencia y memoria en el hardware real.

### 5. Embeddings bajo demanda

Los embeddings no deben quedar residentes. Se calculan cuando una entrada nueva
lo requiere, se persisten en Bodega y el modelo se libera. Para búsquedas simples,
keyword/FTS debe poder resolver primero sin encender un modelo.

### 6. Modos de trabajo

En 8 GB el perfil solicita `balanced_background`, pero el Resource Governor sigue
siendo la autoridad. Un host `low` sólo alcanza balanced cuando conserva al menos
3 GB de RAM disponible, detecta al menos 4 GB de VRAM, está conectado a corriente
y Ollama Blood puede razonar. Si cualquiera falla, baja a `light_background`.

Balanced permite nutrición y evaluación gobernadas, pero mantiene bloqueados
`stable_consolidation`, tests/build pesados y full-local. Así el portátil puede
aprender candidatos reales sin convertirse en una estación de entrenamiento.

## Variables

Usar `.env.low_resource.example` como referencia. Las variables de Ollama deben
aplicarse al proceso/servicio que ejecuta Ollama; las variables `TRIADE_*` al
proceso de Tríade.

## Validación mínima

Después de arrancar:

```bash
python triade_digimon.py models ollama-health
python triade_digimon.py models ollama-blood
python triade_digimon.py runtime heartbeat
python triade_digimon.py always-on status
ollama ps
```

Criterios de éxito:

- puerto 8010 responde;
- heartbeat continúa sin invocar LLM;
- `effective_mode` no excede el permitido por Resource Governor;
- después de una inferencia con `TRIADE_OLLAMA_KEEP_ALIVE=0`, `ollama ps`
  deja de mostrar el modelo residente;
- no hay más de una inferencia/modelo concurrente;
- Bodega y continuidad funcionan aunque Ollama esté temporalmente descargado.

## Qué NO hacer en este portátil

- mantener simultáneamente modelos 3B/4B/embeddings residentes;
- contexto 32K/128K/256K para conversación normal;
- LoRA/PEFT entrenando continuamente en segundo plano;
- múltiples workers de modelo;
- usar GPU para heartbeat, scheduler o memoria;
- confundir “aprender” con reentrenar pesos: la mayor parte del aprendizaje de
  Tríade debe vivir en memoria gobernada, evidencia, neuronas y políticas.

## Fase siguiente

Medir en el equipo real:

- RAM/VRAM en reposo;
- RAM/VRAM durante una inferencia;
- latencia de carga/descarga;
- calidad A/B entre `qwen2.5:1.5b`, `qwen3.5:0.8b` y `qwen3.5:2b`;
- consumo del runtime durante 30-60 minutos.

Sólo después de esas mediciones se promueve un modelo nuevo como predeterminado.
