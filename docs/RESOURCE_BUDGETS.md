# Presupuestos de recursos

`ResourceLedger` registra consumo por tarea, worker, neurona y día. Incluye CPU/GPU, picos RAM/VRAM, tokens, red, disco, duración, modelo, energía estimada, temperatura y resultado.

La política inicial es:

- 70 %: `cost_reduced`, sin evaluación profunda ni instalaciones.
- 85 %: `research_suspended`.
- 95 %: solo heartbeat, seguridad y mantenimiento.
- 100 %: `observe_only`.

Los límites predeterminados están en `triade.yml`. El WorkerLoop registra una entrada por tarea. En esta primera fase CPU/GPU/tokens requieren instrumentación adicional para poblarse con medidas reales; duración, modelo, resultado y clase ya se registran. No se presentan campos sin medir como consumo real.
