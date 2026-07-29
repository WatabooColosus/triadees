# Activity Budgets

`triade.yml` define presupuestos por ventana para health checks, tareas ligeras, inferencias, investigación, evaluaciones, lecciones y backups. El heartbeat es ilimitado porque es una escritura singleton ligera.

Estos límites complementan el `runtime_budget` diario existente. En esta primera fase son configuración auditable; todavía falta conectarlos a un contador por ventana y al backpressure. Ninguna documentación debe afirmar que ya bloquean actividad.
