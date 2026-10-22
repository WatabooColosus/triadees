from pathlib import Path

from triade.observability.activation_contracts import ContractVerifier, load_contracts
from triade.observability.code_graph import build_module_index, reachable_modules

root = Path.cwd()
index = build_module_index(root)
alcanzables = reachable_modules(root, index)

contratos = load_contracts()
verificador = ContractVerifier(root, db_path=Path('triade/memory/triade.db'), reachable=alcanzables)

modulos_fallando = [
    'triade/capabilities/metacognition.py',
    'triade/federation/dispatch.py',
    'triade/federation/exchange.py',
    'triade/federation/registry.py',
    'triade/runtime/utility_ledger.py',
    'triade/validation/runtime_long_run.py',
    'triade/verification/certification.py',
]

print("=== Contracts loaded ===")
for k in contratos:
    if k.startswith('module:'):
        print(f"  {k}")

print("\n=== Verifying each ===")
for m in modulos_fallando:
    subject = f'module:{m}'
    contrato = contratos.get(subject)
    if contrato:
        veredicto = verificador.verify(contrato)
        print(f'{m}:')
        print(f'  holds: {veredicto.holds}')
        print(f'  classification: {veredicto.classification}')
        print(f'  failed: {veredicto.failed}')
    else:
        print(f'{m}: NO CONTRACT')
    print()