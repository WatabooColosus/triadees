# Check metacognition.py for inactive markers
with open('triade/capabilities/metacognition.py', 'r') as f:
    content = f.read()

markers = [
    'SUBSYSTEM_STATUS = "inactive"',
    'SUBSISTEMA INACTIVO',
    'INACTIVE SUBSYSTEM',
    'no activa una capacidad productiva',
    'benchmark',
    'evaluation',
]

for m in markers:
    if m in content:
        print('FOUND:', m)
    else:
        print('MISSING:', m)

print()
print('First 200 chars:')
print(content[:200])