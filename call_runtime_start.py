import json

import requests

r = requests.post(
    "http://127.0.0.1:8010/api/runtime/start",
    json={"mode": "full_local_guarded", "interval_seconds": 60, "max_cycles": 0},
    timeout=10,
)
print("Status:", r.status_code)
print(json.dumps(r.json(), ensure_ascii=True))
