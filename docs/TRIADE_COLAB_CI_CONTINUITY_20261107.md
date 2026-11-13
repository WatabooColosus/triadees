# Tríade Ω — acta de continuidad de Colab y CI · 2026-11-07 UTC

**Propósito:** conservar evidencia técnica verificable para recuperar el arranque
de Colab sin forzar gates, reemplazar la Bodega de Drive o atribuir aprendizaje
no demostrado. Acta mantenida dentro del repositorio de Tríade, no en la memoria
privada del usuario ni dentro de la base SQLite original.

## Identidad de publicación conservada

- Canal de publicación: rama `colab-releases`, archivo
  `releases/colab-channel.json`.
- Esquema `triade.colab.release.v1`, protocolo 1, secuencia **42**.
- Versión: `R7.17.18-autonomous-panel-cpu-observer`.
- Commit inmutable: `a7d6c8573a1e79fa5a0cbd40fc53f8b4586c282b`.
- Estado de canal: `candidate`; `auto_update_safe=false`.
- Comprobaciones obligatorias: `Runtime Truth CI`, `Python Tests`,
  `Tríade Tests`.
- La identidad de la publicación depende de versión, secuencia, commit y hashes
  SHA-256 de componentes. **No reescribir componentes en la secuencia 42.**

## Diagnóstico de la detención

El panel lanzó:
`RuntimeError: Versión aún no aprobada por CI: Runtime Truth CI`.

El verificador `tools/triade_colab_continuous.py:verify_ci` consulta
GitHub Actions por commit exacto y por evento `push`. Hasta esta revisión,
seleccionaba el último intento por número de run e intento **sin distinguir
la rama del push**.

La API devolvió, para **el mismo SHA**, la siguiente evidencia:

| Control | Ejecución | Rama | Resultado observado |
| --- | --- | --- | --- |
| Python Tests | 42147749806 | main | success |
| Tríade Tests | 42147749834 | main | success |
| Runtime Truth CI | 42147749898 | main | success |
| Tríade Tests | 42153631179 | rama de corrección | success |
| Runtime Truth CI | 42153631151 | rama de corrección | cancelled (primer intento) |

El último run cancelado sustituyó erróneamente a la aprobación de la rama
principal. Los cancelados son **bloqueantes según el verificador vigente**,
pero no constituyen prueba de fallo del código del commit publicado.

Se solicitó un **reintento real** de `Runtime Truth CI`
(`42153631151`, intento 2) para obtener evidencia más reciente sin relajar
el gate. El resultado definitivo requiere consulta de GitHub después del
reintento; no debe presumirse éxito antes de que termine.

## Mejora preventiva preparada en PR #187

La rama de integración ChatGPT/Tableta incorpora un cambio pendiente de
revisión en `verify_ci`:

1. Exigir siempre coincidencia **exacta de SHA** y evento `push`.
2. Si existen runs del mismo control sobre `main`, tomarlos como evidencia
   autoritativa del commit; ignorar runs duplicados de otras ramas que pueden
   ser cancelados por concurrencia.
3. Dentro de `main`, usar el **último intento**, aunque esté fallido,
   cancelado o pendiente. Un éxito anterior en `main` no puede esconderlo.
4. Cuando no hay evidencia de `main`, conservar el gate estricto existente
   para las ramas de publicación candidatas.
5. Mantener todas las comprobaciones de SHA de componentes, protección contra
   regresiones de secuencia, recibo de Drive y aislamiento de la Bodega.
6. Probar tanto el caso de duplicado cancelado como los tres casos
   bloqueantes del último intento en `main`.

Estas correcciones **no están en el commit a7d6... publicado**; el panel
actual no las cargará hasta que una futura versión verificada aumente la
secuencia del manifiesto conforme a su protocolo.

## Continuidad entre sesiones

Al recuperar la sesión, comprobar en este orden:

1. Estado de los tres checks obligatorios sobre el **SHA publicado**,
   con run IDs y fechas, sin aceptar resultados de otro código.
2. Integridad del manifiesto y hashes originales; no editar la secuencia
   actual para forzar arranque.
3. Drive montado y Bodega existente, en **solo lectura** hasta superar gates.
4. Activación del organismo y de los workers, seguida de `/health/live` y
   `/api/runtime/heartbeat`; una respuesta 200 no prueba por sí sola
   actividad cognitiva completa.
5. Diario educativo y transferencia independiente. Distinguir candidato,
   evidencia revisada, transferencia y consolidación realmente aplicada.
6. Guardar un recibo auditable y una versión nueva solo al pasar tests,
   comparación de continuidad y aprobación de publicación.

Ninguna anotación de esta acta implica modificar registros de memoria,
entrenar el modelo ni ejecutar trabajo en segundo plano desde ChatGPT.

## Fuentes directas de verdad

- `colab-releases:releases/colab-channel.json` (publicación vigente)
- `tools/triade_colab_continuous.py` (verificación estricta)
- `tests/test_colab_continuous.py` (contratos de no regresión)
- `https://github.com/WatabooColosus/triadees/actions/runs/42147749898`
- `https://github.com/WatabooColosus/triadees/actions/runs/42153631151`
- `https://github.com/WatabooColosus/triadees/pull/187` (corrección candidata)
