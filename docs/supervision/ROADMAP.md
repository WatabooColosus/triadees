# Hoja de ruta del supervisor externo

Estado tras el ciclo del 2026-08-03 (PR #69). Una casilla marcada exige un
artefacto o una ejecución que la respalde, nunca una afirmación.

## Fase 0 · Preservación

- [x] Identidad e integridad verificadas: `identity_core` 6 filas, no modificado;
      `PRAGMA quick_check` = `ok` sobre la base viva.
- [x] Secretos y permisos auditados: `.env`, `.git`, `.ssh`, `secrets` y
      `credentials` viajan como `crypt:<sha256>` sin contenido
      (`test_graphs_never_expose_secrets`).
- [x] Bases abiertas solo en lectura durante auditoría: todo acceso usa
      `file:...?mode=ro` (`test_live_database_is_never_modified`).
- [x] Rollback definido: ver `CURRENT_STATE.md` y el informe del PR.

## Fase 1 · Auditoría total

- [x] Inventario completo del repositorio: 14 582 nodos, incluidos los ocultos.
- [x] Entry points y procesos reales identificados: 77, de los cuales 14 tienen
      lanzador demostrable.
- [x] Código muerto y desconectado clasificado: 403 módulos sin importador,
      4 460 símbolos sin llamador estático.
- [x] Tablas, escritores y lectores trazados: 279 tablas, 107 vivas.
- [x] Contradicciones documentales registradas: F-011 (`schemas.sql` no refleja
      la base viva).
- [ ] Módulos duplicados: no analizado todavía.

## Fase 2 · Grafos verificables

- [x] Grafo físico reproducible.
- [x] Grafo de módulos e imports, con destino resuelto a fichero real.
- [x] Grafo de llamadas estático.
- [x] Grafo de entrypoints.
- [x] Grafo de workers y tipos de tarea.
- [x] Grafo de tablas con lectores y escritores.
- [x] Grafo de órganos.
- [x] Grafo de continuidad vital.
- [x] Grafo neural/runtime desde SQLite.
- [x] Nodos huérfanos identificados y separados por color.
- [x] Salida determinista (`test_output_is_deterministic`), en JSON, DOT,
      Mermaid y Markdown.
- [x] Observabilidad reactiva: `/internal-graphs` con pulso SSE de 2 s.
- [ ] Comparación automática entre commits: los artefactos son deterministas y
      comparables, pero no hay todavía un `diff` de grafos.

## Fase 3 · Vida operacional

- [x] Arranque real verificado: app 8010 respondiendo, Ollama con seis modelos.
- [x] Workers y pulso vivos: 10 de 11 eslabones con actividad en 24 h al inicio
      del ciclo, 11 de 11 al cierre.
- [x] Recorrido completo de una tarea real demostrado:
      `semantic_memory_governance` pasó de 0 ejecuciones históricas a dos tareas
      `completed` tras el arreglo.
- [ ] Colas, locks, reinicios y dead letters: no revisados en este ciclo.

## Fase 4 · Memoria y aprendizaje

- [x] Entrada → Bodega trazada: la ingesta escribe en `semantic_documents`.
- [x] Causa del estrechamiento identificada y una de sus dos ramas corregida
      (F-002).
- [ ] Recuperación desde Bodega: `bodega._search_semantic` sigue leyendo la
      tabla retirada y devuelve siempre vacío (F-014). **Siguiente trabajo.**
- [ ] Educación neuronal cerrada: `neuron_education_applications` sigue en 0
      filas (F-006).
- [ ] Aprendizaje con efecto posterior demostrado.

## Fase 5 · Anatomía cognitiva

- [x] Órganos mapeados a rutas reales: los 12 existen y están conectados por
      imports.
- [ ] Qualia formalizada: escribe ~16 600 filas que ningún módulo lee (F-005).
- [ ] Hipotálamo medible: `metabolic_signals` 70 293 filas sin lector.
- [ ] Cristal formalizado.

## Fase 6 · Autonomía gobernada

- [ ] Metas reales: `goals` y `goal_dependencies` vacías con lectores y
      escritores presentes.
- [ ] Planificación sostenida.
- [ ] Ejecución limitada y reversible.
- [ ] Escalamiento humano.

## Fase 7 · Federación

Bloqueada hasta estabilizar el organismo local. `federated_*` está en cero y
`federated_merge_nodes` no tiene ni lectores ni escritores (F-015).
