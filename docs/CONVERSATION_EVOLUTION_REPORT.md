# Conversation Evolution Report

Reporte generado desde SQLite local en modo solo lectura. No consolida aprendizaje ni modifica identidad.

## Resumen

- Runs analizados: 50
- Episodios relacionados: 50
- Q_crystal promedio: 0.608
- Estabilidad promedio: 0.866
- Fallback promedio vs Ollama: 84.0% fallback / 16.0% Ollama ok

## Modelos Usados

- hypothalamus:rules:rules-fallback:ok=0: 41
- central:template:template-fallback:ok=0: 41
- hypothalamus:ollama:qwen2.5:3b-instruct:ok=1: 8
- central:ollama:qwen2.5:3b-instruct:ok=1: 8
- hypothalamus:ollama:qwen3:1.7b:ok=0: 1
- central:ollama:qwen3:4b:ok=0: 1

## Fuentes Principales

- test: 13
- api-test-context: 12
- single-port-ui: 12
- single-port-react-ui: 10
- console: 3

## Intenciones Mas Comunes

- conversation: 44
- build_or_update: 4
- analyze: 2

## Temas Recurrentes

- prueba: 40
- auto: 25
- selección: 25
- ollama: 16
- contextual: 12
- single: 12
- port: 12
- nombre: 3
- llames: 2
- camila: 2
- final: 2
- auditoria: 2

## Advertencias Recurrentes

- El plan puede implicar actualización de archivos o repositorio.: 4
- Ollama fue solicitado pero no generó respuesta central; se usó fallback por plantilla.: 1

## Evolucion Del Cristal

- Delta Q promedio: 0.002
- Delta estabilidad promedio: -0.001
- Mejoras detectadas: 3
- Degradaciones detectadas: 3

## Recomendaciones Para Mejorar El Nucleo

- Investigar fallback recurrente: registrar causa exacta y separar fallback de modelo ausente vs salida invalida.
- Mantener aprendizaje conversacional como candidatos revisables, no como consolidacion automatica.
- Separar progresivamente orquestacion del runner en etapas testeables: senales, memoria, cristal, plan, modelos y verificacion.

## Aprendizajes Candidatos

- Patron recurrente: prueba (40 apariciones)
- Patron recurrente: auto (25 apariciones)
- Patron recurrente: selección (25 apariciones)
- Patron recurrente: ollama (16 apariciones)
- Patron recurrente: contextual (12 apariciones)
- Patron recurrente: single (12 apariciones)
- Patron recurrente: port (12 apariciones)
- Patron recurrente: nombre (3 apariciones)
- Advertencia recurrente candidata: El plan puede implicar actualización de archivos o repositorio.
- Advertencia recurrente candidata: Ollama fue solicitado pero no generó respuesta central; se usó fallback por plantilla.

## Que NO Debe Consolidarse Aun

- Entradas textuales completas de usuarios sin aprobacion humana.
- Inferencias de identidad, preferencias o datos privados no verificadas.
- Patrones basados en fallos de modelo o fallback sin revisar causa tecnica.
- Temas con una sola aparicion o sin evidencia en verification_reports.
