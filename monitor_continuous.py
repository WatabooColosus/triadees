import time

from triade.core.life_pulse import LIFE_PULSE

for i in range(6):
    time.sleep(15)
    snap = LIFE_PULSE.snapshot()
    cr = snap.get('continuous_runner', {})
    print('t={}s: cycles={}, running={}, autonomy={}'.format(i*15, cr.get('cycles'), cr.get('running'), LIFE_PULSE.autonomy_level))