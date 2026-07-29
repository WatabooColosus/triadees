# Despliegue 24/7

No se instalan servicios automáticamente. Antes de reiniciar producción:

```bash
python -m compileall -q triade apps scripts
pytest -q
python scripts/benchmark_live_runtime.py --samples 500
sudo systemctl restart triade.service
curl -fsS http://127.0.0.1:8010/api/health
```

Verificar que `live_runtime_heartbeat` avanza cada cinco segundos y que el
proceso permanece activo con Ollama detenido. Rollback: volver al commit anterior
y reiniciar el servicio; no es necesario borrar la tabla singleton.
