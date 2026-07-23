# Índice documental de Tríade Ω

## Fuentes vigentes

Leer en este orden:

1. [`../README.md`](../README.md): identidad, alcance, inicio rápido y separación entre realidad y visión.
2. [`STATUS_CURRENT.md`](STATUS_CURRENT.md): estado técnico operativo vigente.
3. [`../TECHNICAL_DEBT.md`](../TECHNICAL_DEBT.md): deuda abierta canónica y criterios de cierre.
4. [`SYSTEM_AUDIT_2026-07-23.md`](SYSTEM_AUDIT_2026-07-23.md): evidencia de la auditoría integral.
5. [`TRIADE_OS_CONTRACT.md`](TRIADE_OS_CONTRACT.md): contrato y límites de Tríade OS.

## Contratos temáticos vigentes

- Arquitectura: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- Always-On: [`ALWAYS_ON_RUNTIME.md`](ALWAYS_ON_RUNTIME.md)
- Aprendizaje: [`LEARNING.md`](LEARNING.md), [`LEARNING_EVIDENCE_BRIDGE.md`](LEARNING_EVIDENCE_BRIDGE.md)
- Memoria semántica: [`SEMANTIC_CONTINUITY.md`](SEMANTIC_CONTINUITY.md)
- Safety: [`SAFETY.md`](SAFETY.md)
- Qualia: [`QUALIA_BUS.md`](QUALIA_BUS.md)
- Federación: [`FEDERATION.md`](FEDERATION.md)
- Observabilidad: [`OBSERVABILITY.md`](OBSERVABILITY.md)
- Modelos: [`MODEL_POLICY.md`](MODEL_POLICY.md), [`OLLAMA_BLOOD.md`](OLLAMA_BLOOD.md)

## Documentos históricos

Los archivos `STATUS_*` versionados, auditorías anteriores y reportes de fases
conservan trazabilidad del desarrollo. No describen necesariamente el estado actual.
Si contradicen `STATUS_CURRENT.md` o `TECHNICAL_DEBT.md`, prevalecen estos últimos.

## Regla documental

Una capacidad debe etiquetarse como:

- `implementada`: código + pruebas/evidencia runtime;
- `experimental/parcial`: existe, pero depende del entorno o carece de validación completa;
- `visión`: todavía no está implementada.

No se usarán actividad, nombres de módulos o cantidad de ciclos como prueba de
aprendizaje, consciencia, autonomía o estabilidad.
