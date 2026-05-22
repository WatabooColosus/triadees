# Triade Omega - Crystal Q Formula 1.8C

## Fase

TRIADE_CRYSTAL_Q_FORMULA_1.8C

## Objetivo

Acercar q_crystal a la formula teorica oficial y hacer que la regulacion del Cristal influya realmente en el plan y la respuesta de Central.

## Archivos

- triade/core/crystal.py
- triade/core/central.py
- tests/test_crystal_v2.py

## Formula teorica de referencia

S_rel(t) = alpha * S_H(t) + beta * S_T(t)

Q_cristal(t) = (((S_rel(t) + C_prime(t)) / I_prime(t)) ^ R_prime(t)) * Phi(M,t)

## Implementacion operativa

Crystal.q_crystal_payload calcula componentes normalizados:

- s_h: senal afectivo-etica aproximada desde PV-7, intensidad y riesgo
- s_t: senal tecnica/central aproximada desde etica, profundidad, relacion, estabilidad y creatividad
- alpha y beta: ponderacion relacional
- s_rel: integracion de Hipotalamo y Central
- c_prime: contribucion creativa/profunda
- i_prime: penalizacion por intensidad y riesgo
- r_prime: estabilizacion por estabilidad y etica
- phi_memory: continuidad ponderada de memoria
- q_crystal: resultado normalizado en rango 0 a 1

## Influencia en Central

Central.plan ahora cambia segun q_crystal:

- q_crystal menor a 0.40: prudencia elevada
- q_crystal mayor o igual a 0.70 y stability mayor o igual a 0.65: profundidad estable
- resto: equilibrio operativo

Central.respond incorpora el modo del Cristal al fallback y al prompt enviado al modelo local.

## Evidencia

Cada crystal.json y cada registro SQLite siguen conservando q_crystal.
Decision_notes ahora incluye componentes de formula:

- s_rel
- i_prime
- r_prime
- phi_memory

## Validacion local

Ejecutar:

- git pull
- source .venv/bin/activate
- pytest
- sudo systemctl restart triade-chat-ui

Luego ejecutar un run y revisar:

- runs/<run_id>/crystal.json
- runs/<run_id>/plan.json
- runs/<run_id>/output.json

## Siguiente fase sugerida

TRIADE_CRYSTAL_TEMPORAL_STATE_1.8D

Objetivo: que el Cristal evalúe continuidad entre runs, variaciones de q_crystal, estabilidad histórica y alertas por degradación.