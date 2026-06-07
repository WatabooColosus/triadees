# Technical Debt Map · Tríade Ω

## P0 · Higiene Git
- No escribir directo a main.
- Usar siempre rama → PR → revisión → merge.
- Eliminar artefactos de prueba de main.

## P1 · Separar UI/API/Core
`apps/single_port_app.py` concentra UI, API y lógica. Debe dividirse en rutas, servicios, schemas y capa UI.

## P2 · Reducir responsabilidades de Runner
`triade/core/runner.py` coordina modelos, memoria, cristal, safety, aprendizaje, neuronas, artefactos e integridad. Debe separarse en servicios.

## P3 · Fortalecer contratos
`triade/core/contracts.py` usa dataclasses como MVP. Definir ruta a validación fuerte y pruebas de serialización.

## P4 · Safety como compuerta real
Los estados de Safety deben bloquear o limitar acciones sensibles, no solo documentarlas.

## P5 · Federación verificable
Implementar registro de nodos, autenticación, permisos, trazabilidad y pruebas con nodos simulados.

## P6 · Tests mínimos
Agregar pruebas para run completo, memoria, cristal, safety, output gate, API/UI y federación simulada.

## P7 · UI futura
Antes de rediseñar la UI, estabilizar endpoints y separar componentes.
