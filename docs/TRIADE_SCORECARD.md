# Scorecard Tríade - PR #9

Escala: 0 a 10. La puntuacion mide el estado real del codigo presente, no la vision conceptual.

| Area | Puntaje | Lectura |
| --- | ---: | --- |
| Arquitectura | 7.5 | La separacion por organos, runner auditable, memoria y federacion esta clara. El principal costo es la concentracion de responsabilidades en `apps/single_port_app.py` y apps historicas redundantes. |
| Seguridad | 7.0 | Buen bloqueo de permisos prohibidos, Safety, no consolidacion automatica y tokens/admin env. Pendiente: retirar tokens en query, cache de nonces, rotacion de secretos y endurecer perfiles publicos. |
| Aprendizaje | 7.0 | Pipeline candidato/evaluado/verificado/consolidado bien alineado con Tríade. Falta aprendizaje web controlado completo y mas pruebas de ataques de memoria. |
| Federacion | 6.5 | Registro, pausa/revocacion, logs, learning_queue y transporte firmado local existen. El relay publico y compute jobs aun necesitan trazabilidad y contrato unico. |
| Testing | 8.0 | Suite Python y CI pasan; hay cobertura para core, learning, federation, relay y Android build. Falta instrumentacion Android y smoke test LLM real. |
| Documentacion | 7.5 | Hay mucha documentacion y reportes de fase. Riesgo: exceso historico y algunas piezas pueden parecer mas maduras de lo que son. |
| Escalabilidad | 5.0 | Buen punto de partida, pero colas en memoria, SQLite local y relay simple limitan operacion 24/7 multi-nodo. |
| Observabilidad | 7.0 | Runs auditables, logs federados, doctors y reportes existen. Falta telemetria consolidada de jobs, nodos y runtime Android. |
| Mantenibilidad | 6.0 | El sistema es comprensible pero necesita reducir duplicacion, dividir single port app y formalizar migraciones. |

Nota global: 6.9 / 10

## Madurez

Nivel actual: FASE_D_PLUS_ALPHA.

Lectura: Tríade ya es un MVP local verificable con una rama evolutiva de federacion y Android. Todavia no es Fase E estable porque el transporte federado no es unico, el relay publico requiere endurecimiento y el runtime LLM Android no esta validado como capacidad general.

## Decision de release recomendada

PR #9 debe pasar a revision humana como Ready For Review condicionado, sin merge automatico. Si el equipo quiere reducir riesgo de revision, puede dividir siguientes trabajos en PRs separados, pero no es obligatorio dividir PR #9 antes de revisarlo porque CI esta verde y la documentacion marca limites reales.
