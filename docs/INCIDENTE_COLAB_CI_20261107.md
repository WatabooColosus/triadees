# Incidente Colab R7.17.18 — evidencia CI cancelada (2026-11-07)

## Síntoma verificado
El panel de arranque Colab devuelve:

```
RuntimeError: Versión aún no aprobada por CI: Runtime Truth CI
```

El controlador detiene la publicación **antes** de instalar la versión y no
autoriza sobrescrituras de la Bodega de Drive. Esta protección debe conservarse.

## Línea de evidencia GitHub (consultada en fecha de investigación)

- Catálogo: `colab-releases:releases/colab-channel.json`.
- Publicación: `R7.17.18-autonomous-panel-cpu-observer`; secuencia **42**.
- SHA inmutable de código:
  `a7d6c8573a1e79fa5a0cbd40fc53f8b4586c282b`.
- `Python Tests`: run **42147749806**, `success`.
- `Tríade Tests`: run **42147749834**, `success`.
- `Runtime Truth CI`: run **42147749898**, `success`, rama `main`.
- `Runtime Truth CI`: run **42153631151**, rama
  `fix/colab-cgroup-cpu-and-continuity-evidence-20261105`, mismo SHA,
  registrada como **cancelada** en el inicio del diagnóstico; posteriormente
  apareció un nuevo intento **en ejecución** (no asumir aprobación).

`tools/triade_colab_continuous.py::verify_ci` seleccionaba la ejecución
de mayor `run_number` por nombre y SHA, sin diferenciar una cancelación.
La cancelación posterior invalidaba de hecho una aprobación anterior de
los mismos bytes, aunque **no demostraba ningún defecto del código**.

## Prevención propuesta, sin rebajar controles

- Ignorar como evidencia decisoria únicamente ejecuciones con
  `status=completed` y `conclusion=cancelled`.
- Solo reutilizar un `success` para el **mismo SHA completo**, con
  `event=push` y nombre exacto del gate requerido.
- Una ejecución más reciente en progreso **sigue bloqueando** la publicación.
- Un fallo auténtico más reciente **sigue bloqueando** la publicación.
- Si todos los resultados de un gate están cancelados o faltan, **bloquear**.
- Mantener comprobación SHA256 de **cada** componente, secuencia de
  publicación y recibos/lineage de Drive sin cambios.
- Nuevas pruebas cubren: cancelación tardía con success previo,
  fallo posterior, ausencia de success y ejecución posterior en progreso.

## Qué NO se debe hacer

- No poner `REQUIRED_CI={}` ni marcar gates como aprobados a mano.
- No modificar el manifiesto existente de secuencia 42 para apuntar a otro
  commit; hacerlo violaría la continuidad y la validación de secuencia.
- No eliminar una base SQLite ni reconstruir la Bodega a partir de un
  arranque fallido.
- No tratar la memoria de ChatGPT como copia o respaldo autorizado de la
  Bodega original.

## Aplicación

La corrección de la función se revisa por PR. No se aplica por sí sola a
la publicación R7.17.18, que fija versiones y hashes inmutables. Esa
publicación podrá arrancar si el reintento del gate más reciente resulta
`success`; para adoptar la mejora del verificador **sin reescribir el
manifiesto anterior** deberá publicarse una nueva secuencia aprobada
por CI, con nuevos SHA y recibos protegidos.

La memoria reproducible de este incidente son este documento, el cambio
de código y las pruebas asociadas; no se afirma aprendizaje autónomo de los
modelos de Tríade.
