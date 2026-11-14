# Guía de acompañamiento de componentes desconectados

El grafo interno se regenera antes de cada revisión. Un nodo desconectado no se activa con imports artificiales ni con filas sintéticas.

## Orden de trabajo

1. **Entrypoints productivos**: ejecutar cada script bounded con entrada real, artefacto cerrado y referencia en `runs`. Los scripts de pruebas, migraciones históricas y recuperación manual se clasifican como legacy.
2. **Módulos de producción**: conectar solo cuando exista una responsabilidad operativa. `triade/learning/local_corpus.py` necesita un consumidor productivo gobernado; `apps/chatgpt_mcp_app.py` necesita un launcher explícito o debe quedar como integración opcional.
3. **Tablas**: para cada escritor vacío se exige una tarea que lo active, una fila no sintética, verificación y rollback. Las tablas de capacidades opcionales permanecen vacías hasta que exista demanda real.
4. **Workers**: cada tipo debe tener enqueue, lease, ejecución bounded, postcondición y evidencia. Las tareas `dead_letter` se investigan antes de reintentarse.

## Evidencia mínima

- Entrypoint: invocación real + artefactos + resultado.
- Módulo: importador productivo + ejecución observable.
- Tabla: escritor ejecutado + fila trazable + verificador.
- Aprendizaje: baseline, aplicación posterior, evaluación independiente y comparación.

El plan generado en `artifacts/audits/omega_disconnected_guidance.json` acompaña cada nodo con el tipo de evidencia que falta. No se permite aumentar el score reclasificando estados sin esa evidencia.
