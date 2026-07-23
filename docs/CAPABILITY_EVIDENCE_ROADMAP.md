# Ruta de capacidades verificables

Esta tabla separa código existente, prueba operativa y aspiración. Ninguna fila
se considera completa por una autoevaluación del propio modelo.

| Capacidad | Estado actual | Evidencia presente | Criterio para considerarla cumplida |
|---|---|---|---|
| Memoria contextual multiusuario | Implementada en almacenamiento; autenticación externa pendiente | `tenant_id/user_id/session_id` obligatorios en runs, episodios e Hipotálamo; navegador con identidad persistente | integrar proveedor de identidad para producción y política de retención |
| Aprendizaje acumulativo | Medible, aún sin resultado externo suficiente | gate de novedad, métricas neuronales por activación y manifiesto de benchmark congelado | acumular ejecuciones de evaluador independiente y demostrar delta positivo sin regresión |
| Planificación de largo plazo | Implementada como núcleo | grafo SQLite con dependencias, leases, criterios, evidencia y replanificación tras reinicio | conectar el grafo a más decisiones autónomas del runtime |
| Múltiples modelos y herramientas | Experimental gobernada | A/B externo puede cambiar rutas Central/Hipotálamo solo con benchmark congelado | producir evaluaciones externas reales por cada tarea y ampliar cobertura de herramientas |
| Federación entre nodos | Experimental, no “real” todavía | transporte federado firmado previo y `PeerSync` con persistencia/defensa SSRF | autenticación mutua, merge idempotente real, resolución de conflictos y prueba entre dos hosts independientes |
| Mejora autónoma de código | Parcial y restringida | zonas, integridad, papelera, Safe Shell y tests | workspace aislado, parche autónomo, regresión obligatoria, rollback probado y promoción con aprobación definida |
| Entrenamiento propio | Deuda abierta | adquisición de modelos y registros de aprendizaje | datasets versionados con licencia/procedencia/PII, split congelado, adaptadores reproducibles y model card |
| Métricas externas | Contrato implementado; evidencia real pendiente | registro inmutable con evaluador independiente, hashes de manifiesto/artefacto y comparación acumulativa | ejecutar el benchmark desde un evaluador externo real; los tests simulados no cuentan como prueba externa de producción |

La prueba de regresión `tests/test_level5_assurance.py` cubre aislamiento tras
reinicio, grafo durable y replanificación, A/B con evidencia congelada, métricas
neuronales observadas, dos almacenes de nodo independientes con sobre firmado e
idempotente, worktree real con regresión/rollback, lease de workers entre
procesos y deduplicación persistente. El endpoint `GET /api/assurance/status`
publica únicamente contadores y controles comprobables; un contador cero no se
presenta como capacidad demostrada.

## Hallazgos de la integración 2026-07-23

- Se corrigió `PeerSync`: el registro usaba una columna inexistente, los fallos
  parciales se reportaban como éxito y las URLs no tenían defensa SSRF.
- Se corrigió el adaptador A/B para consumir el `ModelResult` real de Ollama.
  Su score continúa siendo una heurística interna; no cuenta como métrica externa.
- Se eliminó de Safe Shell el comando que imprimía el entorno completo y se
  confinó `working_dir` al repositorio.
- Se añadieron pruebas de regresión para shell, persistencia de peers,
  compatibilidad Ollama, locks de coordinación y unidades del scheduler.

## Próxima secuencia técnica

1. Implementar identidad `tenant_id/user_id/session_id` obligatoria en todo el
   camino de escritura y recuperación de memoria, con migración y pruebas.
2. Crear un almacén de objetivos durables con grafo de dependencias, leases,
   replanificación y criterios de aceptación.
3. Convertir PeerSync a sobres firmados, merge idempotente con vector/versiones
   y una prueba de integración entre dos procesos.
4. Construir el pipeline gobernado de datasets y adaptadores después de fijar
   licencias, consentimiento, borrado y benchmark externo.
5. Ejecutar mejora de código únicamente en un workspace efímero; exigir suite
   de regresión y conservar un artefacto de rollback antes de promover cambios.

Más pulsos no sustituyen estos contratos: aumentar la frecuencia antes de
tener aislamiento, idempotencia y evaluación externa solo amplifica errores y
consumo. El intervalo debe adaptarse a carga y evidencia de utilidad.
