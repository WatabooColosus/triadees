# Estrategia de migraciones

Tríade usa migraciones aditivas y auditables para memoria local.

Reglas:

- Cada migración vive en `triade/memory/migrations/NNN_descripcion.sql`.
- No se borra ni renombra una tabla existente sin una migración manual documentada y copia de seguridad.
- Las migraciones deben usar `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS` o `ALTER TABLE ADD COLUMN` cuando sea posible.
- Los cambios destructivos se reemplazan por tablas nuevas, backfill explícito y validación humana.
- Cada migración debe poder ejecutarse más de una vez sin romper el entorno local.

Flujo recomendado:

1. Crear migración SQL pequeña.
2. Ejecutarla sobre una copia de `triade/memory/triade.db`.
3. Añadir prueba que verifique estructura o comportamiento.
4. Documentar el estado en `docs/STATUS_*.md` si cambia una capacidad visible.

Estado actual:

- `001_9A_semantic_memory.sql`: memoria semántica documental y embeddings.
- `002_federated_transport_log.sql`: bitácora opcional para transporte federado firmado.

