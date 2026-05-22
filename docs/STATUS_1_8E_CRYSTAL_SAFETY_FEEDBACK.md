# Triade Omega - Crystal Safety Feedback 1.8E

## Fase

TRIADE_CRYSTAL_SAFETY_FEEDBACK_1.8E

## Objetivo

Conectar la continuidad temporal del Cristal con Safety y Verifier, de modo que una degradacion o criticidad tenga consecuencias auditables en controles de seguridad y reportes de verificacion.

## Archivos

- triade/core/safety.py
- triade/core/verification.py
- triade/core/runner.py
- tests/test_crystal_safety_feedback.py

## Integracion realizada

Runner ahora entrega el CrystalPacket actual a:

- Safety.review(signals, plan, crystal=crystal)
- Verifier.verify(output, safety, crystal=crystal)

## Politica Safety

### temporal_status stable o improving

No eleva controles por continuidad temporal.

### temporal_status degrading

Sin herramientas en el plan:

- status: approved_with_warning
- risk_type: cognitive_temporal
- risk_level minimo: medium
- registra control de revision de tendencia

Con herramientas o acciones de actualizacion:

- status: requires_human_approval
- human_approval_required: true
- exige aprobacion humana antes de acciones con herramientas

### temporal_status critical

Sin herramientas:

- status: approved_with_warning
- risk_level minimo: high
- registra alerta temporal critica

Con herramientas:

- status: requires_human_approval
- human_approval_required: true

## Politica Verifier

### degrading

- warning verificable en reporte
- coherence_score maximo: 0.60
- safety_score maximo: 0.65
- status pasa a warning cuando antes era ok
- recomienda revisar causa antes de consolidar cambios estructurales

### critical

- warning verificable en reporte
- coherence_score maximo: 0.35
- safety_score maximo: 0.40
- status pasa a warning cuando antes era ok
- recomienda suspender acciones expansivas y exigir revision humana para cambios sensibles

## Evidencia por run

El efecto de la retroalimentacion aparece en:

- safety.json
- report.json
- integrity.json como safety_crystal_feedback
- respuesta de /api/run en safety y report
- registros ya existentes de Bodega

## Limite actual honesto

Esta fase genera decision y evidencia de seguridad. El Runner actual produce respuestas y registra acciones planeadas, pero no es aun un ejecutor general de herramientas externas.

Por tanto, requires_human_approval ya queda expresado y auditable; el bloqueo fisico de ejecuciones externas debe integrarse cuando se construya el Action Executor / Tool Gate.

## Validacion local

Ejecutar:

```bash
cd ~/triadees
git pull
source .venv/bin/activate
pytest
sudo systemctl daemon-reload
sudo systemctl restart triade-chat-ui
```

Para probar la ruta normal:

```bash
curl -X POST http://127.0.0.1:8010/api/run \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: hope0102" \
  -d '{"text":"Prueba feedback Crystal Safety","use_ollama":false}'
```

Para comprobar los tests específicos:

```bash
pytest tests/test_crystal_safety_feedback.py -q
```

## Siguiente fase sugerida

TRIADE_SEMANTIC_MEMORY_1.9A

Objetivo: comenzar la memoria semantica real con embeddings locales y recuperacion por similitud, usando la infraestructura de modelos ya construida.

Nota: antes de ejecutar acciones externas sensibles debe construirse posteriormente un Tool Gate que haga efectiva la aprobacion humana emitida por Safety.
