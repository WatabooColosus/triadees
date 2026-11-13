# Auditoría en vivo de educación — 2026-07-29

## Estado observado

- `triade.service`: activo, sin reinicios desde 02:09 UTC.
- LifePulse: activo cada 60 segundos, autonomía `train_candidates`.
- WorkerLoop: activo; más de 800 tareas completadas.
- Investigación curricular: programada aproximadamente cada 10–11 minutos.
- Pipeline: 508 candidatos en `internally_checked`, todos con cero usos medidos en runs.
- Memoria semántica: 59 documentos candidate, cero stable.
- Neuronas: 13 stable y 2 experimental al inspeccionar.

La actividad existía, pero no era educación demostrada. Los ciclos repetían misiones y el score de misión permanecía prácticamente fijo. La investigación reciente devolvía `no_evidence` porque la consulta incluía texto interno y el proveedor principal no encontraba URLs.

## Cambio aplicado

Se añadió un ciclo persistente:

diagnóstico → currículo → selección de material → independencia de fuentes → lección candidata → ejercicio pendiente → revisión espaciada

El ciclo no marca `learned=true`. Dos fuentes independientes solo permiten `lesson_prepared`; todavía exige evaluación independiente, aplicación en runs y mejora contra baseline.

El canary real produjo:

- sesión inicial `material_insufficient`, sin aprendizaje declarado;
- investigación gobernada con documentación primaria de OpenCV y Pillow;
- dos candidatos `internally_checked`, sin memoria stable;
- sesión posterior `lesson_prepared`, con dos dominios independientes y `learned=false`.

## Límites actuales

- Solo existe un catálogo primario inicial para visión; otros dominios deben agregarse mediante política y pruebas.
- La evaluación independiente y aplicación en runs siguen pendientes.
- La educación prepara material y repetición; todavía no demuestra transferencia.
- No se habilitó promoción estable automática.
