-- Retira nueve esquemas huerfanos. Evidencia en docs/debt/ORPHAN_TABLES_BLOCK_B.md
-- Requiere rebasar el ancla con IdentityContinuity.migrate_anchor() en el mismo acto.
DROP TABLE IF EXISTS benchmark_results;
DROP TABLE IF EXISTS benchmark_tasks;
DROP TABLE IF EXISTS federated_merge_log;
DROP TABLE IF EXISTS federated_merge_nodes;
DROP TABLE IF EXISTS meta_model_candidates;
DROP TABLE IF EXISTS meta_model_decisions;
DROP TABLE IF EXISTS meta_model_evaluations;
DROP TABLE IF EXISTS metabolic_config;
DROP TABLE IF EXISTS user_sessions;
