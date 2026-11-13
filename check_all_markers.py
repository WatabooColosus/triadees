# Check each failing module for markers
modules = [
    "triade/capabilities/metacognition.py",
    "triade/federation/dispatch.py",
    "triade/federation/exchange.py",
    "triade/federation/registry.py",
    "triade/runtime/utility_ledger.py",
    "triade/validation/runtime_long_run.py",
    "triade/verification/certification.py",
]

markers = [
    'SUBSYSTEM_STATUS = "inactive"',
    "SUBSISTEMA INACTIVO",
    "INACTIVE SUBSYSTEM",
    "no activa una capacidad productiva",
    "benchmark",
    "evaluation",
]

for mod in modules:
    with open(mod, "r") as f:
        content = f.read()
    print(f"\n=== {mod} ===")
    found = False
    for m in markers:
        if m in content:
            print(f"  FOUND: {m}")
            found = True
    if not found:
        print("  NO MARKERS FOUND")
        # Show first 300 chars
        print(f"  Content preview: {content[:300]}")
