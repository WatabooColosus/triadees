# Adaptive Scheduler

La arquitectura objetivo se divide en dos piezas:

- `EventDrivenScheduler`: vencimientos monotónicos, prioridad, jitter, wake events y espera eficiente.
- `AdaptiveScheduler` legacy: historial, intervalos recomendados y consulta a `ResourceLedger`.

En esta fase el loop vivo usa la primera pieza para heartbeat (5 s) y despacho (20 s). Los handlers aún consultan la segunda antes de ejecutar. La integración futura debe convertir cada dominio en un job independiente y añadir circuit breakers persistentes, cooldown y backpressure integral.
