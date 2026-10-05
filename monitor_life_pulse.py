import time
from triade.core.life_pulse import LIFE_PULSE
from triade.core.always_on import load_always_on_config

# Check initial state
print('Initial state:')
print('  continuous_run_enabled:', LIFE_PULSE.continuous_run_enabled)
print('  _continuous_thread:', LIFE_PULSE._continuous_thread)

# Configure and start
cfg = load_always_on_config()
result = LIFE_PULSE.configure_continuous_runner(
    enabled=True,
    autonomy_level='promote_stable',
    interval_seconds=10,
)
print('Configure:', result)

LIFE_PULSE.start()

# Monitor for 30 seconds
for i in range(6):
    time.sleep(5)
    snap = LIFE_PULSE.snapshot()
    cr = snap.get('continuous_runner', {})
    thread = LIFE_PULSE._continuous_thread
    thread_alive = thread.is_alive() if thread else False
    print('t={}s: enabled={}, running={}, cycles={}, thread_alive={}, continuous_run_enabled={}'.format(
        i*5, cr.get('enabled'), cr.get('running'), cr.get('cycles'), 
        thread_alive,
        LIFE_PULSE.continuous_run_enabled))