-- Retira dos tablas legacy vacías, después de mover sus últimos lectores y
-- escritores a los contratos canónicos vivos: semantic_documents/
-- semantic_embeddings y sandbox_replay. El aplicador se niega a retirarlas si
-- reciben filas entre el diagnóstico y la transacción.
--
-- Requiere rebasar el ancla con IdentityContinuity.migrate_anchor() en el mismo acto.
DROP TABLE IF EXISTS semantic_memory;
DROP TABLE IF EXISTS sandbox_executions;
