# Tríade Ω — Continuidad verificable entre sesiones

**Proyecto:** Tríade Ω · Agencia Digital Wataboo.  
**Alcance:** bitácora técnica del PR #187. Este documento no es la Bodega, ni una copia de memoria conversacional, ni un proceso en segundo plano.

## Propósito

Evitar que un nuevo chat, reinicio de Colab o cambio de versión confunda **lo propuesto** con **lo probado**. La memoria contextual del asistente sirve para orientar investigaciones, pero la fuente de verdad es siempre la evidencia fechada (Git, GitHub Actions, despliegues, snapshots y pruebas reales de aprendizaje).

## Separación de capas

- **Neurona Central:** hipótesis, decisiones arquitectónicas, cambios y experimentos respaldados por commits.
- **Hipotálamo Emocional:** prioridades de trabajo y objetivos expresados, sin persistir datos privados de conversaciones.
- **Bodega:** SQLite/Drive del organismo original; jamás sobrescribir, migrar o extraer automáticamente por usar este documento.
- **Cristal de verificación:** CI y pruebas independientes; nunca convertir una señal de salud o telemetría en prueba de aprendizaje.
- **Guardia de integridad:** cambios solo en ramas, con pruebas, trazabilidad y reversión posible.

## Esquema mínimo de un checkpoint operativo

Al retomar trabajo o cerrar un ciclo, anotar SOLO datos técnicos no sensibles y la fuente de cada afirmación:

```yaml
observed_at_utc: "YYYY-MM-DDTHH:MM:SSZ"
github:
  repository: "WatabooColosus/triadees"
  pr: 187
  branch: "..."
  head_sha: "..."
  ci: { passed: [], failed: [], pending: [] }
render:
  service: "triade-omega-mcp"
  deployed_sha: "..."
  deployment_status: "live|failed|unknown"
colab:
  runtime_live_proven: false
  outbound_telemetry_fresh_proven: false
bodega:
  independent_integrity_verification: false
learning:
  baseline_evaluated: false
  application_observed: false
  independent_transfer_evaluated: false
  certified: false
next_action: "..."
```

Los campos desconocidos se dejan como **unknown**; jamás convertir la ausencia de evidencia en cero real, salud positiva o progreso logrado.

## Registro inicial — 2026-11-07 (UTC)

- **PR #187:** rama `feat/chatgpt-actions-safe-gateway-20261106`; el 7 de noviembre se observaron nueve flujos aprobados y `Runtime Truth CI` fallido por formato en dos archivos.
- **Corrección aplicada en la rama:** commits `0c2fc1f` (tests) y `5535b33` (herramienta Colab), solo para Ruff. La nueva corrida pasó por la fase de formato y continuó con cobertura Python 3.11/3.12. El cierre de toda CI requiere comprobación posterior.
- **Render:** último despliegue live observado `e7a8751`, servicio público en `https://triade-omega-mcp.onrender.com/`. Auto-deploy desactivado; este SHA no equivale al HEAD del PR.
- **Colab:** no hay kernel original conectado confirmado en esta auditoría; Render no puede encenderlo. No se ha certificado telemetría reciente de Colab ni una sesión educativa real.
- **Aprendizaje completo:** NO certificado. Los contadores, la UI y una API que responde no prueban transferencia independiente ni continuidad de Bodega.

## Procedimiento seguro de evolución

1. Leer este archivo y **volver a consultar** el HEAD y los gates actuales. Nunca confiar en este registro histórico como estado en vivo.
2. Diagnosticar usando logs específicos del commit fallido y corregir solo la causa demostrada; no silenciar tests ni desactivar controles.
3. Mantener el PR en borrador si un gate falla o queda pendiente, y registrar SHA final y evidencia de cada comprobación.
4. Para Colab, preferir telemetría autenticada **solo saliente y agregada** según `docs/TRIADE_COLAB_TELEMETRY.md`. El panel real debe estar encendido por el operador; la telemetría no expone ni sustituye la Bodega.
5. Para declarar aprendizaje, exigir sesión educativa concluida, aplicación verificable, baseline, evaluador de transferencia independiente disponible, integridad del respaldo y ausencia de regresiones.
6. Cuando exista evidencia de esos requisitos, registrar links/identificadores técnicos y solo entonces evaluar habilitación, promoción o despliegue de cambios autorizados.

## Prohibiciones

No almacenar en este archivo tokens, correos personales, nombres de usuarios, datos privados, textos de sesiones, contenido de SQLite, valores de secretos de Colab/Render ni URLs temporales privilegiadas. No copiar la Bodega a un repositorio. No inventar medidas, ejecutar comandos remotos no autenticados, fusionar PR sin gates o publicar rutas de escritura/shell.

**Regla:** toda mejora debe poder distinguirse como `idea`, `implementada`, `probada`, `desplegada` o `certificada`. Son estados diferentes.
