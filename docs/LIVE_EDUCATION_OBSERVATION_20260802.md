# Observación de la educación neuronal natural · 2026-08-02

El encargo era esperar y registrar una sesión completa sobre el runtime real,
sin intervención manual:

```
lesson_prepared → aplicaciones medibles → baseline → post-score → decisión
→ conservación o rollback
```

**No ocurrió, y no por falta de espera.** El recorrido no puede completarse hoy:
está cortado en tres sitios distintos. Este documento registra lo que sí pasó,
con la evidencia de cada corte.

La observación se hizo con `scripts/observe_neuron_education.py`, que **sólo
lee**: no crea sesiones, no fuerza `_target()`, no siembra actividad. Si la
herramienta empujara el ciclo, lo que registrara dejaría de ser una observación.

---

## Lo que se observó en vivo

Runtime levantado a las 20:09 UTC, en `full_local`, con los seis modelos
presentes. Dos ciclos naturales de `neuron_education_cycle`, sin tocarlos:

| Hora (UTC) | Qué hizo el ciclo | Resultado |
|---|---|---|
| 20:11:22 | Eligió la neurona **7052**, buscó material | `insufficient_material` |
| 20:17:32 | Resolvió la sesión de la neurona **12** | `uncertain` → `insufficient_evidence` |
| 20:17:32 | Eligió la neurona **7053**, buscó material | `insufficient_material` |

Ese es el ciclo entero, y se repite: resuelve a `insufficient_evidence` lo que no
puede medir, y crea sesiones nuevas que mueren en la puerta del material. Nunca
llega a la tercera etapa.

`neuron_education_applications` sigue con **cero filas**.

---

## Corte 1 · Las fechas no se comparan bien — *corregido*

`neuron_activity.created_at` se escribe con espacio (`2026-08-02 08:23:23`); la
sesión de educación usa ISO con `T` (`2026-08-02T03:38:27.340611+00:00`).
Comparando como texto, el espacio (`0x20`) ordena **antes** que la `T` (`0x54`):

```sql
sqlite> SELECT '2026-08-02 08:23:23' > '2026-08-02T03:38:27.340611+00:00';
0     -- «el run de las 08:23 es anterior a la lección de las 03:38»
```

El efecto no era perder una fila: era **invertir la medida**. Ese run se caía de
las aplicaciones y entraba en el baseline, que es exactamente lo que la pieza
existe para separar.

Corregido normalizando con `datetime()` en los dos lados de la comparación. Los
tests del fichero escribían ambos lados con `T`, así que pasaban con el fallo
puesto; los dos nuevos usan el formato real de producción.

---

## Corte 2 · Las neuronas medibles no son competencias

El 2026-08-02 (`9041efc`) se corrigió que el currículo prefiriera neuronas
evaluables. Funciona: ahora elige a la 7052 y la 7053 en vez de a la 11. El
problema es **quiénes son las evaluables**.

| Neurona | Dominio | «Misión» |
|---|---|---|
| 6471 | `system_governance` | «Me llamo Santiago, soy el CEO de Wataboo, tu creador» |
| 6871 | `system_governance` | «Quiero informacion sobre la Banda Epica de gotic metal» |
| 7052 | `system_governance` | «Puedes anexar otra base web a curriculum para busqueda…» |
| 7053 | `system_governance` | «Busca en google sobre agencia digital wataboo…» |

Son **frases de chat convertidas en neuronas**. Su «misión» es literalmente lo
que alguien escribió en una conversación, y su dominio es `system_governance`
para las cuatro, diga lo que diga el texto.

De ahí el `insufficient_material`: el ciclo exige dos fuentes independientes
relevantes para el objetivo, y no existen dos fuentes independientes sobre «Me
llamo Santiago». No es un fallo del buscador — es que **no hay competencia que
enseñar**. Se ve en el material que recupera: para el objetivo de la 6471 trajo
cuatro páginas sobre el concurso televisivo *Yo me llamo*.

El arreglo del currículo hizo lo que prometía. Lo que destapó es que la
población de neuronas evaluables está contaminada.

---

## Corte 3 · Las competencias reales no se activan donde se mide

Las dos neuronas que sí son competencias —la 11 (Visual) y la 12 (Código y
Reparación)— llegan a `lesson_prepared` sin problema. Pero:

```
neuron_activity de las neuronas 11 y 12:
  94 filas, todas en runs `pulse-*`
  última: 2026-07-29 02:08:33
```

Los runs `pulse-*` no generan `verification_reports`. Sin informe no hay
puntuación, sin puntuación no hay aplicación medida, y el resolutor sólo puede
responder `insufficient_evidence` — que es lo honesto. Su última activación fue
**antes** de que se prepararan sus lecciones.

Esto ya estaba diagnosticado como P1-05. Sigue abierto.

---

## Lo que esto significa

El circuito está construido y es correcto pieza a pieza. Lo que falta no es
código: es **un sujeto al que educar que además se pueda medir**. Hoy la
población se parte en dos mitades disjuntas, y ninguna sirve:

- las que se pueden medir no son competencias;
- las que son competencias no se ejecutan donde se mide.

Corregido el corte 1, quedan dos condiciones para que la próxima observación
pueda registrar un recorrido completo, y **ninguna es un parche al ciclo**:

1. que las neuronas nacidas de frases de chat dejen de entrar en el currículo
   como competencias —o dejen de nacer así—;
2. que las neuronas 11 y 12 se activen en runs con informe de verificación, no
   sólo en `pulse-*`.

Mientras tanto, la respuesta correcta del sistema es la que está dando:
`insufficient_evidence` y `insufficient_material`. Negarse a certificar sin
medida es el comportamiento que se le pidió. **La educación neuronal sigue en
0 % observado**, y ahora se sabe exactamente qué falta para que deje de estarlo.
