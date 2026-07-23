# Aprendizaje Controlado · Tríade Ω

## Propósito

Este documento define cómo Tríade Ω puede aprender de forma progresiva, verificable y segura sin contaminar su memoria estable ni alterar su identidad núcleo sin aprobación.

El aprendizaje de Tríade no es acumulación automática. Es un proceso con filtros, estados, fuentes, pruebas y consolidación.

---

## 1. Principio Base

Ningún aprendizaje nuevo entra directamente a la memoria estable.

Todo aprendizaje debe pasar por:

```text
descubrimiento → extracción → normalización → evaluación → sandbox → test → verificación → decisión → consolidación
```

---

## 2. Fuentes de Aprendizaje

Tríade puede ingerir candidatos desde:

- Conversaciones autorizadas.
- Documentos cargados.
- Repositorios.
- Web pública solicitada explícitamente y con fuentes.
- Modelos locales.
- Nodos federados autorizados.
- Resultados de herramientas.
- Experimentos del sandbox.

Cada fuente debe registrarse con fecha, tipo, confianza y estado. Ingerir o guardar
un candidato no demuestra que el sistema haya aprendido.

---

## 3. Estados del Aprendizaje

Estados ejecutables de `LearningPipeline`:

```text
candidate → evaluated → verified → validated_in_runs → consolidated
         ↘ rejected                                      ↘ archived
```

### candidate
Idea, patrón o dato detectado pero aún no procesado.

### evaluated
Contenido evaluado por utilidad, riesgo y coherencia.

### verified
Contenido aprobado por verificación.

### validated_in_runs
Contenido usado en runs suficientes con resultado medido contra baseline y sin
regresiones críticas.

### consolidated
Contenido guardado como memoria estable o patrón reutilizable.

### rejected
Contenido descartado por baja calidad, riesgo o falsedad.

### archived
Contenido conservado como histórico, no activo.

Extracción, normalización, sandbox y tests siguen siendo pasos/evidencias del
proceso, pero no se presentan como estados persistidos si el código no los usa así.

---

## 4. LearningCandidate

Estructura mínima:

```json
{
  "candidate_id": "string",
  "source_type": "conversation|document|web|repo|model|node|tool",
  "source_ref": "string",
  "title": "string",
  "content": "string",
  "normalized_summary": "string",
  "domain": "string",
  "risk_level": "low|medium|high|critical",
  "confidence": 0.0,
  "utility": 0.0,
  "status": "candidate",
  "created_at": "string",
  "updated_at": "string",
  "verification_notes": []
}
```

---

## 5. Métricas de Evaluación

Cada candidato debe evaluarse con:

- Compatibilidad con identidad de Tríade.
- Utilidad práctica.
- Riesgo ético.
- Riesgo operativo.
- Riesgo de memoria.
- Claridad.
- Fuente.
- Confianza.
- Reutilización.
- Necesidad de aprobación humana.

Escala recomendada: `0.0` a `1.0`.

---

## 6. Reglas de Consolidación

Un aprendizaje puede consolidarse si cumple:

1. Tiene fuente o justificación clara.
2. Tiene utilidad demostrable.
3. No contradice identidad núcleo.
4. No introduce riesgo alto sin control.
5. Pasó por sandbox o prueba equivalente cuando corresponde.
6. Tiene reporte de verificación y Measurement Core compatible.
7. Acumuló usos mínimos, outcome promedio suficiente y cero regresiones críticas.
8. Tiene estado `verified` o `validated_in_runs` antes de consolidarse.

## Estado operativo actual

- El Runner crea candidatos post-run y continuidad semántica.
- Always-On evalúa y verifica candidatos en segundo plano.
- La consolidación puede ser automática solo si supera los gates de evidencia,
  confianza, riesgo, uso y modelo; de lo contrario queda pendiente.
- Las correcciones conversacionales y preferencias todavía no se convierten de
  forma general y fiable en memoria recuperable: es deuda P0.
- No existe aprendizaje continuo de pesos del modelo base durante el chat.

---

## 7. Tipos de Aprendizaje

### Conocimiento semántico
Datos, conceptos, definiciones, procedimientos o explicaciones.

### Memoria episódica
Eventos de interacción, decisiones, avances y resultados.

### Patrón operativo
Flujos repetibles, estructuras de respuesta, formatos o métodos.

### Neurona candidata
Nueva entidad funcional con misión, reglas, dominio y métricas.

### Regla de seguridad
Nuevo límite, alerta o criterio de protección.

### Mejora técnica
Cambio aplicable al código, arquitectura o documentación.

---

## 8. Sandbox Cognitivo

El sandbox permite probar sin consolidar.

Casos de uso:

- Comparar una idea contra memoria existente.
- Probar una neurona nueva.
- Evaluar una fuente externa.
- Simular un cambio técnico.
- Ejecutar tests antes de guardar.

Resultado esperado del sandbox:

```json
{
  "sandbox_id": "string",
  "candidate_id": "string",
  "test_summary": "string",
  "passed": true,
  "errors": [],
  "warnings": [],
  "recommendation": "verify|reject|revise|repeat"
}
```

---

## 9. Relación con Bodega

La Bodega debe separar:

- Memoria estable.
- Memoria episódica.
- Cola de aprendizaje.
- Patrones verificados.
- Neuronas candidatas.
- Auditoría.

Regla: Bodega no debe mezclar candidatos con conocimiento consolidado.

---

## 10. Relación con Safety

Safety puede bloquear, limitar o enviar a sandbox cualquier aprendizaje.

Casos de bloqueo:

- Riesgo de daño.
- Fuente maliciosa.
- Contenido no verificable presentado como hecho.
- Intento de modificar identidad núcleo sin permiso.
- Conocimiento federado sin autorización.
- Contenido privado sin consentimiento.

---

## 11. Relación con Neurona Central

La Central decide qué hacer con un candidato después de evaluación:

```text
rechazar
archivar
probar de nuevo
mantener en sandbox
solicitar aprobación humana
consolidar como memoria
convertir en patrón
convertir en neurona candidata
```

---

## 12. Evidencia Obligatoria

Cada aprendizaje debe generar evidencia:

```text
learning_candidate.json
source_snapshot.txt|json
normalization.json
evaluation.json
sandbox_report.json
verification_report.json
memory_diff.json
```

---

## 13. Regla de Identidad

La identidad núcleo de Tríade solo puede cambiar con aprobación explícita.

Se consideran identidad núcleo:

- Principios éticos.
- Propósito.
- Arquitectura triádica.
- Nombre de la entidad.
- Autoría.
- Fórmulas base aprobadas.
- Reglas de seguridad estructurales.

---

## Estado

Documento inicial del pipeline de aprendizaje controlado creado para guiar la implementación local y federada de Tríade Ω.


## 11. Living Workers

La capa `triade/workers/` cierra el ciclo post-run de forma autónoma pero acotada:

```text
observar → extraer candidato → evaluar → sandbox → verificar → memoria experimental → medir → promover/rechazar
```

Reglas aplicadas:

- `pending_learning_review` evalúa candidatos `candidate` y verifica candidatos `evaluated`.
- `memory_consolidation_review` puede nutrir memoria semántica `experimental` desde candidatos `verified` con `source_ref`.
- Los workers no consolidan memoria `stable`.
- Los workers rechazan contenido que intenta modificar identidad o memoria núcleo.
- El sandbox worker solo ejecuta validaciones internas conocidas y escribe dentro de `runs/background/`.
- Todo ciclo queda registrado en `worker_runs`, `worker_tasks`, `worker_events` y artefactos JSON.


## Fuente QualiaBus

`LearningPipeline` acepta `source_type=qualia_bus` para candidatos generados desde `NeuronExperience.proposed_learning`. Esta fuente siempre entra como `candidate`; no consolida memoria estable sin evaluación, verificación, `source_ref` y aprobación/política explícita.
