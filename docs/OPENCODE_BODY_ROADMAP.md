# Hoja de ruta: OpenCode como cuerpo efector gobernado

## Objetivo

Construir una integración real y verificable donde Tríade Ω pueda preparar, autorizar, supervisar y evaluar tareas de ingeniería ejecutadas mediante OpenCode, sin entregar acceso libre al repositorio ni confundir generación de código con autoevolución cognitiva.

## Fase 0 — Fundación documental

Entregables:

- `AGENTS.md` permanente;
- estado actual de la integración;
- inventario de PDF, DOC y DOCX fundacionales;
- matriz entre conceptos originales y código vigente;
- contrato preliminar del cuerpo efector.

Criterio de salida:

- fuentes de verdad identificadas;
- contradicciones documentadas;
- ninguna modificación del runtime.

## Fase 1 — Contrato de tarea de ingeniería

Definir un esquema estructurado, por ejemplo `EngineeringTask`, con:

- `task_id`;
- objetivo;
- justificación;
- fase;
- archivos permitidos;
- archivos prohibidos;
- comandos permitidos;
- presupuesto de autonomía;
- pruebas requeridas;
- riesgo;
- necesidad de aprobación humana;
- estrategia de rollback;
- referencias de memoria y documentación.

Criterio de salida:

- validación Pydantic;
- serialización reproducible;
- pruebas unitarias;
- ninguna ejecución externa.

## Fase 2 — Constructor de contexto persistente

Crear un `EngineeringContextBuilder` que reúna únicamente contexto autorizado:

- `AGENTS.md`;
- documentos fundacionales relevantes;
- estado actual;
- fase activa;
- decisiones previas;
- archivos objetivo;
- pruebas relacionadas;
- límites de seguridad.

Debe imponer límites de tamaño, relevancia y procedencia.

Criterio de salida:

- contexto determinista;
- fuentes trazables;
- pruebas contra pérdida, duplicación e inyección de instrucciones no autorizadas.

## Fase 3 — Adaptador OpenCode en dry-run

Crear una interfaz reemplazable:

```text
EngineeringExecutor
└── OpenCodeExecutor
```

El primer adaptador solo debe:

- construir el comando o sesión;
- mostrar qué ejecutaría;
- registrar argumentos;
- negar shell libre;
- no modificar archivos.

Criterio de salida:

- dry-run completo;
- integración con System Zones, Autonomy Budget y Delegated Action Planner;
- evidencia en logs y observabilidad.

## Fase 4 — Ejecución aislada de solo lectura

Permitir tareas como:

- búsqueda;
- inspección;
- explicación de flujo;
- propuesta de plan;
- selección de pruebas;
- análisis de diff existente.

Sin escrituras.

Criterio de salida:

- timeout;
- captura de stdout/stderr;
- límites de recursos;
- registro por `run_ref`;
- pruebas de denegación.

## Fase 5 — Escritura controlada en rama

Permitir cambios únicamente cuando:

- exista rama de trabajo;
- los archivos estén autorizados;
- el presupuesto lo permita;
- haya snapshot previo;
- se use sandbox o workspace aislado;
- no se toque `main`, `.git`, `.env` ni `identity_core`;
- el cambio pueda revertirse.

Criterio de salida:

- modificación mínima demostrada;
- diff capturado;
- integridad verificada;
- rollback probado.

## Fase 6 — Pruebas y evaluación técnica

Después de cada ejecución:

- ejecutar pruebas focalizadas;
- ejecutar verificaciones generales aprobadas;
- ejecutar `git diff --check`;
- clasificar fallos;
- impedir promoción con rojo;
- producir un informe estructurado.

Criterio de salida:

- evidencia reproducible;
- ningún resultado inventado;
- salida diferenciada entre ejecutado, omitido y no disponible.

## Fase 7 — Memoria de ingeniería

Registrar en Bodega:

- objetivo;
- contexto usado;
- cambios;
- pruebas;
- errores;
- rollback;
- decisión humana;
- resultado posterior;
- aprendizaje candidato.

No consolidar automáticamente como verdad estable.

Criterio de salida:

- recuperación tras reinicio;
- trazabilidad hacia commit, diff y pruebas;
- contradicción y revisión soportadas.

## Fase 8 — Cierre de aprendizaje

Demostrar:

```text
problema inicial
→ intervención autorizada
→ evidencia técnica
→ resultado medido
→ memoria candidata
→ reutilización posterior
→ mejora verificable
```

Criterio de salida:

- una decisión futura cambia correctamente gracias a evidencia anterior;
- la mejora puede auditarse y revertirse.

## Fase 9 — Autonomía progresiva

Solo después de las fases anteriores:

- tareas de mantenimiento de bajo riesgo;
- límites por cantidad de archivos y bytes;
- ventanas temporales;
- aprobación humana según riesgo;
- watchdog;
- cancelación;
- rollback automático;
- reportes en Cabina Viva.

No se autoriza autoedición irrestricta.

## Primer siguiente paso recomendado

No programar aún el adaptador completo.

La siguiente fase debe ser únicamente:

> Auditar los componentes existentes de autonomía delegada, sandbox, planificación, modelos, workers, memoria e integridad y producir el contrato mínimo `EngineeringTask` sin ejecutar OpenCode.

Al terminar, detenerse para revisión humana.
