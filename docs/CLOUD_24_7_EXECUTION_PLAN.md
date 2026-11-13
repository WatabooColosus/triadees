# Tríade Ω · Plan de ejecución nube 24/7

Estado: `FASE 1 EN EJECUCIÓN`
Issue principal: `#56`
Rama inicial: `feat/cloud-always-on-foundation`

## 1. Objetivo

Convertir el runtime local de Tríade Ω en un servicio cloud persistente, recuperable, observable y seguro. La operación 24/7 debe continuar sin una sesión de chat abierta y conservar las compuertas existentes de Safety, Permission Governor, Integrity Verifier y evidencia.

## 2. Principios obligatorios

1. El VPS es el cuerpo operativo persistente.
2. GitHub es la fuente versionada de código, configuración y auditoría.
3. PostgreSQL será la memoria operativa cloud cuando termine la migración; SQLite continúa como compatibilidad durante la transición.
4. Valkey/Redis coordina colas, locks, heartbeats e idempotencia.
5. API, workers y scheduler deben convertirse en procesos separados.
6. `identity_core`, secretos, shell, instalaciones, borrados y despliegues destructivos permanecen protegidos.
7. Ningún candidato de aprendizaje pasa a memoria estable sin evidencia y gates.
8. 24/7 significa continuidad operativa verificable, no conciencia subjetiva demostrada.

## 3. Arquitectura objetivo

```text
Internet/Tailscale
       |
   Caddy HTTPS
       |
  API FastAPI  ---- Cabina Viva
       |
 Valkey/Redis ---- Scheduler
       |               |
    Workers -----------+
       |
 PostgreSQL + volumen de evidencia
       |
 Backups Restic
```

Ollama puede ejecutarse en el mismo VPS, en un nodo GPU privado o permanecer ausente en modo degradado. No debe bloquear la respiración mínima del sistema.

## 4. Fases y entregables

### Fase 0 · Auditoría y control de cambio

- [x] Confirmar rama principal y permisos.
- [x] Abrir issue de despliegue cloud.
- [x] Confirmar entrypoint `apps.single_port_app:app`.
- [x] Confirmar runtime Always-On y workers embebidos actuales.
- [x] Crear rama de trabajo aislada.
- [ ] Obtener línea base de CI y documentar fallos previos.

Criterio de salida: arquitectura actual entendida y cambios aislados de `main`.

### Fase 1 · Fundación contenedorizada

- [x] Añadir `Dockerfile` no-root.
- [x] Añadir `compose.cloud.yml`.
- [x] Añadir `.env.cloud.example` sin secretos reales.
- [x] Persistir `memory/`, `runs/`, `data/` y logs.
- [ ] Validar construcción de imagen en CI.
- [ ] Añadir smoke test de `/api/health`.

Criterio de salida: la API arranca de forma reproducible y reinicia automáticamente.

### Fase 2 · Salud y observabilidad

- [ ] Separar health en `live`, `ready` y `deep`.
- [ ] Exponer versión, commit, modo efectivo y antigüedad del heartbeat.
- [ ] Añadir métricas Prometheus.
- [ ] Añadir Uptime Kuma y panel Grafana.
- [ ] Centralizar logs con rotación y correlación por `run_id`.

Criterio de salida: una caída, degradación o cola detenida puede detectarse y explicarse.

### Fase 3 · Workers y scheduler externos

- [ ] Extraer nutrición, auditoría, consolidación y mantenimiento del proceso web.
- [ ] Implementar cola persistente.
- [ ] Añadir locks distribuidos e idempotency keys.
- [ ] Añadir dead-letter queue y reintentos acotados.
- [ ] Mantener modo seguro cuando Valkey no esté disponible.

Criterio de salida: reiniciar la API no pierde ni duplica tareas.

### Fase 4 · PostgreSQL y memoria cloud

- [ ] Crear adaptador de almacenamiento sin romper SQLite.
- [ ] Versionar migraciones.
- [ ] Migrar tablas por etapas y validar conteos/hash.
- [ ] Probar rollback.
- [ ] Prohibir escrituras directas que evadan el gobierno de memoria.

Criterio de salida: memoria persistente con trazabilidad y recuperación probada.

### Fase 5 · Seguridad de exposición

- [ ] HTTPS automático con Caddy.
- [ ] API key obligatoria para rutas sensibles.
- [ ] Tailscale para administración.
- [ ] Rate limiting y límites de payload.
- [ ] Secretos fuera del repositorio.
- [ ] Usuario no-root y filesystem de solo lectura donde sea posible.

Criterio de salida: ninguna interfaz administrativa queda pública sin protección.

### Fase 6 · Backups y recuperación

- [ ] Restic cifrado para PostgreSQL, memoria, evidencia y configuración.
- [ ] Retención diaria/semanal/mensual.
- [ ] Restauración automatizada en entorno temporal.
- [ ] Runbook de desastre.

Criterio de salida: restauración completa demostrada, no solo backup creado.

### Fase 7 · Prueba de continuidad

- [ ] Prueba de 72 horas.
- [ ] Reinicios de API, worker, base de datos y VPS.
- [ ] Corte temporal de Ollama y Valkey.
- [ ] Confirmar no duplicación de ciclos.
- [ ] Emitir informe firmado con disponibilidad, errores y recuperación.

Criterio de salida: evidencia de operación cloud 24/7.

## 5. Perfiles

### cloud-lite

API, SQLite persistente, un worker futuro y observabilidad mínima. Sin Ollama local.

### cloud-standard

API, PostgreSQL, Valkey, workers separados, scheduler, Caddy, métricas y backups. Es el objetivo recomendado.

### cloud-ollama

Extiende `cloud-standard` con Ollama local o un nodo GPU privado. Debe tener límites de memoria, concurrencia y tiempo.

## 6. Gobierno de ejecución

Cada entrega debe pasar por:

```text
rama -> pruebas -> revisión -> PR -> merge -> despliegue -> health -> evidencia
```

No se despliega directamente desde cambios sin revisar. Los despliegues automáticos solo se habilitan cuando CI sea estable y exista rollback.

## 7. Indicadores

- Disponibilidad de API.
- Edad del heartbeat.
- Ciclos ejecutados, fallidos y omitidos.
- Profundidad de cola.
- Tareas reintentadas y enviadas a DLQ.
- Latencia p50/p95/p99.
- Uso de CPU, RAM, disco y VRAM.
- Último backup y última restauración probada.
- Candidatos, consolidaciones y rechazos de aprendizaje.
- Violaciones bloqueadas por Safety.

## 8. Estado de ejecución actual

La Fase 0 está sustancialmente completa y la Fase 1 comenzó con la creación de la rama, este documento y los artefactos de contenedorización. La siguiente acción técnica es validar la imagen y añadir CI de smoke test antes de introducir PostgreSQL como dependencia obligatoria.