# Tríade Ω 5.8.0 — Runtime Recovery

Rama de actualización: codex/triade-5.8.0-runtime-recovery

Esta versión responde al dictamen del runtime del 22/10/2026: heartbeat activo, Ollama disponible, pero worker con iterations=0 y cola sin progreso.

## Incluye

- diagnóstico basado en evidencia de SQLite, worker, cola, metabolismo, Ollama y GPU;
- recuperación explícita de leases vencidos con copia previa de SQLite;
- gate de aceptación que exige progreso entre dos lecturas;
- no borra runs, tareas ni evidencias y no fabrica actividad.

## Uso en Colab

```python
!python tools/upgrade_triade_580.py --root /content/Triade
!python tools/acceptance_580.py --root /content/Triade --script tools/upgrade_triade_580.py --wait 30
```

La reparación de leases se ejecuta solo de forma explícita:

```python
!python tools/upgrade_triade_580.py --root /content/Triade --repair-leases
```

Esta rama queda lista para revisión antes de fusionarla en main.
