-- Retira `goals`: el gemelo muerto de `planning_graph`, y el caso que origino el
-- detector de deuda de alias. Cero filas en produccion desde siempre; su unico
-- escritor era `tests/test_consciousness.py` —un test que sembraba la unica fila
-- que su propio codigo iba a encontrar— y su unico lector,
-- `consciousness/salience.py`, devolvia el suelo fijo de 0.1 para cualquier
-- entrada. El lector se migro a `planning_graph` en el mismo commit.
--
-- Requiere rebasar el ancla con IdentityContinuity.migrate_anchor() por la via
-- gobernada: sin eso el runtime arranca en degraded_safe_identity_mismatch.
DROP TABLE IF EXISTS goals;
