# Triaje de deuda — 2026-08-03

SHA base: `741f2b5c8b90e5c1a36b868968f0767bd4c9373a`
Rama: `fix/debt-triage-circuit-closure`
Artefacto: `artifacts/debt/debt-triage-20260803.json`

## Por qué el contador subió a 100

No apareció deuda nueva: apareció deuda que antes nadie medía. El detector de
alias entró en el informe único y añadió lectores huérfanos, alias léxicos y
estados muertos, que llevaban ahí sin contarse.

## Reparto

| Clasificación | Inicial | Tras modelar formas de escritura | Tras corregir la regla de lector |
|---|---|---|---|
| `incomplete_subsystem` | 72 | 71 | **72** |
| `legacy_expected` | 18 | 17 | **18** |
| `detector_false_positive` | 5 | 5 | **5** |
| `confirmed_break` | 5 | 1 | **0** |
| **Clasificados** | 100 | 94 | **95** |

El descenso de `confirmed_break` a cero **no es un descuento**. Cada baja tiene
una causa demostrada y una prueba que impide reintroducirla.

## Los cinco cortes que no lo eran

Cuatro eran formas de escritura que el detector no modelaba:

| Estado | Escritura real | Prueba |
|---|---|---|
| `detected` | `DEFAULT 'detected'` en el CREATE TABLE | `test_un_default_de_columna_produce_el_estado` |
| `starting` | `_STATE["status"] = "starting"` | `test_una_asignacion_de_clave_produce_el_estado` |
| `runtime_recovered` | `state, error = "runtime_recovered", None` | `test_un_desempaquetado_de_tupla_produce_el_estado` |
| `no_evidence` | `{"status": "no_evidence"}` | `test_un_literal_de_diccionario_produce_el_estado` |

El quinto, `neuron_certifications`, era un error de mi propia regla de triaje.
Tenía 1 lector, 0 escritores y 0 filas, y la regla lo llamó corte confirmado.
Pero su lector —`triade/neuron_factory/certification.py`— no lo alcanza ningún
entrypoint arrancado: **nadie recibe nunca ese caso vacío**. La regla ahora
comprueba la alcanzabilidad del lector antes de acusar.

## Confianza graduada

De los 4 estados muertos restantes, sólo **uno** es acusación firme:
`unhealthy` en `worker_supervisor.py`, que además es uno de los dos módulos que
ningún entrypoint alcanza.

Los otros tres pasan a `suspected_dead_status` con `confidence="suspected"`:
existe una escritura `SET status = ?` en un fichero que también los compara, y
el valor enviado no es visible al análisis estático. No se descartan —pueden
seguir siendo cortes— pero el informe dice lo que la evidencia sostiene.

`suspected_dead_status` cuenta como categoría propia en el informe: rebajar la
confianza de un hallazgo no es motivo para esconderlo del contador.

## Decisión: `longitudinal_memories` → INACTIVO

Evidencia sobre `main @ 741f2b5`:

| Comprobación | Resultado |
|---|---|
| Migración `021_longitudinal_memory.sql` | existe, **nunca aplicada** |
| Tablas `longitudinal_*` en la base viva | **ninguna** |
| `triade/memory/longitudinal.py` alcanzable | **no** |
| Consumidores productivos en `triade/` o `apps/` | **ninguno** |
| Único consumidor | `scripts/run_phase_05_memory_longitudinal.py` (script de fase) |
| Cobertura de pruebas | sí, `tests/memory_longitudinal/` |

**Opción B, no por conveniencia.** Cerrar el circuito exigiría inventar un
consumidor productivo que nadie ha pedido: eso es conectar un cascarón, y quien
leyera el resultado creería que hay memoria longitudinal en uso. Crear la tabla
para callar la alerta está prohibido por el mismo motivo.

Tampoco se borra: el código está cubierto por pruebas y no lo supera ningún
módulo vivo.

Queda declarado en el propio módulo (`SUBSYSTEM_STATUS = "inactive"`) con la
evidencia y las cinco condiciones que harían falta para activarlo: aplicar la
migración, un productor real, un consumidor productivo, alcanzabilidad desde un
entrypoint vivo y una prueba end-to-end.

## Suite completa

Ejecutada con el runtime parado, que es condición necesaria:

```
2.106 tests · 0 fallos · 0 errores · 0 saltados · EXIT=0 · 13 min 40 s
```

| Categoría | Cantidad |
|---|---|
| Fallo previo | 0 |
| Fallo introducido | 0 |
| Fallo corregido | 5 avisos de ruff propios |
| No ejecutable por entorno | 0 |

Contención medida, porque explica los intentos anteriores fallidos:

| Condición | Ritmo |
|---|---|
| Runtime encendido | ~3 tests/min |
| Runtime parado | ~154 tests/min |

## Línea base de lint

`ruff check .` da 665 avisos. **656 son `EXE002`** —bit de ejecución sin
shebang—, artefacto del montaje del Studio: git tiene los ficheros como
`100644`, así que CI no los ve. De los 9 reales, 5 los introduje yo y están
corregidos; 4 son previos y se dejan intactos para no mezclar señal.

## Riesgos y pendiente

- Los 72 `incomplete_subsystem` no están triados uno a uno: son capacidades sin
  terminar, no cortes en marcha, pero cada una merece una decisión propia.
- Circuitos P0 de aprendizaje, goals y workers: **sin verificación end-to-end**
  en esta fase.
- PRs #71, #68, #67, #65: sin revisar.
- Contratos de Neurona Reparadora: sin diseñar.
- `/api/runtime/heartbeat` tarda 19,3 s en aislado y supera los 60 s bajo carga.
  Preexistente, no medido antes.
