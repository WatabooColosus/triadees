# Gestión de GPU

La auditoría detectó una NVIDIA L4 con 23.034 MiB. `triade.yml` define reservas,
límites soft/hard y concurrencia conservadora. Esta fase solo aporta medición con
`scripts/benchmark_gpu_queue.py`; todavía no existe un `GPUResourceManager` que
haga admisión, reserva o preemption. Ninguna tarea debe asumir esos gates hasta
el PR dedicado a ModelWorker/GPUResourceManager.
