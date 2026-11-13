# TRIADE · Iteración 2 — el aprendizaje encendido

2026-08-02, tras la auditoría integral. Objetivo: aprendizaje gobernado **full
encendido** en producción y funcionando de verdad, no en sombra.

---

## Lo que se encendió, y en qué orden

Encender la bandera **primero** habría abierto el circuito con el filtro fuera.
El orden importaba:

1. Filtro de seguridad en la extracción (P2-02).
2. Aislamiento del grupo de control (causa raíz de I-3, descubierta al encender).
3. `TRIADE_POST_RUN_LEARNING=1` en `.env`.

---

## Hallazgo nuevo · La ruta antigua invalidaba todos los experimentos

Es el hallazgo de esta iteración, y no se habría visto sin encender el circuito.

Un run genera **dos** filas en `learning_queue`:

| Ruta | `candidate_id` | Contenido |
|---|---|---|
| Gobernada | `exp-42ba…` | «Para los informes de auditoría usa siempre la etiqueta AUDITORIA-OMEGA al principio.» |
| Antigua | `learn-3816…` | `run_id: … input: Para los informes … AUDITORIA-OMEGA … response: …` |

El volcado de la ruta antigua **contiene la frase original con el dato dentro**.
`_build_prompt` excluía del control únicamente el candidato bajo medición, así
que el hermano seguía siendo recuperable. Comprobado en la base real:

```
CONTROL (excluye solo el candidato medido):
  inyectados: ['learn-38161190d2e54a42', 'exp-c09bc0b6c6954064']
```

El brazo de control tenía la respuesta. Resultado en producción:

```
control_mean = 1.0   treatment_mean = 1.0   delta = 0.0   ->  "neutral"
```

**349 generaciones de evidencia sin producir un solo saber no eran candidatos
malos: era el experimento invalidado de origen.** La regla que faltaba: un
experimento sobre un run no puede usar como control nada derivado de ese run.

Tras el arreglo, misma pregunta, mismo modelo, inferencia real:

```
control_mean = 0.0   treatment_mean = 1.0   delta = 1.0   ->  "improved"
```

---

## El circuito completo, medido en producción

Conversación real por `POST /api/run`, `source: audit-e2e-20260802`:

```
04:05:13  run-20260802-040513-a09bbc8f  responde al usuario
04:05:27  tarea learning_candidate_generation  (pending, prio 70)
             idempotency_key = post-run-learning:run-20260802-040513-a09bbc8f
04:06:12  worker-…5040d696 la reclama y la ejecuta
          running -> completion_uncertain -> completed (artifacts_published)
04:06:12  candidato exp-42ba8d3e1ea34d8e
             tipo preference · risk_level "none" (del veredicto, no literal)
             contenido: la proposición sola, sin transcripción
04:19:14  mission_planner encola la medición POR SU CUENTA
04:19:24  evidencia: control 0.0 · tratamiento 1.0 · delta 1.0 · improved
04:19:24  exp-42ba8d3e1ea34d8e -> evidence_verified
04:24:04  run posterior: recuperado e inyectado en el contexto
```

| Métrica | Antes | Después |
|---|---|---|
| `evidence_verified` | 1 | **2** |
| `learned_today` | 0 | **1** |
| `used_today` | 0 | **1** |
| Tareas `learning_candidate_generation` | 0 en toda la historia | ejecutándose |

La medición que promovió la encoló el `mission_planner` solo. No fue una tarea
manual: el sistema lo hizo por su cuenta.

---

## El eslabón que sigue sin cerrar · inyección ≠ influencia

Se inyectó, y está probado con artefacto:

```json
"verified_knowledge_block": "<triade_verified_knowledge>\n…\n- [exp-42ba8d3e1ea34d8e] Para los informes de a…"
```

`runs/run-20260802-042355-07034131/input.json`. El bloque va al principio del
prompt, antes de `Identidad:` (`central.py:877-880`).

**Y aun así el modelo respondió «AUDIT REPORT».**

El mismo saber, con el mismo modelo, acertó **5 de 5** en el prompt aislado del
experimento de evidencia. En el prompt completo de producción —que además lleva
`Identidad`, `Memoria`, `Verdad de continuidad`, `Investigación web`— el modelo
de 3B lo ignora.

Conclusión honesta: **el cableado está completo y es trazable de punta a punta;
la eficacia sobre la respuesta final, no.** El experimento de evidencia mide
influencia en un prompt aislado, no en el prompt de producción. Son dos cosas
distintas y hasta hoy se confundían.

Esto es P1 abierto, y es el trabajo de la iteración 3.

---

## Estado de las capacidades tras esta iteración

| # | Capacidad | Antes | Ahora |
|---|---|---|---|
| 9 | Aprendizaje conversación · ruta gobernada | PARTIAL (apagada) | **VERIFIED** en producción |
| 12 | Filtro de seguridad en extracción | BROKEN | **VERIFIED** |
| 15 | Generación de evidencia | PARTIAL (349 sin efecto) | **VERIFIED** (`improved` real) |
| 16 | Consolidación a saber verificado | NOT OBSERVED | **VERIFIED** (1 → 2, autónoma) |
| 17 | Inyección de saber en conversación | NOT OBSERVED | **PARTIAL** — inyecta, no influye |

Aprendizaje desde conversación: de **1/9 (11 %)** a **5/9 (56 %) verificado**.

---

## Sigue abierto

| ID | Qué |
|---|---|
| **P1-03** (nuevo) | La inyección no cambia la respuesta en el prompt completo de producción |
| P1-01 | Educación neuronal no aplica ni mide (`neuron_education_applications`: 0) |
| P1-02 | `self_improvement_canary_observation` sin productor |
| I-1 | Renovación de lease sin demostrar |
| P3-01 | `_check_queue` sobre `worker_tasks` retirada |
| P3-02 | `memory_consolidation_review` sin productor |

**La ruta antigua ya se puede retirar**, y ahora hay evidencia dura de por qué:
no solo duplica y vuelca transcripciones, sino que **invalidaba la medición de la
ruta nueva**. Con el control aislado ya no hace daño al experimento, pero sigue
contaminando el corpus con 180 volcados.

---

## Iteración 3, por orden

1. **P1-03**: que el saber verificado influya en el prompt de producción.
   Medir con la misma vara del experimento: control/tratamiento sobre el prompt
   **real**, no sobre uno aislado. Sin esa medición, cualquier ajuste de prompt
   es opinión.
2. Retirar la ruta antigua, con migración de los 180 volcados.
3. I-1, P1-02, P3-01, P3-02.
4. Diseñar el resolutor de la educación neuronal (P1-01).

---

## Rollback

```bash
# Apagar el aprendizaje sin desplegar código:
sed -i 's/^TRIADE_POST_RUN_LEARNING=1/TRIADE_POST_RUN_LEARNING=0/' .env
# y reiniciar la app.
```

Copia del `.env` previo en `.env.backup-preaudit`. Los tres cambios de código se
revierten con `git revert 5666113`.
