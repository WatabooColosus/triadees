# Arquitectura del latido vivo

`LiveHeartbeat` es una ruta operacional CPU-only. Cada pulso registra reloj monotónico, reloj de pared, ciclo, PID, RAM disponible y duración en una fila singleton SQLite. No importa ni consulta Ollama.

`EventDrivenScheduler` mantiene jobs independientes en una priority queue monotónica. Espera sobre un evento con timeout hasta el próximo vencimiento; no usa busy loop. `WorkerTaskQueue.enqueue()` despierta el runtime mediante `wake_bus`, por lo que una tarea nueva no espera al intervalo de despacho.

La compatibilidad se conserva: `WorkerLoop` sigue ejecutando sus handlers y gates existentes. Esta fase cambia su mecanismo de espera, no separa aún todos los workers especializados.

Rollback: revertir los cambios en `worker_loop.py`, `worker_autostart.py` y `task_queue.py`; las tablas singleton añadidas son compatibles y pueden quedar sin uso.
