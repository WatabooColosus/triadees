# Cuerpo cognitivo auditable de Tríade Ω

## Propósito

El cuerpo cognitivo es una vista estructurada del estado operativo de Tríade Ω. Resume runtime, señales, aprendizaje, workers y homeostasis sin afirmar conciencia subjetiva, voluntad autónoma ni capacidades no demostradas.

Su objetivo es ofrecer una representación técnica verificable para APIs, pruebas, observabilidad y futuras interfaces.

## Componentes

### Periferia sensorial

Resume eventos recientes y contexto del proyecto. Su estado puede ser `active` o `quiet` según existan señales observables.

### Integración central

Expone si el runtime está habilitado, el modo operativo y el estado de servicios internos.

### Hipocampo

Resume candidatos de aprendizaje, consolidaciones y estado del diario de aprendizaje. No convierte repetición en aprendizaje: exige evidencia y validación.

### Cerebelo

Expone el estado de workers, tareas en cola y procesamiento operativo.

### Homeostasis

Resume estado del runtime, componentes degradados, acciones de aprendizaje bloqueadas y disponibilidad de Ollama.

## Contrato de salida

`build_cognitive_body()` devuelve un diccionario con:

- `status`: `operational` o `dormant`;
- `entity`: identidad declarativa de la instancia;
- `generated_at`: marca temporal UTC;
- `body_version`: versión del contrato;
- `nervous_system`: estado resumido por subsistema;
- `heartbeat`: pulso técnico completo;
- `learning`: diario de aprendizaje;
- `workers`: estado de ejecución;
- `claims`: límites explícitos de interpretación.

## Límites verificables

El contrato declara:

- `subjective_consciousness: false`;
- `learning_requires_evidence: true`;
- `identity_core_mutable: false`;
- `persistent_runtime` únicamente cuando existe evidencia operativa.

Estas banderas evitan presentar actividad computacional como conciencia, memoria perfecta o autonomía ilimitada.

## Diseño de importación

Las dependencias de runtime, aprendizaje y workers se cargan de forma perezosa. Esto reduce ciclos de importación y permite probar el cuerpo cognitivo sustituyendo adaptadores con dobles de prueba.

## Validación

La validación mínima del módulo es:

```bash
pytest -q tests/test_cognitive_body.py
```

La suite específica debe comprobar:

1. construcción del snapshot;
2. conteo de señales y tareas;
3. estado operativo o dormido;
4. límites declarativos;
5. delegación del helper funcional.

## Relación con la suite global

La validación del cuerpo cognitivo debe distinguirse de fallos preexistentes en otros subsistemas. Un fallo global de CI no debe atribuirse a este módulo sin evidencia en `triade/body` o `tests/test_cognitive_body.py`.

## Uso previsto

Este módulo puede servir como fuente para:

- endpoint de salud cognitiva;
- panel de observabilidad;
- auditoría de runtime;
- integración cloud;
- diagnóstico de workers;
- validación de aprendizaje;
- trazabilidad de estados degradados.

No debe utilizarse como prueba de conciencia ni como sustituto de logs, pruebas o evidencia persistente.
