# Triade Self Improvement Path

Reflexion interna generada desde datos locales. No modifica identidad, no consolida aprendizaje y no cambia codigo automaticamente.

## Estado

- Modo: proposal_only
- Sabe que ocurrio: True
- Sabe uso de modelos: True

## Observaciones

- Runs analizados: 50 con cobertura de trazabilidad completa si cada etapa supera 95%.
- Uso de modelos: 82.0% fallback/failed y 18.0% Ollama ok.
- Cristal promedio: Q=0.61 estabilidad=0.866.
- Memoria semantica local sin documentos/embeddings analizados; la continuidad depende sobre todo de memoria episodica.
- Fallback alto: el nucleo necesita diagnostico fino de modelos y causas de caida.
- Hay advertencias recurrentes que pueden alimentar una neurona verificadora.
- Hay degradaciones o deltas negativos de Cristal que requieren seguimiento temporal.

## Neuronas Propuestas

### neurona_diagnostico_modelos

- Dominio: model-router
- Mision: Observar eventos de modelo, separar causas de fallback y recomendar rutas Central/Hipotalamo verificables.
- Estado: candidate

### neurona_memoria_semantica

- Dominio: memory
- Mision: Detectar conversaciones o documentos que merecen pasar a candidatos de memoria semantica sin consolidarlos automaticamente.
- Estado: candidate

### neurona_verificadora_recurrente

- Dominio: verification
- Mision: Agrupar advertencias recurrentes de verification_reports y proponer pruebas o controles para reducirlas.
- Estado: candidate

### neurona_continuidad_conversacional

- Dominio: conversation
- Mision: Cuidar continuidad conversacional y preferencias recordables sin convertir inferencias privadas en identidad estable.
- Estado: candidate

### neurona_guardiana_cristal

- Dominio: crystal
- Mision: Monitorear degradaciones de Q_crystal y estabilidad para sugerir ajustes de prudencia, memoria y verificacion.
- Estado: candidate

### neurona_arquitecta_core

- Dominio: core-architecture
- Mision: Mantener el backlog del nucleo, dividir modulos grandes y preparar cambios incrementales compatibles con CLI, API y UI.
- Estado: candidate

## Ciclo Real

- observe: Leer runs, model_events, crystal_states, verification_reports y memoria sin modificar DB estable. | criterio: Salida JSON contiene politica read-only y trazabilidad por etapa.
- analyze: Convertir 50 runs en metricas de fallback, Cristal, fuentes e intenciones. | criterio: Métricas reproducibles por analyze-conversations y reflect-core.
- propose: Proponer 6 neuronas candidatas segun necesidades observadas. | criterio: Cada neurona tiene mision, dominio, reglas, assessment y estado candidate.
- test: Definir prueba esperada antes de activar o usar una neurona en el ciclo cognitivo. | criterio: La neurona no pasa a experimental/stable sin test o evidencia.
- verify: Verificar que la mejora no reduce trazabilidad, seguridad ni compatibilidad CLI/API/UI. | criterio: pytest, doctor y reporte de reflexion pasan.
- approve: Pedir aprobacion humana para consolidar learning, activar neuronas o modificar codigo. | criterio: No hay consolidacion automatica ni cambios de identidad.
- integrate: Integrar cambios pequenos y reversibles al nucleo. | criterio: Nuevo estado queda documentado y auditable.

## Decisiones Humanas Requeridas

- Decidir si registrar/activar estas neuronas candidatas: neurona_diagnostico_modelos, neurona_memoria_semantica, neurona_verificadora_recurrente, neurona_continuidad_conversacional, neurona_guardiana_cristal, neurona_arquitecta_core.
- Aprobar explicitamente cualquier consolidacion en memoria semantica estable.
- Aprobar cambios de codigo que permitan auto-mejora ejecutiva.
- Definir umbral minimo para promover candidate -> experimental -> stable.
