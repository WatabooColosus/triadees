# OpenCode como cuerpo efector de Tríade Ω

## Estado actual · 2026-07-24

Este documento define el estado presente de la relación entre Tríade Ω y OpenCode.

## Dictamen

OpenCode no forma parte todavía del runtime cognitivo interno de Tríade. Actualmente es una herramienta externa de ingeniería usada por el creador para inspeccionar, modificar, probar y documentar el repositorio.

La integración objetivo consiste en convertirlo progresivamente en un cuerpo efector gobernado, sin confundir sus capacidades con capacidades propias ya demostradas por Tríade.

## Lo que ya existe en Tríade

Según `docs/STATUS_CURRENT.md`, el repositorio ya contiene bases relevantes para esta evolución:

- `TriadeRunner` como ciclo cognitivo integrado;
- Central, Hipotálamo, Bodega, Cristal y Safety;
- LearningPipeline gobernado;
- Living Workers y Always-On Runtime;
- planificación persistente;
- sandbox aislado;
- Safe File Ops;
- clasificación de zonas del sistema;
- presupuesto de autonomía;
- snapshots de integridad;
- papelera reversible;
- planificación de acciones delegadas;
- aprobación humana para acciones críticas;
- observabilidad, Memory Trace y evidencia por run;
- orquestación y evaluación de modelos locales.

Estas capacidades son la base para conectar un ejecutor de ingeniería, pero no demuestran todavía que Tríade pueda gobernar OpenCode de extremo a extremo.

## Papel actual de cada parte

### Dirección humana

- define la visión;
- aprueba las fases;
- resuelve contradicciones fundacionales;
- autoriza cambios sensibles;
- decide cuándo integrar y fusionar.

### Tríade Ω

- conserva la arquitectura cognitiva;
- produce contexto, memoria, prioridades, políticas y decisiones;
- debe gobernar progresivamente las acciones técnicas;
- registra evidencia y aprendizaje verificable.

### OpenCode

- inspecciona archivos;
- propone planes técnicos;
- modifica código;
- ejecuta pruebas;
- revisa diffs;
- prepara commits;
- devuelve evidencia.

### Modelos locales

- suministran razonamiento y generación auxiliar;
- son reemplazables;
- no constituyen la identidad de Tríade;
- deben declararse degradados cuando no estén disponibles.

## Ciclo objetivo

```text
Necesidad detectada
    ↓
Central analiza
    ↓
Hipotálamo prioriza riesgo y recursos
    ↓
Bodega aporta contexto y memoria
    ↓
Cristal y Constitución verifican coherencia y límites
    ↓
Integrador autoriza una tarea acotada
    ↓
OpenCode ejecuta en rama y sandbox gobernados
    ↓
Tests, integridad y observabilidad verifican
    ↓
Bodega registra resultado y evidencia
    ↓
Tríade evalúa si hubo mejora real
```

## Brecha actual

Aún falta demostrar un adaptador ejecutable que conecte una decisión de Tríade con una sesión de OpenCode y cierre el ciclo con:

- tarea estructurada;
- contexto persistente;
- límites de archivos y comandos;
- rama aislada;
- dry-run;
- ejecución;
- captura de salida;
- pruebas;
- diff;
- aprobación humana;
- rollback;
- registro en memoria;
- evaluación posterior.

Hasta que ese ciclo exista y sea probado, OpenCode seguirá siendo una herramienta externa dirigida por el humano.

## Principio de honestidad

No se debe afirmar que:

- Tríade modifica autónomamente su propio código;
- OpenCode es ya un órgano interno;
- existe autoevolución completa;
- existe aprendizaje de ingeniería cerrado;
- existe continuidad autónoma de desarrollo.

Se puede afirmar únicamente que el repositorio posee componentes parciales y avanzados para construir esa integración.

## Regla operativa vigente

El desarrollo continuará por fases:

1. documentación y contratos;
2. adaptador mínimo;
3. dry-run;
4. ejecución controlada;
5. verificación;
6. memoria del resultado;
7. aprobación humana;
8. autonomía progresiva solo con evidencia.
