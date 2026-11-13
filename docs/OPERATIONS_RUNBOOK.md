# Operations runbook

Comprobaciones mínimas:

```bash
systemctl status triade.service triade-ollama.service
journalctl -u triade.service -n 100 --no-pager
python scripts/benchmark_gpu_queue.py
sqlite3 triade/memory/triade.db 'select cycle, duration_ms, updated_at from live_runtime_heartbeat;'
```

Si el heartbeat se congela: capturar logs y snapshot de DB, detener workers de
forma segura, recuperar leases vencidos y reiniciar el servicio. Si Ollama cae,
mantener heartbeat y tareas CPU; no reiniciar todo el runtime únicamente por esa
dependencia. Ante presión térmica o de memoria, detener trabajo pesado. El
backpressure automático completo sigue pendiente.
