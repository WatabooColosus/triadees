# Continuidad de evidencias canónicas Colab · Tríade Ω

## Problema probado
El informe read-only del 2026-11-02 03:16 UTC, commit 347763e5, mostró 3.103 tareas y 5.955 transiciones SQLite. De 907 `result_ref` relativos muestreados, sólo cuatro pares `result.json/manifest.json` eran accesibles. No puede concluirse qué archivos históricos dejaron de existir ni recuperarlos únicamente desde SQLite.

## Implementación
`tools/triade_colab_evidence_continuity.py` contiene dos operaciones independientes y acotadas:

- `archive(db_path, runtime_root, store_dir)`: lee SQLite mediante URI `mode=ro`, toma referencias de `autonomous_tasks` en estado terminal y conserva **sólo directorios canónicos íntegros**: el manifiesto debe coincidir con los identificadores de tarea, tipo, estado, worker y generación de lease de la fila de Bodega, además de los SHA-256 del resultado y los demás artefactos. Rechaza rutas externas, traversal, symlinks, falta de hashes y archivos oversized. La copia tiene su propio `receipt.json` vinculado a la ruta original. Publica una vez por directorio usando staging y rename; nunca sobrescribe recibos.
- `restore(runtime_root, store_dir)`: verifica nuevamente cada recibo y restaura directorios **faltantes** en la misma ruta `runs/background/...`; nunca sobrescribe ni reconstruye artificialmente directorios parciales o divergentes. No escribe ni reemplaza la Bodega.

La copia privada se conserva en `MyDrive/Triade/operacion_colab_continua/evidencias_worker/v1/items` con índice por SHA-256 de referencia relativa. Límites por ciclo: 128 nuevos recibos; máximo 2 MiB por archivo y 6 MiB por recibo; máximo 10.000 referencias de BD examinadas. Se priorizan las actualizaciones más recientes. Las cuotas son límites de trabajo y no autorizan borrar archivos históricos. La protección es de solo adición; no hay recolección destructiva.

La versión V4 del **cuaderno permanente de Colab**, cuyo mismo ID de Drive se preserva, incluye el módulo íntegro comprimido y fijado por SHA-256. Tras el arranque restaurará lo disponible, archivará los recibos nuevos legítimos y activará un observador de intervalo 300 segundos que funciona sólo mientras el kernel de Colab permanezca encendido. El panel muestra los conteos `restored`, `archived`, `conflicts` y `unavailable_or_invalid`. El módulo no crea una tarea ni altera los gates A/B.

## Criterios para validación operativa

1. Registrar SHA-256 del módulo cargado, conteos y mensajes del panel V4. Confirmar que `memory_modified=false`.
2. Confirmar que aparezca al menos un recibo bajo `evidencias_worker/v1/items`, que el `receipt.json` y el manifiesto cuadren con los archivos, y que no haya conflictos de escritura.
3. En nueva sesión Colab, restaurar los recibos validados sin sobrescribir resultados existentes; comprobar que el lector A/B puede volver a verificar al menos esas evidencias.
4. Ejecutar auditoría A/B read-only antes/después; un mayor número de observaciones **no** supone una mejora causal ni certifica un canary.

**Seguridad:** No se fabrica ningún incidente, no se ejecutan prompts para superar gates, no se modifica SQLite, no se fusiona el PR ni se publica release stable automáticamente. Incidentes funcionales reales, controles negativos, canary causal y rollback productivo siguen siendo necesarios para promoción.
