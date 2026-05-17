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

Tríade puede aprender desde:

- Conversaciones autorizadas.
- Documentos cargados.
- Repositorios.
- Web pública.
- Modelos locales.
- Nodos federados autorizados.
- Resultados de herramientas.
- Experimentos del sandbox.

Cada fuente debe registrarse con fecha, tipo, confianza y estado.

---

## 3. Estados del Aprendizaje

```text
candidate
extracted
normalized
evaluated
sandboxed
tested
verified
consolidated
rejected
archived
```

### candidate
Idea, patrón o dato detectado pero aún no procesado.

### extracted
Contenido separado de su fuente original.

### normalized
Contenido convertido a estructura clara.

### evaluated
Contenido evaluado por utilidad, riesgo y coherencia.

### sandboxed
Contenido probado sin afectar memoria estable.

### tested
Contenido sometido a pruebas funcionales o comparativas.

### verified
Contenido aprobado por verificación.

### consolidated
Contenido guardado como memoria estable o patrón reutilizable.

### rejected
Contenido descartado por baja calidad, riesgo o falsedad.

### archived
Contenido conservado como histórico, no activo.

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
5. Pasó por sandbox o prueba equivalente.
6. Tiene reporte de verificación.
7. Tiene estado `verified` antes de `consolidated`.

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
