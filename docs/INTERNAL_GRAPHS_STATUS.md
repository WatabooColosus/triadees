# Estado de implementación de los grafos internos

**Última verificación: 2026-08-09**, sobre `triade/memory/triade.db` y el runtime
vivo en el puerto 8010.

## Operativo

- **Atlas físico del repositorio** — `triade/observability/file_graph.py`.
- **Protección criptográfica de rutas sensibles** — los nodos bajo
  `SENSITIVE_NAMES` se publican con identificador SHA-256, sin ruta ni contenido.
- **Grafo neural leído desde SQLite en solo lectura** —
  `triade/observability/neural_graph.py`.
- **Grafo de código y de runtime** — `code_graph.py`, `runtime_graph.py`.
- **Exportación JSON versionada** — `scripts/build_internal_graphs.py` escribe
  en `artifacts/internal_graphs/`.
- **API visual** — `apps/routes/ui.py` sirve el explorador
  (`internal_graphs_ui.html`, catálogo, lectura y deuda) y el frontend lo pinta
  en `frontend/src/components/GrafosInternos.tsx`.
- **Consumo por el planificador** — `mission_planner` planifica
  `system_debt_scan` con prioridad derivada del total de deuda medido:
  `priority = max(10, 45 − min(35, total))`. Cuanta más deuda mide el grafo, más
  urgente se vuelve escanearla.
- **Refresco bajo demanda** — `triade/observability/refresh.py` aplica
  *serve-stale-while-revalidate*: devuelve lo que hay, publica su edad, y si
  supera 900 s lanza **una** reconstrucción en segundo plano, con lock y
  escritura atómica por `os.replace`. No hay temporizador a propósito:
  reconstruir el AST cuesta ~53 s y gastarlos sin que nadie mire sería quemar
  CPU.

## Pendiente

- **Streaming de eventos.** El panel sigue siendo *pull*; no hay empuje al
  cliente cuando el grafo cambia.
- **Distinguir hallazgo observado de corte demostrado.** El contador publica
  hallazgos —39 el 2026-08-09, todos `incomplete_subsystem` y `confirmed_break`
  en 0—. La capa de contratos verificados que separa una cosa de la otra llegó
  con #89 y aún no se refleja en el panel.
- **Falsos positivos por escritura parametrizada.** `SET status = ?` no dice qué
  valor escribe, así que estados vivos aparecen como muertos. Verificados como
  falsos positivos el 2026-08-09: `retry_wait`, `preparing`, `replanning`. El
  propio `alias_debt.py` documenta la categoría en su cabecera y aun así los
  cuenta.

## Nota sobre este documento

Su versión anterior —del PR #68, 2026-08-02— declaraba pendientes la API visual
y el uso del grafo por el planificador. Las dos existen desde entonces, así que
se reescribió en vez de rescatarse tal cual: documentación que declara pendiente
lo que ya funciona se lee igual que la buena y es igual de falsa que la que cita
un fichero borrado.
