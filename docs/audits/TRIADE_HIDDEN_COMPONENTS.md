# TRIADE_HIDDEN_COMPONENTS.md — Componentes que no se ven a simple vista

**SHA:** `e3cba75` · **Fecha:** 2026-07-31
**Cobertura:** metabolismo (Fase 4) + hallazgos de Fases 2–3. Las áreas de las
Fases 5–16 (workers en detalle, runner, neuronas, memoria, modelos, LoRA, Qualia)
**no** están cubiertas aquí todavía.

Marcas: **[E]** evidencia · **[I]** inferencia · **[H]** hipótesis · **[NV]** no verificado.

---

## 1. Catálogo de necesidades metabólicas: 10 declaradas, 4 cableadas, 3 vivas

**[E]** `triade/metabolism/needs.py:16-79` declara un catálogo de **10** tipos de
necesidad:

```
health_check          heartbeat            lease_supervision    budget_check
memory_maintenance    contradiction_detection    backlog_review
artifact_review       snapshot_maintenance       internal_task_generation
```

**[E]** Pero el detector real `detect()` (`needs.py:98-132`) **solo puede crear 4**:

| Kind | Línea que lo crea | Condición |
|---|---|---|
| `health_check` | `needs.py:98` y `:102` | siempre (ok o degradado) |
| `heartbeat` | `needs.py:112` y `:118` | siempre (ok o degradado) |
| `lease_supervision` | `needs.py:125` | **solo si** `not leases["ok"]` |
| `budget_check` | `needs.py:132` | siempre (cada ciclo) |

**[E]** El contrato de política (`contracts.py:64` y `:88`) fija el conjunto
habilitado exactamente a esos mismos 4. **[E]** El dispatcher del coordinador
(`coordinator.py:442-448`) tiene handler exactamente para esos mismos 4.

### Conclusión: 6 necesidades son solo entradas de diccionario

**[E]** `memory_maintenance`, `contradiction_detection`, `backlog_review`,
`artifact_review`, `snapshot_maintenance`, `internal_task_generation` **no tienen
detector, ni política, ni handler**. Existen únicamente como claves del catálogo
en `needs.py:44-79`. **No pueden dispararse jamás.**

Estado según la taxonomía del encargo: **`implemented_not_connected`** (en rigor,
ni siquiera implementadas: solo declaradas).

**[E] Confirmación en datos de producción** — `SELECT kind, COUNT(*) FROM
metabolic_needs GROUP BY kind` sobre la DB real devuelve **solo 3 kinds**:

| Kind | completed | running | pending |
|---|---|---|---|
| `health_check` | 1806 | 0 | 10 |
| `heartbeat` | 1806 | 0 | 10 |
| `budget_check` | 841 | 67 | 6 |

**[E]** `lease_supervision`: **0 filas**. Está cableado y habilitado, pero su
condición (`needs.py:121`, `if not leases.get("ok", True)`) nunca se cumplió.
**Nota de honestidad [I]: esto es comportamiento correcto**, no un defecto — es un
detector condicional que no ha tenido motivo para dispararse. No debe contarse
como componente roto.

---

## 2. El metabolismo SÍ ejecuta de verdad (contra la hipótesis de simulación)

**[E]** Volumen real en la DB de producción:

| Tabla | Filas |
|---|---|
| `metabolic_signals` | 25.079 |
| `metabolic_receipts` | 9.700 |
| `metabolic_needs` | 4.543 |
| `metabolic_cycle` | 1.817 |
| `metabolic_config` | **0** |

**[E]** Distribución real de recibos por etapa:

| Etapa | Estado | Nº |
|---|---|---|
| `execute` | success | 4453 |
| `verify` | passed | 4325 |
| `evaluate` | skipped | 902 |
| `authorize` | **denied** | **20** |
| `execute` | dry_run | 6 |

**[E] El Policy Engine deniega de verdad** (20 `authorize/denied`): no es un gate
decorativo. **[E] La etapa `verify` existe y se ejecuta** (4325 `passed`).

**[I] Discrepancia a revisar:** 4453 `execute/success` frente a 4325
`verify/passed` → **128 ejecuciones sin un verify registrado como aprobado**.
**[NV]** No se determinó en esta fase si corresponden a verificaciones fallidas,
omitidas, o a un desfase temporal de escritura.

**[E] `metabolic_config` está vacía (0 filas)** pese a que
`apps/single_port_app.py:118` llama `mc.load_config()` en el arranque.
**[H]** La configuración se resuelve por defecto/entorno sin persistirse. **[NV]**
No verificado qué implica para la reproducibilidad de la política.

---

## 3. Estados metabólicos permanentemente huérfanos (P1)

**[E]** 93 necesidades llevan atascadas desde el 2026-07-30 (ventana 03:21–04:22),
mientras el sistema ha ejecutado 1817 ciclos desde entonces (necesidad más reciente:
2026-07-31T01:52):

| Estado atascado | Nº | Estado del ciclo padre | ¿Ciclo cerrado? |
|---|---|---|---|
| `running` | **67** | `failed` | **sí** (`finished_at` no nulo) |
| `pending` | **26** | `completed` | **sí** |

**[E] Causa raíz exacta** — `triade/metabolism/recovery.py:16-23`:

```python
def recover_interrupted_cycles(self):
    ...
    WHERE status IN ('running','starting') AND finished_at IS NULL
```

y `:45-53` (`_recover_needs`) solo repara necesidades **del ciclo que está
recuperando**:

```python
WHERE cycle_id=? AND status='running'
   → UPDATE metabolic_needs SET status='recovered' WHERE need_id=?
```

**Consecuencia [E]:** un ciclo que terminó como `failed` o `completed` (con
`finished_at` puesto) **nunca vuelve a ser escaneado**. Sus necesidades que
quedaron en `running`/`pending` **no tienen ninguna ruta de recuperación**. Son
huérfanas permanentes.

**[E]** Estados reales de `metabolic_cycle`: 1754 `completed`, **67 `failed`**,
2 `interrupted`. La tasa de ciclos fallidos es 67/1817 ≈ **3,7 %**, y cada uno
dejó necesidades colgadas.

**Impacto [I]:** no bloquea el sistema (sigue creando ciclos nuevos), pero
contamina permanentemente cualquier métrica de backlog y deja trabajo declarado
como "en curso" que nadie ejecutará nunca.

---

## 4. Componentes ocultos ya identificados en fases anteriores

**[E]** Registrados en `TRIADE_PROCESS_TREE.md` y `TRIADE_GAPS_AND_RISKS.md`:

- Hilo `triade-workers-always-on` dentro del proceso API que **siempre pierde**
  la carrera del lock y muere, pero se reporta como `running`.
- `EventDrivenScheduler` cooperativo (no es un hilo) dentro del bucle de workers.
- Subproceso hijo efímero por tarea (`governed_task_executor.py:226`).
- 5 de 7 hilos daemon sin ruta de apagado ordenado.

---

## 5. Pendiente de censar [NV]

No cubierto todavía en ninguna fase ejecutada: QualiaBus y sus 4 tipos de paquete
(¿tienen consumidor real?), Cristal temporal (¿influye en decisiones?),
contradiction detection / cuarentena semántica, `goals` y planificación autónoma,
`GovernedPlanDispatcher` (ya sabido: probado sin caller de producción),
`neuron_factory` (ya sabido: solo self_improvement + dashboards), censo exhaustivo
de `except` silenciosos, TODO/FIXME, y funciones llamadas solo por tests.
