# Auditoría viva del motor Tríade

## Estado observado

La auditoría se ejecutó sobre `triade/memory/triade.db` y el runtime local del
servidor. La cadena de vitalidad ya tiene verificación, memoria episódica,
recuperación y backups operativos. El aprendizaje, en cambio, todavía no puede
declararse consolidado:

- 15 candidatos en `learning_queue`; 10 `internally_checked` y 5
  `evidence_verified`.
- 6 evidencias comparativas, pero 0 candidatos con usos medidos en ejecuciones,
  0 `validated_in_runs`, 0 consolidados y 0 sesiones educativas aprobadas.
- Investigación gobernada presente: 6 ejecuciones; investigación autónoma: 2.
- PEFT/canary sin adaptador activo ni eventos: es una ruta bajo demanda, no una
  señal de aprendizaje real por sí sola.
- Federación sin nodos registrados: el registro exige emparejamiento explícito
  y no debe crear confianza automáticamente.
- La base tiene todos los esquemas relevantes; la ausencia de filas en
  federación, adapters y canary no prueba una rotura si no existe una fuente o
  un nodo autorizado que activar.

## Prioridad de cierre

1. **Ejecución en segundo plano.** Arrancar y vigilar el worker y el runner
   continuo desde `TriadeOmega`; registrar cada ciclo, error y recuperación.
2. **Uso medido del aprendizaje.** Conectar retrieval y `run_use_count` a las
   ejecuciones reales. Un candidato no puede consolidarse hasta acumular tres
   usos y una mejora media de al menos 0.70.
3. **Educación reversible.** Tras `validated_in_runs`, crear la asignación a
   neurona, ejecutar sesiones y persistir aplicaciones y resultados.
4. **Investigación web gobernada.** Mantener fuentes permitidas, citas,
   contradicciones y proyección al grafo; nunca introducir una afirmación web
   directamente en memoria estable.
5. **PEFT/canary.** Sólo cuando exista un adapter aprobado: ejecutar canary,
   comparar baseline/candidate, registrar regresiones y permitir rollback.
6. **Federación.** Emparejar al menos un nodo real con clave y permisos
   mínimos; usar intercambio de candidatos/verificaciones y mantener todo lo
   recibido como candidato hasta pasar la misma cadena de evidencia.

## Corrección aplicada

`scripts/audit_learning_baseline.py` consultaba una columna `status` que no
existe en `learning_evidence`. Ahora usa `decision`, que es el estado real de
la evidencia comparativa. La auditoría vuelve a ser ejecutable y no oculta un
fallo de SQL como si faltara el aprendizaje.

## Prueba de capacidad por memoria

Se ejecutaron los tests de `hardware_profile`, `resource_governor`,
`compatibility_matrix` y `model_router`, además de una simulación de perfiles:

- 7.2 GB totales y menos de 2 GB libres: `cooldown`; heartbeat y lectura siguen
  permitidos, pero workers pesados, evaluación y consolidación se bloquean.
- 16 GB con 8 GB libres: `balanced_background`; workers, investigación,
  embeddings y evaluación pueden ejecutarse, con consolidación estable todavía
  protegida.
- 32 GB con 16 GB libres y Ollama sano: `full_local_guarded`; se habilitan
  evaluación, consolidación, canary, tests y research gobernado.

La PC actual entra en protección porque en los ciclos observados llegó a 0.08
GB libres. El estado correcto es presión de recursos, no una rotura de SQLite;
la interfaz debe mostrar degradación y la causa, no fingir que el motor está
listo para full local.

## Criterio de finalización

La deuda sólo baja cuando existe productor, evento, consumidor y evidencia
persistida. Las filas sintéticas para “poner verde” el grafo quedan prohibidas.
