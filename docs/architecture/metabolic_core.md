# Metabolic Core · Núcleo Metabólico de Tríade Ω

**Versión:** 0.2.0 (Fase 3-6 — Implementado y verificado)
**Estado:** Operacional (1356 tests pasan)
**Dependencia:** Runtime v2 (autoridad canónica de ejecución)

---

## 1. Principios de diseño

1. **Runtime v2 es la autoridad canónica de ejecución.** El metabolismo no reemplaza ni duplica `AutonomousTaskStore`, `ResourceLedger`, `EffectReceipt` ni ningún componente de runtime v2.
2. **Sin conciencia ni emulación biológica.** El metabolismo es un sistema de coordinación de procesos internos, no una simulación de vida.
3. **Fail-closed.** Toda operación metabólica requiere autorización explícita. Sin permiso, no hay acción.
4. **Configurable y desactivado por defecto.** `metabolism.enabled: false` en `triade.yml`.
5. **Dry-run soportado.** Todo ciclo puede ejecutarse en modo observación sin efectos.
6. **Idempotente.** Cada necesidad metabólica tiene un `idempotency_key` único.
7. **Presupuestado.** Toda actividad tiene presupuesto de CPU, RAM, VRAM, disco, tiempo y frecuencia.
8. **Recuperable.** Tras caída, el coordinador recupera ciclos interrumpidos.

---

## 2. Arquitectura

```
┌──────────────────────────────────────────────────────────────────────┐
│                      METABOLIC COORDINATOR                            │
│  Ciclo: observe → evaluate → propose → authorize → execute → verify  │
│         → consolidate                                                 │
│                                                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │
│  │ Health   │  │ Needs   │  │ Policy   │  │ Scheduler            │  │
│  │ Sensors  │  │ Queue   │  │ Engine   │  │ (EventDrivenScheduler)│  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────────┘  │
│                                                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │
│  │ Budget   │  │ Receipts │  │ Recovery │  │ Signal Bus           │  │
│  │ Tracker  │  │ Ledger   │  │ Manager  │  │ (MetabolicSignal)     │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────────┘  │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ USES
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      RUNTIME V2 (canonical)                           │
│  AutonomousTaskStore · ResourceLedger · EffectReceipt ·               │
│  ExecutionResult · CanonicalTaskArtifacts · LiveHeartbeat             │
│  ServiceHealth · RuntimeWatchdog · RuntimeRecovery                    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Componentes

### 3.1 MetabolicCoordinator

Orquesta el ciclo completo. Es el punto de entrada único.

```
Ciclo: observe → evaluate → propose → authorize → execute → verify → consolidate
         ↑                                                        |
         └────────────────────── LOOP ────────────────────────────┘
```

- `tick()` → ejecuta un ciclo completo
- `recover()` → recupera ciclos interrumpidos
- `shutdown()` → apagado limpio
- `status()` → estado observable

### 3.2 MetabolicSignal

Señal que representa un evento metabólico. Se emite al inicio/fin de cada etapa.

```python
@dataclass
class MetabolicSignal:
    signal_id: str
    cycle: int
    stage: str  # observe | evaluate | propose | authorize | execute | verify | consolidate
    need_id: str | None
    status: str  # started | completed | failed | skipped
    reason: str
    timestamp: str
    budget_used: ResourceUsageReceipt | None
```

### 3.3 MetabolicNeed

Necesidad metabólica identificada. Cada necesidad tiene:

```python
@dataclass
class MetabolicNeed:
    need_id: str
    kind: str  # health_check | memory_maintenance | contradiction_detection |
               # backlog_review | artifact_review | lease_supervision |
               # snapshot_maintenance | internal_task_generation
    priority: int  # 0-100 (higher = more urgent)
    evidence: dict  # por qué se detectó esta necesidad
    estimated_cost: ResourceBudget
    risk: str  # none | low | medium | high | critical
    min_frequency_seconds: float
    cooldown_seconds: float
    expires_at: str | None
    authorization_policy: str  # always | on_threshold | never
    success_condition: str  # qué constituye éxito
```

### 3.4 MetabolicPolicy

Política que define qué necesidades pueden ejecutarse, bajo qué condiciones.

```python
@dataclass
class MetabolicPolicy:
    enabled_kinds: set[str]
    min_priority: int
    require_ollama: bool
    require_redis: bool
    max_concurrent_needs: int
    dry_run: bool
    allowed_modes: set[str]  # observe_only | light | full
```

### 3.5 ResourceBudget

Presupuesto de recursos para una necesidad.

```python
@dataclass
class ResourceBudget:
    cpu_seconds_max: float
    ram_mb_max: float
    vram_mb_max: float
    disk_mb_max: float
    duration_seconds_max: float
    frequency_seconds_min: float
```

### 3.6 MetabolicReceipt

Comprobante de ejecución metabólica, persistido en la DB.

```python
@dataclass
class MetabolicReceipt:
    receipt_id: str
    cycle: int
    need_id: str
    stage: str
    status: str  # success | failure | skipped | dry_run
    started_at: str
    finished_at: str
    budget_used: ResourceUsageReceipt
    artifact_ref: str | None
    effect_receipt_ref: str | None
    error: str | None
    evidence: dict
```

---

## 4. Ciclo metabólico detallado

### 4.1 Observe
- Leer health sensors (disco, RAM, CPU, GPU, Ollama, DB)
- Verificar heartbeats activos
- Revisar leases expiradas
- Examinar cola de necesidades pendientes
- Revisar backlog
- Detectar contradicciones en memoria semántica

### 4.2 Evaluate
- Priorizar necesidades detectadas
- Calcular costo estimado
- Verificar cooldown
- Verificar expiración
- Verificar presupuesto disponible

### 4.3 Propose
- Generar `MetabolicNeed` para cada necesidad evaluada
- Registrar en la cola de necesidades
- Emitir `MetabolicSignal`

### 4.4 Authorize
- Aplicar `MetabolicPolicy`
- Verificar permisos
- Verificar modo (dry-run, observe-only, etc.)
- Verificar identidad no modificada
- Verificar que no haya tarea duplicada

### 4.5 Execute
- Usar Runtime v2 (`AutonomousTaskStore`) para ejecutar
- Usar `ResourceLedger` para contabilidad
- Usar `EffectReceipt` para postcondiciones
- Aplicar backoff si es necesario

### 4.6 Verify
- Verificar postcondiciones
- Verificar artifacts generados
- Verificar presupuesto respetado
- Generar `MetabolicReceipt`

### 4.7 Consolidate
- Registrar receipt en DB
- Actualizar estado de necesidad (completada)
- Limpiar leases temporales
- Emitir señal de consolidación

---

## 5. Necesidades metabólicas planificadas

| # | Necesidad | Prioridad | Frecuencia min | Cooldown | Riesgo |
|---|---|---|---|---|---|
| N1 | Health check | 90 | 30s | 10s | none |
| N2 | Heartbeat pulse | 80 | 5s | 2s | none |
| N3 | Memory maintenance | 50 | 300s | 60s | low |
| N4 | Contradiction detection | 40 | 600s | 120s | low |
| N5 | Backlog review | 30 | 900s | 300s | medium |
| N6 | Artifact review | 30 | 3600s | 600s | low |
| N7 | Lease supervision | 70 | 60s | 15s | low |
| N8 | Snapshot maintenance | 20 | 86400s | 3600s | low |
| N9 | Internal task generation | 10 | Bajo demanda | variable | medium |
| N10 | Budget check | 60 | 120s | 30s | none |

---

## 6. Tablas SQLite

Migración: `memory/migrations/032_metabolic_core.sql`

```sql
CREATE TABLE IF NOT EXISTS metabolic_cycle (
    cycle_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    mode TEXT NOT NULL DEFAULT 'full',
    error TEXT,
    recovery_ref TEXT
);

CREATE TABLE IF NOT EXISTS metabolic_needs (
    need_id TEXT PRIMARY KEY,
    cycle_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 50,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    estimated_cost_json TEXT NOT NULL DEFAULT '{}',
    risk TEXT NOT NULL DEFAULT 'low',
    status TEXT NOT NULL DEFAULT 'pending',
    authorization_policy TEXT NOT NULL DEFAULT 'always',
    success_condition TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    result_json TEXT DEFAULT '{}',
    FOREIGN KEY (cycle_id) REFERENCES metabolic_cycle(cycle_id)
);

CREATE TABLE IF NOT EXISTS metabolic_receipts (
    receipt_id TEXT PRIMARY KEY,
    cycle_id INTEGER NOT NULL,
    need_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    cpu_seconds REAL DEFAULT 0.0,
    ram_mb REAL DEFAULT 0.0,
    duration_ms REAL DEFAULT 0.0,
    artifact_ref TEXT,
    effect_receipt_ref TEXT,
    error TEXT,
    evidence_json TEXT DEFAULT '{}',
    FOREIGN KEY (cycle_id) REFERENCES metabolic_cycle(cycle_id),
    FOREIGN KEY (need_id) REFERENCES metabolic_needs(need_id)
);

CREATE TABLE IF NOT EXISTS metabolic_signals (
    signal_id TEXT PRIMARY KEY,
    cycle_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    need_id TEXT,
    signal_status TEXT NOT NULL,
    reason TEXT,
    timestamp TEXT NOT NULL,
    budget_json TEXT DEFAULT '{}',
    FOREIGN KEY (cycle_id) REFERENCES metabolic_cycle(cycle_id)
);

CREATE TABLE IF NOT EXISTS metabolic_config (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
```

---

## 7. Presupuesto metabólico

| Recurso | Límite por ciclo | Límite por hora | Límite por día |
|---|---|---|---|
| CPU | 30s | 300s | 3600s |
| RAM | 512 MB | - | - |
| Disco (lectura) | 10 MB | 100 MB | 500 MB |
| Disco (escritura) | 5 MB | 50 MB | 250 MB |
| Duración ciclo | 60s | - | - |
| Needs por ciclo | 10 | - | - |

---

## 8. Apagado y recuperación

### Apagado limpio
1. `MetabolicCoordinator.shutdown()` establece `stop_event`
2. Espera a que el ciclo actual termine (timeout: 30s)
3. Marca ciclo como `shutdown` en DB
4. Libera leases

### Recuperación tras caída
1. Al iniciar, consulta `metabolic_cycle` por ciclos `running`
2. Para cada ciclo huérfano:
   - Marca como `interrupted`
   - Recupera necesidades con estado `running` como `recovered`
   - Re-lanza necesidades pendientes si aún son válidas
3. Retoma ciclo normal

---

## 9. Integración con runtime v2

El metabolismo **usa** runtime v2, no lo reemplaza:

| Operación metabólica | Runtime v2 component |
|---|---|
| Ejecutar tarea | `AutonomousTaskStore.enqueue()` |
| Lease de tarea metabólica | `AutonomousTaskStore.claim()` |
| Artifact | `CanonicalTaskArtifacts` |
| Receipt de efecto | `EffectReceipt` |
| Resultado de ejecución | `ExecutionResult` |
| Budget | `ResourceLedger.record()` |
| Heartbeat | `LiveHeartbeat.pulse()` |
| Health check | `ServiceHealth.inspect()` |
| Watchdog | `RuntimeWatchdog.tick()` |
| Recovery | `RuntimeRecovery.recover()` |
| Scheduler | `EventDrivenScheduler` |

---

## 10. Configuración (`triade.yml`)

```yaml
metabolism:
  enabled: false                    # Desactivado por defecto
  dry_run: false                    # Modo observación sin efectos
  interval_seconds: 30              # Intervalo entre ciclos
  max_cycles: 0                     # 0 = ilimitado
  jitter_seconds: 2.0              # Jitter para evitar thundering herd
  policy:
    min_priority: 10               # Prioridad mínima para ejecutar
    max_concurrent_needs: 5
    require_ollama: false           # No requiere Ollama
    require_redis: false            # No requiere Redis
    allowed_modes:
      - observe_only
      - light
      - full
  needs:
    health_check:
      enabled: true
      interval_seconds: 30
      priority: 90
    heartbeat:
      enabled: true
      interval_seconds: 5
      priority: 80
    memory_maintenance:
      enabled: false
      interval_seconds: 300
      priority: 50
    contradiction_detection:
      enabled: false
      interval_seconds: 600
      priority: 40
    backlog_review:
      enabled: false
      interval_seconds: 900
      priority: 30
    lease_supervision:
      enabled: true
      interval_seconds: 60
      priority: 70
    budget_check:
      enabled: true
      interval_seconds: 120
      priority: 60
```

---

## 11. API de estado

Endpoints read-only (vía API existente o CLI):

| Ruta | Descripción |
|---|---|
| `GET /api/metabolism/status` | Estado del coordinador |
| `GET /api/metabolism/cycle/{id}` | Detalle de ciclo |
| `GET /api/metabolism/needs` | Necesidades pendientes |
| `GET /api/metabolism/receipts` | Receipts recientes |
| `GET /api/metabolism/budget` | Presupuesto consumido |
| `GET /api/metabolism/health` | Health metabólico |

CLI: `triade metabolism status|cycle|needs|receipts|budget|health`

---

## 12. Reglas de seguridad

1. El metabolismo **nunca** modifica `identity_core`
2. El metabolismo **nunca** activa LoRA training automáticamente
3. El metabolismo **nunca** escribe en memoria estable sin autorización
4. El metabolismo **nunca** hace solicitudes de red externa sin permiso explícito
5. Toda operación metabólica pasa por safety/leases/fencing
6. El metabolismo respeta `safe_only`, `require_human_approval` y `sandbox_only`
7. El metabolismo falla cerrado ante cualquier condición insegura

---

## 13. Implementación (Fase 3-6)

### Módulos creados

| Módulo | Archivo | Propósito |
|---|---|---|
| Coordinator | `triade/metabolism/coordinator.py` | Ciclo completo observe→evaluate→propose→authorize→execute→verify→consolidate |
| Contracts | `triade/metabolism/contracts.py` | Dataclasses: MetabolicNeed, MetabolicPolicy, MetabolicReceipt, MetabolicSignal, ResourceBudget |
| Health | `triade/metabolism/health.py` | Sensores: DB, disco, RAM, heartbeat, leases, cola |
| Needs | `triade/metabolism/needs.py` | Detección de 10 tipos de necesidad + cooldown |
| Policy | `triade/metabolism/policy.py` | Motor de autorización basado en MetabolicPolicy |
| Budget | `triade/metabolism/budget.py` | Límites por ciclo/hora/día |
| Receipts | `triade/metabolism/receipts.py` | Ledger de comprobantes persistidos |
| Signals | `triade/metabolism/signals.py` | SignalBus emite y persiste señales |
| Scheduler | `triade/metabolism/scheduler.py` | Temporizador con jitter |
| Recovery | `triade/metabolism/recovery.py` | Recuperación de ciclos huérfanos |

### Tablas SQLite

Migración `memory/migrations/032_metabolic_core.sql`: metabolic_cycle, metabolic_needs, metabolic_receipts, metabolic_signals, metabolic_config

### API REST

| Método | Ruta | Propósito |
|---|---|---|
| GET | `/api/runtime/metabolism/status` | Estado del coordinador |
| POST | `/api/runtime/metabolism/start` | Iniciar ciclo metabólico |
| POST | `/api/runtime/metabolism/stop` | Detener ciclo metabólico |
| GET | `/api/runtime/metabolism/cycle/{id}` | Detalle de ciclo |
| GET | `/api/runtime/metabolism/needs` | Necesidades pendientes |
| GET | `/api/runtime/metabolism/receipts` | Receipts recientes |
| GET | `/api/runtime/metabolism/budget` | Presupuesto consumido |
| GET | `/api/runtime/metabolism/health` | Health metabólico |

### Configuración (`triade.yml`)

```yaml
metabolism:
  enabled: true
  dry_run: false
  mode: full
  interval_seconds: 15
```

Necesidades habilitadas por defecto: health_check, heartbeat, lease_supervision, budget_check.

### Estado operacional (verificado)

- **Always-On:** `full_local_guarded`, thread background vivo, self-test pasado
- **Metabolismo:** `full`, thread daemon vivo, ciclos cada 15s
- **Daemon workers:** activos, modo daemon, 1802 tareas completadas
- **Ollama:** 6 modelos disponibles, GPU NVIDIA L4 22GB VRAM
- **Tests:** 1356/1356 pasan (0 fallos)

### Reglas de seguridad

1. Nunca modifica `identity_core`
2. Nunca activa LoRA training automático
3. Nunca escribe en memoria estable sin autorización
4. Nunca hace solicitudes de red externa sin permiso
5. Toda operación pasa por safety/leases/fencing
6. Fallo cerrado ante cualquier condición insegura
