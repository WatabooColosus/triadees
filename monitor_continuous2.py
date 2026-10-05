import time
from triade.core.life_pulse import LIFE_PULSE
from triade.core.always_on import load_always_on_config

# Simulate the startup sequence
cfg = load_always_on_config()
result = LIFE_PULSE.configure_continuous_runner(
    enabled=bool(cfg.get('continuous_runner_enabled', False)),
    autonomy_level=str(cfg.get('continuous_runner_autonomy_level', 'observe_only')),
    interval_seconds=int(cfg.get('continuous_runner_interval_seconds', 60)),
    max_cycles=int(cfg.get('continuous_runner_max_cycles', 0)),
)
print('Configure:', result)

LIFE_PULSE.start()

for i in range(12):
    time.sleep(5)
    snap = LIFE_PULSE.snapshot()
    cr = snap.get('continuous_runner', {})
    thread_alive = LIFE_PULSE._continuous_thread.is_alive() if LIFE_PULSE._continuous_thread else False
    print('t={}s: enabled={}, running={}, cycles={}, thread_alive={}'.format(
        i*5, cr.get('enabled'), cr.get('running'), cr.get('cycles'), thread_alive))

import time