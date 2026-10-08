# Cierre del circuito de aprendizaje por fases

Fuente inspeccionada: `037b58e6a616149645012bd72e6996062c82391f`. Referencia remota: `faae9c146bd625c011a76af7c69ca6be0a7597a2`.

Se avanza secuencialmente: investigar -> reparación mínima -> prueba focalizada -> ejecución normal -> evidencia -> gate. Un ensayo fallido se conserva y se corrige antes de certificar la siguiente capacidad.

## Fase 1: Diagnóstico del corte

Estado: Investigación realizada; cierre funcional pendiente.

Trazar admisión, candidato, planner, worker, Formativa y ambos registros.

**Salida exigida:** Mapa de productores/consumidores, contratos y estados; causa demostrada sin escritura operativa.

## Fase 2: Currículo y entrenamiento ejecutable

Estado: PENDING.

Conectar la necesidad al planner y WorkerLoop actuales; Formativa produce casos de entrenamiento y casos reservados distintos, evaluador objetivo y presupuesto.

**Salida exigida:** Tarea real completa; resultados por caso, errores, latencia, recursos y referencias al conocimiento. No usar puntuación de estructura como competencia.

## Fase 3: Certificación independiente y activación

Estado: PENDING.

Usar Measurement Core, Regression Gate y evaluación existentes; resolver vínculo entre CapabilityRegistry y el registro leído por el router.

**Salida exigida:** Held-out reservado antes de entrenar; umbral predefinido; regresiones ausentes; certificación y activación con receipts. El router encuentra la neurona sin comodines.

## Fase 4: Educación y aplicación productiva

Estado: PENDING.

Conectar NeuronEducationCycle, ApplicationRecorder y Resolver con la neurona certificada y tareas posteriores.

**Salida exigida:** Mismo correlation_id o parent_correlation_id explícito desde experiencia hasta verification report; retrieval e inyección observados; aplicación real registrada.

## Fase 5: Beneficio causal y consolidación

Estado: PENDING.

Comparar baseline, tratamiento y control negativo en tareas nuevas equivalentes; evaluar provenance, riesgo y política efectiva de memoria.

**Salida exigida:** Tratamiento mejora una métrica objetiva frente a ambos controles; no regresión; decisión del gate; stable_knowledge_id sólo si la política realmente autoriza. La ruta stable actual requiere revisión explícita de gobernanza.

## Fase 6: Reutilización y persistencia

Estado: PENDING.

Ejecutar tareas relacionadas distintas antes y después de shutdown/restart limpio.

**Salida exigida:** Mismo conocimiento y versión recuperados; neurona y aplicación correlacionadas; resultado correcto después del reinicio.

## Fase 7: Fallo, regresión y recuperación

Estado: PENDING.

Probar crash de un WorkerLoop de prueba con tarea en vuelo y variante experimental inferior, usando infraestructura normal.

**Salida exigida:** Cero tareas perdidas y efectos duplicados; lease recuperado; integridad SQLite; regresión detectada y rollback restaura baseline con receipt.

## Fase 8: Aprendizaje autónomo y certificación final

Estado: PENDING.

Observar necesidad -> plan -> ejecución -> evaluación -> aprendizaje?siguiente decisión sin chat; recertificar fuente congelada.

**Salida exigida:** Al menos un ciclo cognitivo útil sin intervención; controles de recursos activos; pruebas focalizadas y suite final; evidencias de la misma revisión. Supervisor continuo después de cerrar estos gates.

## Investigación de fase 1

`DomainAdmissionCoordinator.form` conserva estado candidate y emite `pending_executable_curriculum`. `MissionPlanner._plan_neuron_formation` forma el candidato, pero no consume ese resultado como currículo ejecutable de admisión. `NeuronTrainer.evaluate` puntúa especificación, reglas e IO; no ejecuta tareas de competencia. `SandboxExecutionEngine.execute_configuration` serializa una configuración; su completed no demuestra aprendizaje. `NeuronEducationCycle._target` selecciona experimental, dejando fuera el candidato recién formado. `NeuronEvaluationCoordinator.promote` registra capacidades demostradas en otro flujo; falta verificar y cerrar el vínculo con el registro que consulta NeuralLearningRouter.

Lectura del sandbox existente: neurona 1, estado `candidate`, filas de training: 0. No se escribieron filas ni se atribuye esta observación al runtime productivo.

**Siguiente reparación:** establecer el contrato de currículo/ejecución/certificación para admisiones y cablearlo al planner y handler existentes, manteniendo candidato hasta evaluación objetiva. Evitar `store_training` con puntuación estructural: ese método también cambia el estado neuronal.

**No cerrado:** certificación, activación, aplicación productiva, beneficio actual, consolidación, reuse, persistencia aprendida, recovery productivo y autonomía cognitiva.
