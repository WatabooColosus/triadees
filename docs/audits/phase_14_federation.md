# Fase 14 — federación real

Fecha UTC: 2026-07-29

Base: `f2b3b69`

Estado: `completed`

Se añadió identidad Ed25519 por nodo al transporte persistente existente. La
validación levanta dos procesos HTTP reales con PID, puerto, DB y par de claves
distintos. A firma evidencia; B verifica la firma, reproduce el SHA-256, acepta,
rechaza replay mediante idempotencia; A firma una revocación y B la aplica.

El registro existente aporta estados persistent/trusted/quarantined/revoked,
fingerprint único (barrera Sybil básica), reputación, permisos deny-by-default e
historial. Los envelopes aportan expiración, nonce y operación offline/online.

## Reproducción

```bash
pytest -q tests/test_ed25519_federation.py tests/test_federated_exchange.py
python scripts/run_phase_14_federation.py
```

Evidencia: `artifacts/triade_verify/phase_14/federation.json`.

La prueba usa transporte loopback real entre procesos, no registros simulados.
No acredita operación entre hosts geográficamente separados.

## Validación ejecutada

```text
python -m compileall -q triade apps scripts tests                PASS
ruff check (archivos de fase)                                    PASS
ruff format --check .                                            PASS (776 files)
pytest (Ed25519, exchange y registry)                             PASS (15)
pytest (dispatch, evidence gate, federation y Ed25519)            PASS (20)
pytest -q tests/operational_truth                                PASS (18)
python scripts/run_runtime_concurrency_test.py                   PASS
python scripts/run_phase_14_federation.py                        PASS
```

Los PIDs observados fueron distintos; la evidencia se reprodujo, el reenvío fue
idempotente y el estado final en B fue `revoked`.
