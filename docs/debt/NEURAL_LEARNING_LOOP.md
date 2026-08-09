# El ciclo de aprendizaje neural: dónde se rompía

**Medición:** 2026-08-09 sobre `triade/memory/triade.db` (`integrity_check = ok`,
WAL, `synchronous = FULL`), confirmada por descriptor abierto del proceso vivo.
**PR:** #94 · **Rama:** `fix/close-neural-learning-loop`

## Lo que no faltaba

Casi todo. `NeuronEducationResolver` y `NeuronEducationApplicationRecorder`
existen, están bien construidos y **están cableados** en
`worker_loop.py:1697-1720`, en el orden correcto. El arreglo del 2026-08-02
(`9041efc`, priorizar neuronas medibles) también funciona.

Lo que faltaba eran cuatro eslabones, encadenados de tal forma que reparar uno
sólo destapaba el siguiente.

## Los cuatro cortes

### 1 · Las dos mitades no se tocaban

| | neuronas 11, 12 | neuronas 6471, 6871, 7052, 7053, 8399, 8400 |
|---|---|---|
| dominio | `vision_image_understanding`, `code_repair_build_tests` | `system_governance` (las seis) |
| ¿llegan a `lesson_prepared`? | **sí** — 13 sesiones, las únicas | **no** — 29 en `insufficient_material` |
| ¿se pueden medir? | **no** — 0 runs con informe | **sí** — 130/84/71/71/6/5 |

Las 47 activaciones de las neuronas 11 y 12 son todas de runs `pulse-*`, y de
las 412 filas de `verification_reports` **ninguna** es `pulse-*`. Quien recibía
lección no se podía medir; quien se podía medir no recibía lección.

**Causa:** de los cinco hosts de `TRUSTED_RESEARCH_HOSTS`, cuatro eran
documentación de Python y visión. Para un objetivo de `system_governance` sólo
Wikipedia resultaba relevante, y una fuente independiente nunca satisface la
puerta de dos.

**Reparado** (`fbf32fe`): cuatro fuentes curadas de gobernanza, con hosts
autorizados por el operador el 2026-08-09 — `owasp.org`, `nist.gov`,
`docs.github.com`, `martinfowler.com`. **No se bajó el umbral de dos fuentes.**
Verificado sobre datos reales: las neuronas 6471, 7052 y 8399 pasan de 1 a 3
fuentes independientes.

### 2 · La investigación no podía escribir material. Nunca.

`GovernedResearchWorker` sólo crea candidato cuando el material trae `claims`:

```python
elif not claims:
    status = "unverifiable"        # governed.py:142
```

El proveedor web devolvía `url`, `title` y `content`, **nunca `claims`**. La
condición no podía cumplirse jamás.

```
governed_research_runs: 156 filas, 100 % `unverifiable`, 0 candidatos
```

No era una regresión: la pieza no existía.

**Reparado** (`7b850bc`): `triade/research/claim_distiller.py`, con dos
extractores y la misma salida.

- **`rules`** — determinista, sin modelo, auditable. Frases definitorias. Es el
  predeterminado porque no depende de nada que pueda alucinar.
- **`model`** — un modelo local propone pares y **no se le cree**: `_anclada()`
  exige que al menos el 60 % de los términos con contenido de cada afirmación
  aparezcan en el texto de origen. Un modelo dentro de una cadena de evidencia
  sólo es admisible si su salida se verifica contra la fuente.
- **`both`** — une los dos; ante la misma clave manda la determinista.

Cada afirmación lleva `extractor`, así que se puede auditar el origen y
descartar por origen.

### 3 · El fallo se guardaba y no enseñaba

La misma pregunta **156 veces palabra por palabra**, el mismo fallo 156 veces,
guardado 156 veces, y ninguna lectura de ese historial. Y la pregunta estaba
contaminada: el nombre de una neurona nacida de una conversación es la frase que
la creó, no un tema — `neurona-como-hace-lindo` metía «como hace lindo» en la
consulta.

`repeated_failure` **ya era uno de los `TRIGGERS` gobernados** y ningún productor
lo emitía: 156/156 entraban como `gap`. La arquitectura anticipó aprender del
fallo repetido; faltaba el productor.

**Reparado** (`319e7f3`): `prior_failed_research()` cuenta cuántas veces esa
pregunta no produjo nada — es la memoria del proceso sobre sí mismo. `run()`
escala el trigger a `repeated_failure` a partir de tres y publica
`prior_failures` para que sea legible por quien decide el siguiente intento.
`_research_curriculum` **usa** ese reconocimiento y estrecha la pregunta al
dominio. Sólo el fallo educa: un candidato creado no cuenta como intento fallido.

### 4 · El efecto ocurrió y no tenía recibo

A las **02:04:06** la investigación creó su primer candidato en la historia del
sistema. Y murió acto seguido:

```
last_error: "El handler afirmó un efecto sin recibo verificable"
status: retry_wait
learning_queue: 795 → 796      ← el candidato ya estaba escrito
```

El gate es correcto y nunca había saltado porque `unverifiable` no declara
efecto ninguno. Al haber por fin efecto, se destapó.

**Reparado** (`a212a71`): `_research_effect_receipt()` firma el recibo
**releyendo la fila** en `learning_queue`. `verified` sale de que la fila exista
de verdad, no de que el handler diga que la escribió. Sin candidato no se firma
recibo: firmar sobre `unverifiable` sería mentir.

## Lo que sí se demostró en producción

A las 02:04:06, tras encadenar los cortes 1, 2 y 3:

```
pregunta:  "gobernanza de sistemas software auditoría trazabilidad
            documentación técnica fundamentos"     ← estrechada, sin ruido
fuentes:   docs.python.org, docs.pytest.org, owasp.org   ← 3 independientes
claims:    7 (3 del modelo, 4 de reglas)
status:    candidate_created      ← tras 156 `unverifiable` seguidos
learning_queue: 795 → 796
```

Es la primera vez que la investigación gobernada escribe material.

## Lo que NO está demostrado

- **Ningún ciclo de aprendizaje completo.** Hay candidato; no hay lección, ni
  evidencia evaluada, ni decisión, ni consolidación, ni rollback en vivo. La
  cadena completa está probada en fixture (`test_neural_learning_loop_closure`),
  no en producción.
- **El recibo no se ha confirmado en vivo.** Está verificado en prueba; el
  reintento en producción depende de dos relojes: el intervalo adaptativo de
  `research_curriculum` (900 s) y el envejecimiento de prioridad.
- ~~**Calidad de las afirmaciones.**~~ **Reparado el 2026-08-09** (rama
  `fix/claim-quality`). De las 7 producidas, tres eran la página hablando de sí
  misma: `"if you = interested in helping, please contact…"`,
  `"older versiona = available in the Github repo"` y
  `"previous versions = available at OWASP Top Ten 2021"`. `X are Y` casa con
  «If you are interested in helping…» exactamente igual que con «OWASP Top 10 is
  a standard awareness document»: la forma no las distingue. Tres cerrojos
  deterministas lo hacen —sujetos que no nombran nada, marcas de navegación en
  el valor, y un mínimo de tres palabras con contenido—, aplicados a **los dos**
  extractores, porque la higiene no depende de quién produjo la afirmación.
  Verificado contra las páginas vivas: owasp.org pasa de 4 afirmaciones a 1, y
  la que sobrevive es la única que afirma algo del tema.
### 5 · Investigación y currículo buscaban cosas distintas

La investigación usaba `domain_queries[domain]`; el currículo seleccionaba
material con `mission or name` de la neurona, que en las nacidas de una
conversación es la frase que las creó («Me llamo Santiago, soy el CEO de
Wataboo»). Dos vocabularios para la misma neurona: lo investigado bajo uno nunca
resultaba relevante bajo el otro. Las seis neuronas medibles veían **1** fuente
independiente y morían en `insufficient_material` incluso con el candidato de
investigación ya promovido a `internally_checked`.

**Reparado:** el mapa vive en `curriculum.py` como fuente única y lo comparten
los dos lados. Las seis pasan de 1 a **2** fuentes independientes.

## El ciclo entero, en una prueba de CI

`test_de_la_investigacion_a_la_consolidacion` recorre la cadena completa sobre
el código real, determinista y sin red: investigación con proveedor fijo →
destilación → candidato → material → lección → evidencia `pending` → runs
medidos → veredicto `improved` con `rollback_ref` conservado. Cada eslabón fue
un corte distinto en producción.

## Lo que sigue abierto

- **Selección de fuentes.** Tres de las siete afirmaciones son de
  `unittest`/`pytest` para una pregunta de gobernanza: `docs.python.org` casa
  por la palabra «software».

## Cadencia, que no es avería

Dos mecanismos hacen que el ciclo parezca detenido cuando no lo está, y conviene
no confundirlos con un corte:

- **Envejecimiento de prioridad.** `claim()` ordena por
  `priority − MIN(100, edad_en_minutos)`. `research_curriculum` tiene prioridad
  nominal 45, la peor de la cola, y el planner repone tareas de 12-15 en cada
  ciclo. Medido: **36 minutos** desde encolarse hasta despacharse. Es una guarda
  anti-inanición funcionando, no una avería. Si se quisiera investigar más a
  menudo, la palanca honesta es la prioridad nominal en
  `mission_planner._plan_research_curriculum`, no la guarda.
- **Intervalo adaptativo.** `research_curriculum` tiene 900 s entre ejecuciones
  (`adaptive_scheduler.py`). Antes de que venza, el planner la marca `skipped`
  con `adaptive_interval_not_elapsed`.

## Deuda registrada, no perseguida

- `NeuronEducationCycle._candidate_materials()` acepta `validated_in_runs` y
  `consolidated`; **nadie escribe ninguno**. Los reales son `internally_checked`
  (781) y `evidence_verified` (14). Otro lector al gemelo muerto. No bloquea hoy
  porque `internally_checked` sí entra.
- `PRAGMA foreign_key_check` reporta filas huérfanas en `model_events` → `runs`.
  `integrity_check` da `ok`.
- El runtime arranca en `degraded_safe_identity_mismatch`: el ancla de identidad
  está en `034` y el repo calcula `036` desde que #91 añadió
  `036_retire_goals.sql`. **No se ha tocado**: rebasarla exige autorización
  explícita del operador.
