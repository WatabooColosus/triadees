# Deuda técnica vigente · Tríade Ω

Corte: 2026-07-23. Esta es la lista canónica de deuda abierta. Los reportes de
versiones anteriores son históricos.

## P0 · Continuidad y recuperación de memoria

- SQLite persiste episodios y memoria semántica, pero guardar no garantiza recordar.
- Falta extracción general de hechos, preferencias, correcciones y relaciones sin
  programar respuestas especiales.
- Falta identidad de usuario autenticada para aislar memoria en una web pública.
- Faltan backups cifrados, retención, exportación y restauración probada.
- La promoción estable debe seguir exigiendo baseline, evidencia y reversibilidad.

## P0 · Operación pública y seguridad

- El modo público sin API key bloquea administración, pero no sustituye autenticación,
  cuotas, separación multiusuario ni protección antiabuso de producción.
- La URL pública depende del ciclo de vida del Cloudspace.
- Faltan dominio/ingress persistente, estrategia de secretos, backups y recuperación.

## P1 · Always-On y scheduler adaptativo

- El intervalo fijo de 60 segundos mezcla tareas ligeras y costosas.
- Falta separar heartbeat (30–60 s), aprendizaje/refutación (5–15 min) y tests
  profundos (10–30 min o por evento).
- Falta watchdog explícito para recuperar el hilo Always-On si muere.
- Deben medirse novedad, duplicados, utilidad por ciclo, presión térmica y recursos.

## P1 · Memoria emocional longitudinal

- Hipotálamo interpreta cada turno y produce PV-7, pero no conserva un estado
  emocional agregado y aislado por sesión.
- PV-7 ejecutable usa `[0,1]`; cualquier formulación bipolar pertenece a la teoría.

## P1 · Aprendizaje autónomo verificable

- El runtime crea, evalúa y verifica candidatos, pero no toda conversación produce
  conocimiento útil ni debe hacerlo.
- Falta convertir fallos de coherencia, correcciones y repetición en evaluaciones de
  mejora reproducibles, no solo más candidatos.
- La adquisición de modelos usa catálogo permitido; no descubre ni adopta modelos
  arbitrarios de Internet, deliberadamente.

## P1 · Orquestación multi-modelo

- Hay router y asignaciones por rol, pero el Runner principal no despacha N modelos
  dinámicamente por subtarea/pensamiento.
- Faltan suites A/B por rol, métricas de calidad/latencia y política de descarga o
  descarga de GPU basada en recursos.
- `triade-omega` deriva de Qwen2.5 mediante Modelfile; no es entrenamiento fundacional propio.

## P1 · Federación real

- Existen contratos, firma, registro, Edge y Bodega Global federada.
- En el corte auditado no hay nodos remotos activos sostenidos.
- Faltan identidad persistente, reputación, revocación, expiración, cuarentena y
  pruebas prolongadas entre servidores/dispositivos reales.
- Android no aporta inferencia LLM real sin backend nativo y modelo instalado.

## P2 · Modularidad y mantenibilidad

- `runner.py`, `bodega.py`, `triade_digimon.py` y las rutas API concentran demasiadas responsabilidades.
- Persisten wrappers y endpoints legacy que aumentan superficie de mantenimiento.
- Los contratos mezclan dataclasses y Pydantic.
- Falta normalizar métricas históricas, latencias y causas de fallback por componente.

## P2 · Capacidades pendientes

- `gemma3:4b` permite comprensión visual compatible, no generación de imágenes.
- Falta un motor generativo visual separado y su evaluación de seguridad/recursos.
- Tríade OS es un plano de control sobre Linux; no tiene kernel, drivers ni aislamiento
  de procesos propio.

## Deuda resuelta que no debe reabrirse como pendiente

- SQLite, esquema y artefactos auditables por run existen.
- React SPA single-port, tests, Safety, QualiaBus, Ollama y Model Router existen.
- Central, Hipotálamo, Bodega, Cristal, Creadora y Formativa tienen implementación.
- `identity_core` está protegido y la memoria candidata no influye como verdad estable.

## Criterio para cerrar deuda

Una deuda solo se considera cerrada con código, pruebas, evidencia runtime,
documentación actualizada y una ruta de reversión. Actividad, número de ciclos o
cantidad de neuronas no sustituyen mejora demostrada.
