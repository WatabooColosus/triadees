# Tríade Ω · Estado 0.3

## Nombre de fase

```text
TRIADE_DIAGNOSTIC_AND_FULL_PERSISTENCE_0.3
```

---

## Objetivo

Convertir el MVP local SQLite en un sistema con persistencia más completa y diagnóstico operativo.

La fase 0.2 confirmó:

- Runs auditables.
- Memoria episódica en SQLite.
- Recall funcional.
- Chat local.
- Tests básicos.

La fase 0.3 agrega:

- Persistencia de `SignalPacket`.
- Persistencia de `CrystalPacket`.
- Persistencia de `SafetyPacket` como evento auditable.
- Persistencia de `VerificationReport`.
- Comando `doctor`.
- Pruebas extendidas.
- `requirements.txt` base.

---

## Comandos nuevos

### Diagnóstico

```bash
python triade_digimon.py doctor
```

### Diagnóstico dentro del chat

```text
/doctor
```

---

## Flujo actual por run

```text
input
→ create_run en SQLite
→ SignalPacket
→ signal_states
→ MemoryPacket
→ CrystalPacket
→ crystal_states
→ PlanPacket
→ SafetyPacket
→ evento safety en knowledge_patterns
→ OutputPacket
→ episodic_memory
→ VerificationReport
→ verification_reports
→ artefactos JSON
→ integrity.json
→ CLOSED
```

---

## Nuevos IDs en integrity.json

`integrity.json` ahora registra:

```json
{
  "episode_id": 1,
  "signal_id": 1,
  "crystal_id": 1,
  "safety_id": 1,
  "verification_report_id": 1
}
```

---

## Validación esperada

Después de hacer `git pull` en la PC local:

```bash
cd ~/triadees
source .venv/bin/activate
pip install -r requirements.txt
pytest
python triade_digimon.py run "Validación fase 0.3"
python triade_digimon.py doctor
```

Resultado esperado:

- `pytest` debe pasar.
- `memory_diff.stored` debe ser `true`.
- `memory_diff` debe incluir `signal_id`, `crystal_id`, `safety_id`, `verification_report_id`.
- `doctor` debe mostrar conteos mayores a cero en `runs`, `episodes`, `signals`, `crystals`, `safety_events` y `verification_reports`.

---

## Estado

```text
LOCAL_PC_RUNNING_TRIADE_0.2 → TRIADE_DIAGNOSTIC_AND_FULL_PERSISTENCE_0.3
```

---

## Siguiente fase recomendada

```text
TRIADE_OLLAMA_ADAPTER_0.4
```

Prioridades:

1. Crear adaptador local para Ollama.
2. Agregar configuración de modelos por rol.
3. Permitir modelo Hipotálamo y modelo Central.
4. Mantener fallback por plantilla si Ollama no está disponible.
5. Registrar modelo usado en cada run.
