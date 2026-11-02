# Aceptación real de A/B en Colab (PR #159)

Antes de publicar o fusionar se exige una **evidencia read-only**, sin simular fallos.

1. Recupera Tríade en Colab mediante el centro continuo publicado (que preserva Drive).
2. En otra carpeta **aislada**, comprueba la rama y el commit de PR #159; no cambies el checkout R5 ni la Bodega viva.
3. Ejecuta `tools/triade_colab_failure_ab_acceptance.py --db <ruta-local-verificada> --repo <checkout-del-PR> --expected-commit <HEAD-certificado> --report /content/triade_acceptance/evidence.json` con `PYTHONPATH=<checkout-del-PR>`.
4. Lee solo los conteos, identidades por hash, elegibilidad de medición A/B, canary en sombra y reparación funcional pendiente. El script toma una copia SQLite transaccional temporal, incluidos los commits WAL.
5. Si faltan incidentes auténticos, registra el bloqueo como evidencia; **no fabriques prompts, eventos, ni tareas fallidas**.
6. Antes de una promoción estable aún faltan comparador independiente funcional, canary control/tratamiento, prueba de rollback real y recuperación verificada con el Drive del propietario.

La auditoría no ejecuta `evaluate_auto`, `observe`, `propose`, `deploy` ni `rollback`. El reporte siempre indica `operational_causality_proven=false`, `colab_rollback_certified=false` y `promotion_authorized=false`.

**No cambiar `colab-releases` a `stable` ni permitir `auto_update_safe` en este PR.** CI verde de pruebas aisladas no equivale a certificación en Colab.
