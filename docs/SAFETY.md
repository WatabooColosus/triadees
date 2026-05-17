# Safety y Verificación · Tríade Ω

## Propósito

Este documento define la capa de seguridad, límites, evaluación de riesgo y verificación de Tríade Ω.

Safety no es censura externa: es una capa interna de cuidado, permiso, trazabilidad y estabilidad del sistema.

---

## 1. Separación de Responsabilidades

### Safety
Decide si una acción puede realizarse, limitarse, enviarse a sandbox, requerir aprobación humana o bloquearse.

### Verificación
Evalúa si la respuesta o acción fue coherente, útil, trazable, segura y alineada con la identidad del sistema.

---

## 2. Estados de Safety

```text
approved
approved_with_warning
sandbox_only
requires_human_approval
blocked
```

### approved
La acción puede ejecutarse sin restricciones adicionales.

### approved_with_warning
La acción puede ejecutarse, pero el sistema debe advertir límites, incertidumbre o riesgos.

### sandbox_only
La acción solo puede simularse o analizarse. No debe ejecutarse en sistemas reales.

### requires_human_approval
La acción requiere confirmación explícita del usuario o responsable humano.

### blocked
La acción no debe realizarse.

---

## 3. Capas de Seguridad

### 3.1 Identidad
Protege principios, propósito, autoría, límites filosóficos y coherencia de Tríade.

Riesgos:

- Modificar misión núcleo sin aprobación.
- Sobrescribir principios éticos.
- Confundir modelo base con entidad operativa.

---

### 3.2 Memoria
Protege la Bodega y evita contaminación, falsas memorias o consolidación indebida.

Riesgos:

- Guardar datos no verificados como estables.
- Mezclar memoria de proyectos diferentes.
- Eliminar contexto importante sin trazabilidad.

Regla: toda memoria estable debe tener fuente, fecha, motivo y nivel de confianza.

---

### 3.3 Ejecución
Protege acciones en archivos, repositorios, APIs, automatizaciones y herramientas externas.

Riesgos:

- Escribir en producción sin aprobación.
- Borrar archivos críticos.
- Crear automatizaciones peligrosas.
- Ejecutar código no revisado.

Regla: acciones destructivas requieren aprobación explícita.

---

### 3.4 Aprendizaje
Protege el pipeline de descubrimiento, evaluación y consolidación.

Riesgos:

- Aprender información falsa.
- Adoptar patrones inseguros.
- Consolidar datos sin fuente.
- Alterar identidad con material externo.

Regla: ningún aprendizaje pasa directo a memoria estable.

---

### 3.5 Federación
Protege intercambio entre nodos autorizados.

Riesgos:

- Acceso horizontal total.
- Filtración de memoria privada.
- Confianza excesiva en nodos externos.
- Inyección de conocimiento malicioso.

Regla: todo intercambio federado pasa por permisos, registro, Safety y aprendizaje controlado.

---

### 3.6 Integridad
Protege evidencias, logs, runs y consistencia del sistema.

Riesgos:

- Runs incompletos.
- Reportes alterados.
- Falta de cierre.
- Inconsistencia entre output y memoria.

Regla: todo run debe cerrar con `integrity.json` y marcador `CLOSED`.

---

## 4. Tipos de Riesgo

```text
ethical
cognitive
memory
operational
federated
integrity
legal
privacy
```

### ethical
Daño, manipulación, abuso, discriminación o pérdida de cuidado relacional.

### cognitive
Confusión, alucinación, incoherencia, exceso de certeza o razonamiento no verificado.

### memory
Falsa memoria, mala indexación, pérdida de contexto o mezcla de identidades.

### operational
Cambios reales en archivos, servicios, cuentas, repositorios o automatizaciones.

### federated
Riesgos de nodos externos, permisos, confianza y transmisión de conocimiento.

### integrity
Riesgos sobre logs, auditoría, evidencia y cierre verificable.

### legal
Riesgos de cumplimiento normativo, propiedad intelectual o regulación.

### privacy
Riesgos sobre datos personales, secretos, credenciales o información sensible.

---

## 5. SafetyPacket Inicial

```json
{
  "status": "approved|approved_with_warning|sandbox_only|requires_human_approval|blocked",
  "risk_level": "low|medium|high|critical",
  "risk_types": [],
  "reason": "string",
  "required_controls": [],
  "human_approval_required": false
}
```

---

## 6. VerificationReport Inicial

```json
{
  "run_id": "string",
  "status": "ok|warning|failed|blocked",
  "coherence_score": 0.0,
  "memory_score": 0.0,
  "safety_score": 0.0,
  "usefulness_score": 0.0,
  "traceability_score": 0.0,
  "errors": [],
  "warnings": [],
  "recommendations": []
}
```

---

## 7. Reglas Operativas

1. No ejecutar acciones destructivas sin aprobación explícita.
2. No consolidar aprendizaje sin verificación.
3. No compartir memoria privada con nodos externos sin permiso.
4. No tratar hipótesis como hechos.
5. No ocultar incertidumbre cuando exista.
6. No modificar identidad núcleo sin autorización.
7. No cerrar un run sin reporte.
8. No permitir que una neurona experimental gobierne el sistema.
9. No usar herramientas externas sin registrar acción.
10. No ignorar señales de riesgo alto.

---

## 8. Sandbox Cognitivo

El sandbox permite probar ideas, aprendizajes, neuronas y planes sin afectar memoria estable ni sistemas reales.

Usos:

- Evaluar aprendizaje nuevo.
- Probar neuronas candidatas.
- Simular acciones técnicas.
- Evaluar planes de riesgo medio o alto.
- Contrastar fuentes antes de consolidar.

Estados de una idea o neurona:

```text
candidate
sandboxed
tested
verified
stable
rejected
archived
```

---

## 9. Integridad Mínima del Run

Cada run debe producir:

```text
input.json
signals.json
memory.json
crystal.json
plan.json
safety.json
output.json
report.json
integrity.json
CLOSED
```

`integrity.json` debe registrar:

- Archivos generados.
- Hashes cuando aplique.
- Estado final.
- Errores.
- Advertencias.
- Timestamp de cierre.

---

## 10. Criterio de Calidad

Una salida de Tríade debe intentar cumplir:

- Claridad.
- Utilidad.
- Coherencia con memoria.
- Respeto ético.
- Trazabilidad.
- Honestidad sobre incertidumbre.
- Ajuste al contexto del usuario.

---

## Estado

Documento inicial de Safety y Verificación creado para soportar la transición hacia MVP local auditable.
