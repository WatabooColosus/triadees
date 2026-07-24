# T-001: Hipotálamo PV-14 — Especificación de Implementación

## Objetivo
Convertir el Hipotálamo de regulador emocional básico en un regulador cognitivo completo con virtudes/vicios operativos, señales de hardware, y tensiones.

## Estado Actual (Archivos Existentes)

### `triade/core/hypothalamus.py` (321 líneas)
- **Clase `Hypothalamus`**: `analyze(InputPacket) → SignalPacket`
- `apply_qualia_signals(signals, qualia_signals, threshold)` — modula señales con Qualia
- `MOOD_PV7_MODULATION` — mapea 8 emociones a multiplicadores PV-7
- `mood` property → EmotionalState cached
- `load_mood()` → EmotionalState from SQLite

### `triade/memory/hypothalamus_store.py` (379 líneas)
- **`EmotionalState`** (dataclass): valence, arousal, dominance, primary_emotion, fatigue, pv7_baseline (dict), run_count, last_active_at
- **`HypothalamusStateStore`**: save/load/update_fatigue/reinforce/learn_pattern/recall_pattern/decay_patterns
- **`mood_from_signals()`** — función pura: señales → nuevo EmotionalState
- **`compute_primary_emotion()`** — VAD → emoción primaria
- **`fatigue_decay()`** — decaimiento temporal de fatiga

### `triade/qualia/` (9 archivos)
- QualiaBus, QualiaRouter, QualiaStore, QualiaState
- NeuronExperience, QualiaSignal, CentralKnowledgePacket, StorageMemoryPacket
- Crystal class en `triade/core/crystal.py`

## Qué Se Va a Crear/Modificar

### 1. ViceVirtueState (wrapper retrocompatible)

**Archivo nuevo:** `triade/hypothalamus/vice_virtue.py`

```python
@dataclass
class ViceVirtueState:
    """Wrapper retrocompatible sobre el dict pv7_baseline.
    
    Agrega: cálculo de tensiones, pecados operativos, decaimiento,
    y validación — sin romper código existente que usa el dict.
    """
    _virtues: dict[str, float]  # pv7_baseline existente
    
    # Las 7 virtudes (PV-7) — ya existen como keys del dict
    # Los 7 pecados operativos — opuestos de las virtudes
    
    VIRTUE_SIN mapping = {
        "humildad": "orgullo",
        "generosidad": "avaricia", 
        "respeto": "desprecio",
        "paciencia": "impaciencia",
        "templanza": "exceso",
        "caridad": "indiferencia",
        "diligencia": "pereza",
    }
    
    # Métodos:
    - virtue(name) → float  # getter retrocompatible
    - sin(name) → float     # pecado opuesto = 1.0 - virtue
    - tension(virtue_a, virtue_b) → float  # conflicto entre virtudes
    - all_tensions() → dict  # todas las tensiones activas
    - decay(rate, seconds) → None  # decaimiento temporal
    - to_dict() → dict  # exportar como dict (compatibilidad)
    - from_dict(d) → ViceVirtueState  # importar desde dict
```

### 2. Pecados Operativos

Los 7 pecados son el opuesto métrico de las 7 virtudes:
- `orgullo` = 1.0 - `humildad`
- `avaricia` = 1.0 - `generosidad`
- `desprecio` = 1.0 - `respeto`
- `impaciencia` = 1.0 - `paciencia`
- `exceso` = 1.0 - `templanza`
- `indiferencia` = 1.0 - `caridad`
- `pereza` = 1.0 - `diligencia`

Se calculan automáticamente, no se almacenan separadamente.

### 3. Tensiones

Las tensiones miden conflicto entre virtudes:
- `tension("humildad", "diligencia")` — ser humilde vs ser diligente
- `tension("paciencia", "generosidad")` — esperar vs dar
- `all_tensions()` retorna las tensiones con valor > 0.3

### 4. Senses (Señales de Hardware)

**Archivo nuevo:** `triade/hypothalamus/senses.py`

```python
class SystemSenses:
    """Captura señales del hardware y del sistema."""
    
    def cpu_load() -> float          # 0.0-1.0 via psutil
    def ram_usage() -> float         # 0.0-1.0 via psutil
    def gpu_utilization() -> float   # 0.0-1.0 via nvidia-smi
    def gpu_memory_used() -> float   # 0.0-1.0 via nvidia-smi
    def gpu_temperature() -> int     # Celsius via nvidia-smi
    def disk_usage() -> float        # 0.0-1.0 via psutil
    def network_latency() -> float   # ms (si disponible)
    
    def scheduler_heartbeat() -> dict  # desde worker_state
    def error_rate() -> float          # desde error_bus (última hora)
    def active_workers() -> int        # desde worker_state
    
    def snapshot() -> SystemSnapshot   # todas las señales juntas
```

### 5. Cognitive Load

**Archivo nuevo:** `triade/hypothalamus/cognitive_load.py`

```python
class CognitiveLoad:
    """Mide la carga cognitiva del sistema."""
    
    def compute(
        active_runs: int,
        pending_tasks: int,
        memory_pressure: float,
        gpu_pressure: float,
        recent_errors: int,
    ) -> float  # 0.0-1.0
    
    # Señales:
    - Curiosidad: basada en novedad de la query
    - Incertidumbre: basada en confianza de respuestas previas
    - Fatiga por componente: CPU, RAM, GPU, Worker individual
```

### 6. Persistencia Expandida

**Migration:** `triade/memory/migrations/006_hypothalamus_pv14.sql`

```sql
-- Expandir hypothalamus_state con nuevas columnas
ALTER TABLE hypothalamus_state ADD COLUMN cpu_load REAL DEFAULT 0.0;
ALTER TABLE hypothalamus_state ADD COLUMN ram_usage REAL DEFAULT 0.0;
ALTER TABLE hypothalamus_state ADD COLUMN gpu_utilization REAL DEFAULT 0.0;
ALTER TABLE hypothalamus_state ADD COLUMN gpu_memory_used REAL DEFAULT 0.0;
ALTER TABLE hypothalamus_state ADD COLUMN cognitive_load REAL DEFAULT 0.0;
ALTER TABLE hypothalamus_state ADD COLUMN curiosity REAL DEFAULT 0.0;
ALTER TABLE hypothalamus_state ADD COLUMN uncertainty REAL DEFAULT 0.0;
ALTER TABLE hypothalamus_state ADD COLUMN tensions_json TEXT DEFAULT '{}';

-- Tabla de lecturas de hardware
CREATE TABLE IF NOT EXISTS hardware_senses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
```

### 7. Integración con Hipotálamo Existente

**Modificar:** `triade/core/hypothalamus.py`

- `analyze()` ahora también:
  1. Captura `SystemSenses.snapshot()`
  2. Calcula `CognitiveLoad.compute()`
  3. Actualiza `ViceVirtueState` con decay temporal
  4. Calcula tensiones
  5. Incluye todo en el `SignalPacket` resultante

**Modificar:** `triade/memory/hypothalamus_store.py`

- `EmotionalState` ahora incluye:
  - `cpu_load`, `ram_usage`, `gpu_utilization`, `gpu_memory_used`
  - `cognitive_load`, `curiosity`, `uncertainty`
  - `tensions: dict[str, float]`
  - `vice_virtue: ViceVirtueState` (o se mantiene como pv7_baseline dict)

### 8. Integración con Runner

**Modificar:** `runner.py`

- El runner ahora pasa señales del scheduler y errores al Hipotálamo
- El Hipotálamo produce un `SignalPacket` más rico que alimenta a Central

## Orden de Implementación

1. Crear `triade/hypothalamus/` package
2. Crear `vice_virtue.py` con ViceVirtueState
3. Crear `senses.py` con SystemSenses
4. Crear `cognitive_load.py` con CognitiveLoad
5. Ejecutar migration 006
6. Modificar `hypothalamus_store.py` para EmotionalState expandido
7. Modificar `hypothalamus.py` para integrar todo
8. Modificar `runner.py` para pasar señales
9. Tests
10. Smoke test completo

## Criterios de Aceptación

- [ ] ViceVirtueState funciona como wrapper retrocompatible (dict existente sigue funcionando)
- [ ] 7 pecados operativos se calculan correctamente
- [ ] Tensiones se calculan entre pares de virtudes
- [ ] SystemSenses captura CPU/RAM/GPU correctamente
- [ ] CognitiveLoad se actualiza por run
- [ ] EmotionalState persiste con nuevas columnas
- [ ] El runner completo funciona sin errores
- [ ] Health endpoint sigue verde
- [ ] Todos los tests existentes pasan
