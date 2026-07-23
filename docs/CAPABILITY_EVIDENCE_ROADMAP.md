# Ruta de capacidades verificables

Esta tabla separa código existente, prueba operativa y aspiración. Ninguna fila
se considera completa por una autoevaluación del propio modelo.

| Capacidad | Estado actual | Evidencia presente | Criterio para considerarla cumplida |
|---|---|---|---|
| Memoria contextual multiusuario | Parcial | memoria semántica persistente, sesiones y gobierno de recuerdos | aislamiento por tenant probado, recuperación tras reinicio, pruebas de contaminación cruzada y retención configurable |
| Aprendizaje acumulativo | Parcial | candidatos, consolidación y métricas por neurona | benchmark congelado ejecutado antes/después, mejora estadística reproducible y ausencia de regresión |
| Planificación de largo plazo | Deuda abierta | misiones persistentes y workers | objetivos, dependencias, replanificación tras reinicio, presupuestos y criterios de cierre durables |
| Múltiples modelos y herramientas | Experimental | router, Ollama, Safe Shell y comparación A/B | selección por tarea contra benchmark externo, fallos controlados y trazas de herramienta completas |
| Federación entre nodos | Experimental, no “real” todavía | transporte federado firmado previo y `PeerSync` con persistencia/defensa SSRF | autenticación mutua, merge idempotente real, resolución de conflictos y prueba entre dos hosts independientes |
| Mejora autónoma de código | Parcial y restringida | zonas, integridad, papelera, Safe Shell y tests | workspace aislado, parche autónomo, regresión obligatoria, rollback probado y promoción con aprobación definida |
| Entrenamiento propio | Deuda abierta | adquisición de modelos y registros de aprendizaje | datasets versionados con licencia/procedencia/PII, split congelado, adaptadores reproducibles y model card |
| Métricas externas | Deuda abierta | telemetría interna y heurísticas A/B | resultados importados de un evaluador independiente con artefacto, versión, hash y entorno reproducible |

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
