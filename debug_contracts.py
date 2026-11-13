from pathlib import Path

from triade.observability.activation_contracts import ContractVerifier, load_contracts
from triade.observability.code_graph import build_module_index, reachable_modules

root = Path.cwd()
index = build_module_index(root)
alcanzables = reachable_modules(root, index)

# Load contracts
contratos = load_contracts()

# Create verifier with live DB
verificador = ContractVerifier(
    root,
    db_path=Path("triade/memory/triade.db"),
    reachable=alcanzables,
)

# Test each failing table
tablas_fallando = [
    "goal_events",
    "peft_serving_state",
    "semantic_embeddings",
    "worker_tasks",
]

for tabla in tablas_fallando:
    subject = f"table:{tabla}"
    contrato = contratos.get(subject)
    if contrato:
        veredicto = verificador.verify(contrato)
        print(f"{tabla}:")
        print(f"  holds: {veredicto.holds}")
        print(f"  classification: {veredicto.classification}")
        print(f"  failed: {veredicto.failed}")
        print(f"  reason: {veredicto.reason}")
    else:
        print(f"{tabla}: NO CONTRACT FOUND")
    print()
