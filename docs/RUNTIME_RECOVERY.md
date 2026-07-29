# Recuperación del runtime

`ServiceHealth` clasifica el runtime como `healthy`, `degraded`, `stalled`, `recovering`, `critical` o `stopped` usando progreso observable: heartbeat, último ciclo, cola, SQLite, Ollama, disco, RAM, temperatura y errores repetidos.

`RuntimeRecovery` no ejecuta shell ni controla systemd. Antes de actuar crea un snapshot SQLite, registra la causa, acepta callbacks explícitos para detener/arrancar workers, recupera leases vencidos, ejecuta `PRAGMA quick_check` y exige un nuevo heartbeat. Toda acción queda en `runtime_recovery_events`. El snapshot es el rollback.

El número de recuperaciones automáticas está presupuestado. Al agotarse, el watchdog queda en `critical` y no reinicia indefinidamente.

La separación es deliberada: systemd conserva procesos; el watchdog evalúa progreso. Los unit files de `deploy/systemd/` no se instalan automáticamente.
