import requests
import time

for i in range(6):
    r = requests.get('http://127.0.0.1:8010/api/runtime/heartbeat', timeout=10)
    data = r.json()
    print('t={}s: heartbeat_cycle={}, workers_active={}, mode={}, always_on_enabled={}'.format(
        i*10, data.get('heartbeat_cycle'), data.get('workers_active'), data.get('mode'), 
        data.get('always_on', {}).get('enabled', 'N/A')))
    time.sleep(10)