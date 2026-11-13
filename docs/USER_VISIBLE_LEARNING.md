# Cómo ver qué sabe Tríade Ω

> Escrito el 2026-08-01, después de que el responsable dijera «todavía no veo que
> algo pase ni saberes» teniendo 633 candidatos en la base y 1661 tests en verde.
> Tenía razón, y este documento explica por qué y dónde mirar ahora.

## Por qué no se veía nada

Tres causas, en orden de importancia:

1. **No existía la vista.** `/api/knowledge/*` devolvía 404. No había ninguna
   forma, ni por API ni por UI, de preguntar «¿qué sabes?».
2. **Lo que sí se mostraba mentía.** `learning_journal` contaba como
   `candidates_verified` los que están en `internally_checked` —el estado
   atascado, el que significa justamente que **nadie** tiene evidencia— y como
   `evidence_created` filas de `neuron_evidence`, que es la evidencia del ciclo
   educativo de neuronas, otra cosa. El panel mostraba «49 verificados, 49
   evidencias» con **cero** saberes reales.
3. **No hay saberes.** Aun mirando bien, hoy el número honesto es **0**.

## Un candidato no es un saber

Esta es la distinción que faltaba:

| estado | qué significa | ¿lo ve el usuario como saber? | ¿entra al contexto? |
|---|---|---|---|
| `candidate` | generado tras un run, sin evidencia | **no** | **no** |
| `experimental` | usable en tratamiento, reversible | sí, marcado como experimental | sí |
| `evidence_verified` | control/tratamiento medido + RegressionGate | sí | sí |
| `stable` | consolidado por vía gobernada | sí | sí |
| `rejected` | empeoró o fue descartado | sólo en auditoría | no |
| `quarantined` | retenido por el filtro de seguridad | sólo en auditoría | no |
| `duplicate` | agrupado con un canónico | no se cuenta dos veces | no |

Sólo `stable` y `evidence_verified` cuentan como «Tríade sabe esto».

## Dónde mirarlo

### Por API

```bash
# ¿qué código y qué base está usando de verdad?
curl -s localhost:8010/api/runtime/build

# ¿cuántos saberes hay?
curl -s localhost:8010/api/knowledge/summary

# listar, filtrar por estado, y abrir uno
curl -s 'localhost:8010/api/knowledge?limit=20'
curl -s 'localhost:8010/api/knowledge?state=evidence_verified'
curl -s localhost:8010/api/knowledge/<knowledge_id>

# actividad, rechazos, último uso, tareas
curl -s localhost:8010/api/learning/activity
curl -s localhost:8010/api/learning/rejections
curl -s localhost:8010/api/learning/last-used
curl -s localhost:8010/api/learning/tasks
```

### Por UI

Cabina Viva → pestaña de observabilidad → tarjeta **«Saber y aprendizaje»**.
Muestra saberes utilizables, el desglose por estado con colores distintos, qué
se usó hoy, la actividad reciente y el SHA en ejecución.

## Comprobar que ves el código correcto

`/api/runtime/build` existe precisamente para eso. Sin él es imposible
distinguir «la función no existe» de «el proceso arrancó antes del cambio»:

```json
{
  "git_sha_short": "aa15029",
  "branch": "feat/governed-concurrency-and-self-improvement",
  "db_path": "/…/triade/memory/triade.db",
  "db_exists": true,
  "knowledge_visibility_version": "knowledge-visibility-1.0.0"
}
```

Si el `git_sha` no coincide con el commit que esperas, el proceso corre código
viejo: hay que reiniciar el servicio, no buscar el fallo en el código.

## Por qué hoy el número es cero

Medido sobre copia de la base real el 2026-08-01:

```
stable: 0 · evidence_verified: 0 · experimental: 0 · candidates: 633
```

Los 633 candidatos existen, pero:

- `learning_evidence` tiene **1 fila** con `baseline`, `candidate` y `comparison`
  en `null`: evidencia incompleta, que no asciende a nadie.
- No hay productor de evidencia para candidatos conversacionales, así que ninguno
  puede pasar de `internally_checked`.
- El contenido de esos candidatos son transcripciones de runs y plantillas
  autogeneradas: 633 filas, ~200 contenidos únicos.

**Un cero honesto es más útil que un número inflado.** El servicio nunca rellena
el hueco con actividad: si no hay saberes, lo dice y explica por qué.

## Lo que sí está construido y probado

- `triade/memory/retrieval_safety.py` — filtro que impide que una memoria
  envenenada mande sobre el criterio de seguridad. Medido: pasó de invertir la
  respuesta 5/5 a no afectarla.
- `triade/learning/retrieval.py` — inyección real antes de la inferencia, con
  `requested` / `retrieved` / `authorized` / `injected` distinguidos.
- `triade/learning/deduplication.py` — 628 filas → 200 canónicos, sin borrar nada.
- `triade/knowledge/visibility.py` — esta proyección.

Ninguno de los tres primeros tiene todavía llamador en producción: sus tablas
(`retrieval_safety_decisions`, `learning_retrieval_decisions`,
`learning_candidate_groups`) **no existen aún en la base real**, y eso es
justamente lo que `/api/learning/tasks` reporta como `never_scheduled`.

## Lo que falta para que el número deje de ser cero

1. Productor de evidencia (`LearningEvidenceProducer`) — no construido.
2. Llamador de producción para el retriever, dentro del runner.
3. Tareas de worker que ejecuten deduplicación y evidencia.
4. Que los candidatos contengan algo aprendible, no transcripciones.
