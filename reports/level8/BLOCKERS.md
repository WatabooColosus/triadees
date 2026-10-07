# Bloqueos rectificados

Revisión: 2026-10-07, HEAD `bd0aa91e6c922768f7e513f3e434381e64018497`, cambios locales sin commit. Esta revisión sustituye las clasificaciones amplias de recuperación y autonomía de FINAL_AUDIT; no invalida las observaciones originales.

| Orden | Bloqueo y clasificación | Evidencia y límite | Condición de cierre |
|---|---|---|---|
| 1 | Transferencia del conocimiento: ensayo FALLIDO; causa productiva aún NO DETERMINADA | learning_longitudinal_v2.json: baseline, learned y control 0/3. Se recuperó contexto, pero las transacciones violaron el CHECK. Ensayo aislado, modelo qwen2.5:1.5b y política de selección de modelos desactivada: no demuestra fallo global de Tríade. | Diagnosticar contexto recibido y consumidor con política normal; demostrar transferencia a una tarea distinta con métrica objetiva y control negativo. No ajustar el gate para conseguir PASS. |
| 2 | Educación y uso productivo: NO DEMOSTRADOS | El ensayo anterior no acredita Central → ruta neuronal → aplicación → verification_report → consolidación. La ventana observada registró 0 eventos de aprendizaje. | Correlacionar candidato, evidencia independiente, neurona, ejecución posterior, uso y evaluación. Depende de 1 para declarar mejora causal. |
| 3 | Recuperación completa: PARCIAL | recovery_end_to_end.json combina una tarea aislada idempotente recuperada en 2.172 s y la API supervisada recuperada en 59.656 s. No es una misma misión productiva en vuelo. | Correlacionar una tarea del WorkerLoop normal, crash, lease recuperado, resultado y receipt; comprobar un solo efecto y ninguna pérdida en entorno de prueba. |
| 4 | Autonomía cognitiva continua: PARCIAL | background_autonomy_v2.json: 1806.781 s, 56 ciclos, 138 tareas completadas, 0 intervenciones, 0 aprendizajes. Sí demuestra mantenimiento continuo. | Observar necesidad → planificación → ejecución → evaluación/aprendizaje sin disparos manuales; enlazar evidencias, no únicamente contar ciclos. Depende de 2. |
| 5 | Persistencia aprendida y rollback: NO DEMOSTRADOS | clean_restart_v2.json demuestra cierre limpio, identidad y liberación de locks en sandbox; no persistencia de conocimiento consolidado ni rechazo/rollback de una mejora. | Verificar conocimiento consolidado y receipts antes/después del reinicio; probar rechazo y rollback seguro, sin modificar identidad. Depende de 2. |

Otros límites de certificación: seguridad mínima PARCIAL; pruebas de recursos válidas a nivel de máquina pero transición entre instancias; 24h/72h NO DEMOSTRADAS. CI RED-EXTERNAL por billing según ci_blocker.json: no es reparación de código ni motivo para modificar workflows. No se volvió a consultar GitHub.

## Comprobación actual

`Invoke-RestMethod http://127.0.0.1:8010/health/deep`: healthy, PID 11212, workers activos, full_local_guarded. Heartbeat pasó de ciclo 435 (03:02:42Z) a 438 (03:02:59Z), sin crear tareas ni enviar chat. Esto acredita progreso del heartbeat, no aprendizaje.

`python -m pytest tests/test_level8_evidence_audit.py -q`: 10 pruebas aprobadas. `python scripts/level8_audit.py`: salida 1 prevista porque LEVEL_8_CANDIDATE=false; cobertura calculada 4.5/10, sin cambiar pesos ni umbrales. La cifra anterior 5.3 incluía dos gates demasiado amplios. Esta reducción corrige la certificación; no representa una degradación del runtime.

Las 2697 pruebas completas corresponden al código previamente certificado; no se presentan como una nueva ejecución de toda la suite. No hubo reinicios, modificaciones de datos productivos, commits ni push en esta revisión.

## Siguiente acción

Atacar 1 mediante diagnóstico del consumidor normal y de su contexto efectivo. No hay causa de código demostrada todavía que justifique reemplazar el pipeline o añadir otra arquitectura. Mantener las pruebas parciales como evidencia y cerrar los circuitos correlacionados en el orden anterior.

