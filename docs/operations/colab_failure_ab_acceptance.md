# Aceptación real de A/B en Colab (PR #159)

Antes de publicar o fusionar se exige una **evidencia read-only**, sin simular fallos.

1. Recupera Tríade en Colab mediante el centro continuo publicado (que preserva Drive).
2. En otra carpeta **aislada**, comprueba la rama y el commit de PR #159; no cambies el checkout R5 ni la Bodega viva.
3. Ejecuta `tools/triade_colab_failure_ab_acceptance.py --db <ruta-local-verificada> --repo <checkout-del-PR> --expected-commit <HEAD-certificado> --artifact-root /content/Triade --report /content/triade_acceptance/evidence.json` con `PYTHONPATH=<checkout-del-PR>`.
4. Lee solo los conteos, identidades por hash, elegibilidad de medición A/B, canary en sombra y reparación funcional pendiente. El script toma una copia SQLite transaccional temporal, incluidos los commits WAL.
5. Si faltan incidentes auténticos, registra el bloqueo como evidencia; **no fabriques prompts, eventos, ni tareas fallidas**.
6. Antes de una promoción estable aún faltan comparador independiente funcional, canary control/tratamiento, prueba de rollback real y recuperación verificada con el Drive del propietario.

La auditoría no ejecuta `evaluate_auto`, `observe`, `propose`, `deploy` ni `rollback`. El reporte siempre indica `operational_causality_proven=false`, `colab_rollback_certified=false` y `promotion_authorized=false`.

**No cambiar `colab-releases` a `stable` ni permitir `auto_update_safe` en este PR.** CI verde de pruebas aisladas no equivale a certificación en Colab.

## Rutas relativas y continuidad

Las referencias canónicas del runtime son habitualmente rutas relativas `runs/background/.../result.json`. El lector de A/B debe recibir el **directorio raíz del runtime real**, no el checkout de auditoría. La opción `--artifact-root` rechaza escapes `..`, enlaces simbólicos y referencias fuera del directorio autorizado; sigue requiriendo `manifest.json` y SHA-256 válidos. Un `result_ref` en SQLite por sí solo **no demuestra** que exista un archivo disponible.

La captura histórica del 24 de octubre de 2026 (no la Bodega viva del 2 de noviembre) presentó 2.489 tareas autónomas, 2.321 completadas, 4.809 transiciones, 0 filas en `worker_tasks`, y referencias de resultados relativas. Este hallazgo **no acredita incidentes positivos**, ni prueba que los artefactos se hayan conservado tras reinicios de Colab.

El lector ahora presenta `evidence_source_diagnostics`: conteos y causas de no admisión separadas de observaciones verificadas. Si los resultados históricos viven sólo en el disco efímero de una sesión ya terminada, permanecen inadmisibles hasta disponer de copias canónicas verificadas. No reconstruir ni inventar resultados antiguos.

## Integración en el panel continuo

Una versión futura del cliente ofrece **Auditar evidencia A/B**, a través de `failure_ab_status` del instalador; exige que la publicación incorpore el archivo `tools/triade_colab_failure_ab_acceptance.py` como componente `failure_ab_acceptance` con SHA-256 validado y Git/CI aprobado. El proceso clona el commit publicado en una carpeta separada, verifica identidad y árbol Git limpio, copia la Bodega y resuelve artefactos contra el runtime autorizado. Deja el informe fuera de Drive y devuelve `promotion_authorized=false`.

**No publicar este botón como parte de R7.17.0 ni modificar el catálogo sin CI del commit final y un manifiesto SHA coherente.** El cliente actual debe mantener la R7.17.0 si todavía no existe una nueva publicación verificada.
