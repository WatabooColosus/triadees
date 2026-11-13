# Contratos de activación: por qué algo está vacío, dicho de forma comprobable

Fecha: 2026-08-08 · bloque 5 del [plan de deuda](DEBT_TRIAGE_PLAN.md).

Este repositorio ya sabía qué le faltaba. Estaba escrito, y sin resolver, desde
la clasificación de las tablas de automejora:

> La regla general que sí cerraría estos ocho —y cualquier otro caso
> equivalente— es declarar la condición que produce filas y comprobarla:
> **una tabla vacía cuyo escritor es alcanzable y cuya condición de escritura es
> un gate humano documentado no es deuda mientras el gate no se haya ejercido
> nunca.** Eso exige que la condición esté declarada en algún sitio que el
> detector pueda leer, no adivinada. No existe hoy, y construirlo es una decisión
> de diseño —dónde vive esa declaración— que no se debe tomar de pasada.
>
> — [`IMPROVEMENT_TABLES_CLASSIFICATION.md`](IMPROVEMENT_TABLES_CLASSIFICATION.md)

Aquí está tomada esa decisión.

## El problema, dicho con precisión

Hasta ahora toda ausencia de actividad pesaba igual. Eso hace daño en las dos
direcciones:

- una tabla que espera una firma humana que nadie ha dado **sube el contador como
  si estuviera rota**, y el operador aprende a ignorar el número;
- una rotura de verdad **se pierde entre ellas**.

Lo tentador —y lo prohibido— es una lista de nombres:

```python
if table_name == "improvement_proposals":
    return  # no es deuda
```

Eso no clasifica: exime. Esconde una rotura real el día que la haya, y no dice
nada sobre la siguiente capacidad que se construya.

## La decisión: el contrato dice **dónde mirar**, no **qué concluir**

`triade/observability/activation_contracts.py` declara, por sujeto, una
clasificación y **la evidencia estructural que la sostiene**, y el mismo módulo
la vuelve a comprobar en cada medición.

Las declaraciones son Python tipado, no un fichero de datos, por dos razones:
este repositorio evita PyYAML a propósito —`core/config.py` trae su propio parser
mínimo de `triade.yml` para no añadir la dependencia—, y así `mypy` y la
validación de `_contract()` fallan al importar, no al leer. Es la misma forma en
que el repositorio ya declara sus capacidades núcleo (`capabilities/bootstrap.py`)
y su triaje de subsistemas.

```
contrato declara:   HUMAN_GATED, gate en `store.py::approve`
detector comprueba: ¿existe ese símbolo? ¿en código alcanzable?
                    ¿el escritor escribe esa tabla de verdad?
                    ¿hay lector? ¿la prueba nombrada existe?
si algo falla     → vuelve a DEUDA_REAL, diciendo qué evidencia se cayó
```

Borra el gate y la tabla vuelve al contador sola. Retira el escritor y vuelve.
Renombra el símbolo y vuelve. Aparecen filas donde se afirmaba que no las habría
y vuelve. **Es lo contrario de una exclusión: es una afirmación falsable.**

### Los tipos de evidencia

Cada uno es una pregunta con respuesta sí/no, sin interpretar nada:

| evidencia | qué comprueba | responde a |
|---|---|---|
| `writer_reachable` | el fichero existe, nombra la tabla y **algún entrypoint lo alcanza** | PRODUCTOR + ALCANZABILIDAD |
| `human_gate` | el símbolo `def` existe, en código alcanzable | GATE |
| `reader_exists` | hay un fichero que nombra la tabla al leerla | CONSUMIDOR |
| `effect_consumer` | un módulo alcanzable usa el símbolo que produce el efecto | EFECTO |
| `append_only` | el escritor tiene `INSERT` y **ningún** `UPDATE`/`DELETE` sobre ella | contrato de bitácora |
| `writer_retired` | el fichero **no existe** — la ausencia es la prueba | retirada deliberada |
| `proof_test` | la prueba nombrada existe | EVIDENCIA |
| `rows_present` / `rows_absent` | la base viva | EVENTO ocurrido o no |
| `empty_source_table` | no hay estímulo externo (p. ej. cero peers) | NO_EXTERNAL_STIMULUS |

`DEUDA_REAL` **no se puede declarar**: no es una categoría que se pida, es lo que
queda cuando ninguna otra se sostiene.

### Lo que impide hacer trampa

No es la buena voluntad de quien escriba la declaración; son
`tests/test_activation_contracts.py`:

- una declaración **sin evidencia no carga** — sería una exclusión por nombre;
- una clasificación fuera del vocabulario no carga;
- borrar el gate declarado devuelve el sujeto a `DEUDA_REAL` **y dice cuál se
  cayó** (la prueba central: falsabilidad);
- un escritor que deja de ser alcanzable rompe el contrato;
- que aparezcan filas rompe un contrato que las negaba;
- una bitácora a la que alguien añade un `UPDATE` deja de serlo;
- y **todos los contratos declarados se comprueban contra el repositorio real**:
  uno que nombre un gate inexistente, un escritor inalcanzable o una prueba
  borrada no llega a mergearse.

### Dónde se comprueba cada cosa, y por qué en dos sitios

La evidencia se parte en dos, y la partición no es cosmética:

- **estructural** —ficheros, símbolos, alcanzabilidad, `append_only`— se
  responde con el repositorio delante. La comprueba CI.
- **de runtime** —`rows_present`, `rows_absent`, `empty_source_table`— sólo
  tiene respuesta sobre la base viva. En CI **no hay base, ni debe haberla**:
  una CI que dependiera de la memoria de producción mediría otra cosa cada
  día, y la primera vez que alguien aprobara una propuesta de mejora se
  pondría roja sin que nada estuviera mal.

La consecuencia hay que decirla en voz alta: **un contrato que mintiera sobre
filas pasaría CI**. Lo caza el detector, que reverifica *todo* sobre la base
real en cada medición y devuelve el sujeto a `DEUDA_REAL` si falla.

CI comprueba que el contrato es **válido**; el detector, que además es
**cierto**. Salió de un rojo de CI en este mismo PR: el gate dependía de la
base de producción y era imposible de pasar fuera de esta máquina.

### Nada se esconde

`debt_items_total` **sigue siendo la suma de todo lo observado**. Lo que se añade
es `debt_real_total` y el desglose `by_classification`, con todas las categorías
a la vista y separadas.

Bajar el contador principal al clasificar sería indistinguible de esconder
categorías — que es exactamente lo que este repositorio ya sufrió el 2026-08-03,
cuando tres tablas salieron del recuento **por degradación**, al perder su
escritor, sin haber ganado una fila. Hay una prueba que lo fija.

## Primer uso: las bitácoras de sólo escritura

`tables_written_never_read` traía cinco tablas. La pregunta correcta no era
«¿alguien las lee?» sino **«¿el efecto de escribirlas viaja por otro sitio?»**.
Cuando el resultado se devuelve a quien llamó y la fila es el registro de lo que
pasó, añadir un lector sería decoración: leería para no hacer nada.

| tabla | filas | clasificación | por qué |
|---|---|---|---|
| `hardware_senses` | 428 | AUDIT_LEDGER | el hipotálamo decide con el snapshot **en memoria**; la fila es el registro de lo medido |
| `governed_research_runs` | 150 | AUDIT_LEDGER | `run()` devuelve claims y `candidate_id` a `worker_loop`; el efecto viaja por el retorno |
| `engineering_evolution_events` | 2 | AUDIT_LEDGER | el porqué de cada paso; el estado consultable vive en su tabla hermana |
| `evidence_remediation_audit` | 479 | HISTORICAL | acta de una remediación puntual, escrita por un script de operador |
| `neuron_certification_transitions` | 13 | HISTORICAL | las 13 cuarentenas de la fase 12; su escritor se retiró a propósito |

Las cinco son **estrictamente `INSERT`**: no hay un solo `UPDATE` ni `DELETE`
sobre ellas en todo el repositorio, y eso se recomprueba en cada medición.

`neuron_certification_transitions` va en el PR que retira su escritor, no en
éste: su contrato afirma `writer_retired`, y aquí todavía sería falso. Que el
contrato **no se sostenga hasta que el cambio ocurra** es la propiedad, no un
inconveniente.

## Lo que esto no hace

No clasifica solo. Cada entrada exige haber recorrido la cadena entera —
productor, evento, alcanzabilidad, gate, consumidor, efecto, evidencia— y
declarar el eslabón que la sostiene. Lo que da es que ese recorrido **quede
escrito y se vuelva a comprobar**, en vez de vivir en un documento que envejece.

## Segundo uso: los seis task types que nunca corrieron

`task_types_never_executed`. **Los seis tienen handler** y `worker_loop` los
despacha: ninguno es un tipo declarado sin implementar. La diferencia está
siempre en el productor o en su condición, y es esa condición la que se declara.

| task type | → | condición declarada y comprobada |
|---|---|---|
| `goal_install` | HUMAN_GATED | `GoalOrchestrator.approve_install(..., approved_by)`; exige goal en `awaiting_approval` |
| `goal_lora_train` | HUMAN_GATED | `GoalOrchestrator.schedule_lora(..., approved_by)` |
| `self_improvement_evaluation` | HUMAN_GATED | el planner sólo encola si hay propuestas `approved`; aprobar exige firma |
| `self_improvement_canary_observation` | HUMAN_GATED | un escalón más abajo: exige canario `running`, que viene de lo anterior |
| `federation_inbox_review` | NO_EXTERNAL_STIMULUS | `federated_exchange_log` vacía: no hay segundo nodo |
| `write_governed_text_artifact` | ON_DEMAND | espera que alguien pida por escrito un entregable de texto |

Dos matices que importan:

**Federación no es «roto por no tener peer».** Sólo se puede llamar ausencia de
estímulo porque la cadena está construida **y probada** —`test_federated_exchange`,
`test_ed25519_federation`, `test_federated_dispatch`—, y eso se declara como
evidencia. La condición `empty_source_table=federated_exchange_log` se cae sola en
cuanto aparezca un intercambio real. No se fabrica un peer.

**`write_governed_text_artifact` estuvo muerto por construcción** —la única forma
de activarlo era escribir su identificador interno literal en la petición— y eso
ya se corrigió: hoy exige verbo de redacción y sustantivo de entregable, que es
más estricto que la compuerta general, no más laxo. Por eso es `ON_DEMAND` y no
`BROKEN_PRODUCER`.

Ninguno se ha ejecutado a mano en producción para vaciar la categoría.

## Medición tras los dos primeros usos

```
observado 50 | DEUDA_REAL 40
{'HUMAN_GATED': 4, 'AUDIT_LEDGER': 3, 'HISTORICAL': 1,
 'NO_EXTERNAL_STIMULUS': 1, 'ON_DEMAND': 1, 'DEUDA_REAL': 40}
```

El total observado no se mueve. Lo que cambia es de cuánto hay que ocuparse.

## Tercer uso: la automejora, una cadena entera colgando de una firma

Seis de las 28 `tables_with_writer_and_no_rows` son el subsistema
`triade/self_improvement/`. **Ninguna es tabla muerta**: las seis tienen escritor
y lector alcanzables. Cuelgan del mismo punto y por diseño — una propuesta que un
humano aprueba —, a distintas distancias:

```
señal → propuesta → [FIRMA HUMANA] → candidato → canario → observaciones
```

| tabla | distancia a la firma |
|---|---|
| `improvement_signals` | antes: se registra por API con llave |
| `improvement_proposals` | **es** el punto de la firma |
| `improvement_history` | el rastro de cada transición |
| `improvement_candidate_links` | un eslabón por debajo |
| `improvement_canaries` | dos |
| `improvement_canary_observations` | tres |

`bridge.approve()` lanza si `approved_by` viene vacío, y `create_candidate` exige
que la propuesta esté ya `approved`. La separación es deliberada —el humano elige
qué se intenta, la máquina hace la verificación rigurosa— y hoy, además, es
**ejercitable**: las rutas `/api/governance/improvement/*` existen y
`tests/test_self_improvement_door.py` recorre señal → propuesta → firma y
comprueba que sin firma válida no se aprueba nada.

Cero filas significa, literalmente, que **nadie ha propuesto todavía una
mejora**. No que el circuito esté roto.

La evidencia `rows_absent` es la que hace que esto caduque solo: en cuanto
alguien ejerza el gate, el contrato deja de sostenerse y hay que volver a mirar
la tabla con datos delante. Que la clasificación tenga fecha de caducidad
automática es la diferencia entre esto y una exclusión.

```
observado 50 | DEUDA_REAL 34
{'HUMAN_GATED': 10, 'AUDIT_LEDGER': 3, 'NO_EXTERNAL_STIMULUS': 1,
 'ON_DEMAND': 1, 'HISTORICAL': 1, 'DEUDA_REAL': 34}
```
