# Auditoría completa · Tríade Ω · 2026-07-30

Auditoría en 4 fases pedida explícitamente sin simulación: solo evidencia
verificada en vivo (logs reales, stack traces reales, DB real, tests reales)
y con seguimiento en git después de cada fase. Rango de commits:
`b0613ea..8274ded`.

## Fase 1 · Estabilización de arranque/reinicio

Commits `7d4b78d`, `a10452d`.

- **Corregido:** `triade-ollama.service` en loop de reinicio infinito
  (150+ reintentos) porque `on_start.sh` (hook de Lightning Studio) competía
  con systemd por el puerto. `on_start.sh` ahora usa `systemctl start`
  idempotente.
- **Corregido:** contradicción real en el Resource Governor —
  `degradation_reason` decía "permitido" pero el sistema degradaba a
  `observe_only` de todos modos. Causa: se mezclaban dos vocabularios de
  modo distintos, y faltaban `TRIADE_RUNTIME_MODE`/`TRIADE_RUNTIME_ENABLED`
  en `/etc/triade/triade.env` (variables no documentadas en ningún
  `.env.example`). `effective_mode` pasó de `observe_only` a
  `full_local_guarded` real, verificado en vivo.
- **Corregido:** `deploy/systemd/*` desincronizado de lo realmente instalado;
  resincronizado byte a byte, incluido `triade-ollama.service` que no
  estaba versionado.
- **Efecto colateral real detectado y corregido en vivo:** al activarse
  `full_local_guarded` de verdad por primera vez, el dashboard y el chat se
  colgaron 60s+ (reportado por el usuario mientras observaba). Causa:
  `OLLAMA_MAX_LOADED_MODELS=1` forzaba descargar/cargar modelos en cada
  petición de embedding. Subido a 3 modelos simultáneos (22 GB de VRAM
  libres de 23 GB); verificado con evidencia: dashboard de HTTP 000 (60s) a
  2.7s, chat completó con contenido real en 23.7s.
- Deuda documentada, no oculta: heartbeat intermitente >60s sin causa
  confirmada, y discrepancia real Ruff/mypy vs "cero" declarado (18 + 1
  errores reales en el baseline, no simulados).

## Fase 2 · Auditoría por órgano (6 agentes de exploración en paralelo)

Commit `df53aee`. Verificación de conectividad real (call sites, no
documentación) de Central/Neuronas, Hipotálamo/Bodega/Cristal,
Workers/Learning, LoRA/PEFT, Federación/nodo Android, superficies de
entrada. Detalle completo en `ARCHITECTURE_MAP.md` (marcado
`[VERIFICADO 2026-07-30]`).

Hallazgos principales:
- N Creadora/Formadora/Registry **sí** están conectadas (el mapa decía lo
  contrario, estaba desactualizado).
- La duplicación de apps (`chat_ui_app.py` etc.) ya la había resuelto el
  propio proyecto un día antes; el mapa describía archivos inexistentes.
- Nodo Android: 1296 líneas de Java funcional, no un esqueleto.
- LoRA/PEFT: entrenó de verdad con evidencia en DB/disco; el bloqueo de
  aprobación humana frena de verdad en código.
- Living Workers: 19 task types reales, no 10 (README subestimado).
- Código muerto y vestigial identificado para actuar en Fase 3.
- Riesgo: carpeta `systemd/` legada (otra máquina) seguía siendo tocada por
  un worker autónomo del propio sistema.

## Fase 3 · Cierre de brechas

Commit `8274ded`.

- **Corregido:** el ciclo 24/7 de workers usaba un `CrystalPacket` estático
  en vez de `Crystal.regulate()` real — el Cristal solo operaba en
  conversaciones. Conectado (regulación pura, sin I/O); verificado con
  tareas reales completando `status=ok` tras el reinicio del servicio.
- **Eliminado** código muerto confirmado con grep exhaustivo (cero
  referencias en todo el repo, incluidos tests):
  `workers/state_machine.py`, `workers/lease_retry_breaker.py`,
  `federation/merge.py`.
- **Corrección propia:** `GovernedPlanDispatcher` y `embed_pending()` NO
  son código muerto (tienen tests reales) — corregido tras verificación más
  profunda para no borrar por error ni afirmar de más.
- `systemd/DEPRECATED.md` añadido para frenar instalaciones accidentales de
  la carpeta legada.
- **Documentados sin corregir** (rutas de seguridad/reinicio críticas; un
  parche apresurado podría ser peor que el bug): bug real de detección de
  reutilización de PID en `RuntimeProcessLock.inspect()`, y una segunda
  discrepancia con "pytest 100%" (test de `STATUS_CURRENT.md`).

## Fase 4 · Estado final verificado

```
triade-ollama.service    active running
triade-api.service       active running
triade-workers.service   active running
triade-watchdog.service  active running
always-on effective_mode = full_local_guarded, degraded_by_governor = false
repo: limpio, HEAD = 8274ded, en sync con origin/main
```

## Pendientes reales para continuar (no cerrados en esta sesión)

1. Bug de identidad de locks (`RuntimeProcessLock`) — requiere rediseño del
   token, no un parche de comparación.
2. Confirmar si `learning_outcome_score`/`learning_outcome_evidence_ref` se
   están poblando en producción para que el Learning Pipeline promueva
   candidatos de verdad.
3. Decidir si `GovernedPlanDispatcher`/`execute_plan_steps` se conectan al
   runner real o se documentan como capacidad deliberadamente inactiva.
4. Ventanas de certificación 24h/72h y CI verde sobre el SHA final
   (`TRIADE-VERIFY-v1`) — no se pueden fingir ni acelerar; siguen pendientes
   por diseño.
5. `docs/STATUS_CURRENT.md` sigue afirmando "Ruff/mypy/pytest cero al 100%"
   sin ser cierto en este entorno — corregir el documento o cerrar la deuda
   real, no ambas cosas a medias.
