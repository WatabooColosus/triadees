# Estado del MVP Real · Tríade Ω

## Fecha de fase

Fase registrada como transición de MVP conceptual a MVP real con memoria local SQLite.

---

## Qué cambió

Tríade Ω ya no es únicamente documentación ni un runner sin persistencia.

En esta fase se agregó:

- Bodega conectada a SQLite.
- Inicialización automática del esquema `schemas.sql`.
- Creación real de registros en `runs`.
- Guardado real de episodios en `episodic_memory`.
- Recuperación básica de identidad desde `identity_core`.
- Búsqueda simple en memoria episódica y semántica.
- CLI con comandos `run`, `chat` y `recall`.
- Pruebas básicas del runner.

---

## Comandos actuales

### Ejecutar un run

```bash
python triade_digimon.py run "Hola Tríade, crea tu primer run real"
```

### Abrir chat interactivo

```bash
python triade_digimon.py chat
```

Comandos internos:

```text
/exit
/recall <texto>
```

### Consultar memoria

```bash
python triade_digimon.py recall memoria
```

---

## Evidencia generada por run

Cada run crea una carpeta:

```text
runs/run-YYYYMMDD-HHMMSS-xxxxxxxx/
```

Con:

```text
input.json
signals.json
memory.json
crystal.json
plan.json
safety.json
output.json
memory_diff.json
report.json
integrity.json
CLOSED
```

Además, guarda un episodio en SQLite.

---

## Base de datos

Ruta por defecto:

```text
triade/memory/triade.db
```

Esquema:

```text
triade/memory/schemas.sql
```

Tablas usadas en esta fase:

- `identity_core`
- `runs`
- `episodic_memory`
- `semantic_memory`

Tablas preparadas para fases siguientes:

- `neurons`
- `neuron_training`
- `signal_states`
- `crystal_states`
- `learning_queue`
- `knowledge_patterns`
- `federated_nodes`
- `federated_exchange_log`
- `verification_reports`
- `goals`

---

## Limitaciones actuales

> ⚠️ **Documento histórico.** Esta sección describe el hito
> `MVP_REAL_SQLITE_0.1`. Varias de estas limitaciones ya fueron superadas en
> fases posteriores (1.6–1.9). Para el estado vigente consulta
> `AUDIT_REPORT.md` y `ROADMAP.md` en la raíz del repositorio.

Limitaciones tal como se registraron en el hito `MVP_REAL_SQLITE_0.1`
(la mayoría ya resueltas — se conservan como traza histórica):

- ~~El lenguaje de respuesta todavía es una plantilla MVP.~~ → Central usa Ollama con fallback por plantilla.
- ~~No hay integración real con modelos locales Ollama.~~ → Integrada (Hipotálamo + Central) con Model Router por hardware.
- La búsqueda de memoria episódica/keyword sigue siendo simple por términos (la semántica vectorial 1.9 es opt-in).
- ~~No persiste señales, cristal, safety ni verification reports.~~ → Persistidos en tablas dedicadas.
- ~~No existe API FastAPI.~~ → Existe (`apps/`), con 4 workflows n8n y units systemd.

---

## Siguiente fase recomendada

1. Persistir `SignalPacket`, `CrystalPacket`, `SafetyPacket` y `VerificationReport` en SQLite.
2. Agregar adaptador de modelo local, inicialmente Ollama.
3. Hacer que Central pueda usar un modelo para generar respuestas reales.
4. Agregar comando `doctor` para diagnosticar instalación.
5. Agregar `requirements.txt` y guía de instalación.
6. Crear API local con FastAPI.

---

## Criterio de realidad alcanzado

El sistema ya cumple tres condiciones mínimas de realidad operativa:

1. Ejecuta código local.
2. Genera evidencia auditable por run.
3. Guarda memoria persistente en SQLite.

Por tanto, esta fase se registra como:

```text
MVP_REAL_SQLITE_0.1
```
