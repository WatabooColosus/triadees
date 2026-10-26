import json
from datetime import datetime

import requests

print("=" * 80)
print("TRIADE OMEGA - ANALISIS EN TIEMPO REAL -", datetime.now().isoformat())
print("=" * 80)

# 1. HEARTBEAT
r = requests.get("http://127.0.0.1:8010/api/runtime/heartbeat", timeout=10)
hb = r.json()
print("\n1. HEARTBEAT VITAL:")
print(f"   Status: {hb.get('status')}")
print(f"   Truth: {hb.get('heartbeat_truth')}")
print(f"   Mode: {hb.get('mode')}")
print(f"   Workers Active: {hb.get('workers_active')}")
print(f"   Heartbeat Cycle: {hb.get('heartbeat_cycle')}")
print(f"   Last Cycle: {hb.get('last_cycle_at')}")
print(f"   Runtime PID: {hb.get('runtime_pid')}")
print(f"   Ollama Blood: {hb.get('ollama_blood', {}).get('status')}")

# 2. DEEP HEALTH
r = requests.get("http://127.0.0.1:8010/health/deep", timeout=10)
dh = r.json()
print("\n2. DEEP HEALTH:")
print(f"   Overall: {dh.get('status')}")
print(f"   Checks: {dh.get('checks')}")
print(f"   Always On: {dh.get('always_on')}")
print(f"   Workers: {dh.get('workers')}")
print(f"   Ollama Blood: {dh.get('ollama_blood')}")
print(f"   Live Heartbeat Cycle: {dh.get('live_heartbeat', {}).get('cycle')}")

# 3. INTERNAL GRAPHS HEALTH
r = requests.get("http://127.0.0.1:8010/api/internal-graphs/health", timeout=10)
ih = r.json()
print("\n3. INTERNAL GRAPHS HEALTH:")
print(f"   Status: {ih.get('status')}")

# 4. DEBT REPORT
r = requests.get("http://127.0.0.1:8010/api/internal-graphs/debt", timeout=10)
dr = r.json()
print("\n4. DEBT REPORT:")
print(f"   Status: {dr.get('status')}")
print(f"   Total items: {dr.get('debt_items_total')}")
print(f"   Real debt: {dr.get('debt_real_total')}")
print(f"   By classification: {dr.get('by_classification')}")
cr = dr.get("continuous_runner", {})
print(f"   Continuous runner: {cr}")

# 5. LEARNING PIPELINE STATUS
r = requests.get("http://127.0.0.1:8010/api/knowledge/summary", timeout=10)
ks = r.json()
print("\n5. KNOWLEDGE PIPELINE:")
print(f"   {json.dumps(ks, indent=3)}")

print("\n" + "=" * 80)
print("ANÁLISIS COMPLETO -", datetime.now().isoformat())
print("=" * 80)
