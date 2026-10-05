import asyncio

async def test_lifespan():
    import os
    os.environ['TRIADE_DB_PATH'] = 'triade/memory/triade.db'
    os.environ['TRIADE_RUNS_DIR'] = 'runs'
    
    from triade.core.identity_continuity import IdentityContinuity
    from triade.core.runtime_scope import is_test_runtime
    from triade.memory.db_pragmas import ensure_durability_pragmas
    
    db_path = os.getenv('TRIADE_DB_PATH', 'triade/memory/triade.db')
    
    from triade.core.identity_continuity import IdentityContinuity
    identity = IdentityContinuity(db_path).verify(run_id='single-port-startup')
    print('Identity:', identity)
    
    if is_test_runtime() or os.getenv('TRIADE_DISABLE_BACKGROUND') == '1':
        print('Test runtime detected')
        return
    
    from triade.core.always_on import load_always_on_config
    conversation_only = bool(load_always_on_config().get('conversation_only', False))
    print('conversation_only:', conversation_only)
    
    from triade.core.always_on import load_always_on_config as load_cfg
    from triade.core.life_pulse import LIFE_PULSE
    
    cfg = load_cfg()
    print('Config loaded, continuous_runner_enabled:', cfg.get('continuous_runner_enabled'))
    
    from triade.core.life_pulse import LIFE_PULSE
    continuous_result = LIFE_PULSE.configure_continuous_runner(
        enabled=bool(cfg.get('continuous_runner_enabled', False)),
        autonomy_level=str(
            cfg.get('continuous_runner_autonomy_level', 'observe_only')
        ),
        interval_seconds=int(cfg.get('continuous_runner_interval_seconds', 60)),
        max_cycles=int(cfg.get('continuous_runner_max_cycles', 0)),
    )
    print('Configure result:', continuous_result)
    
    LIFE_PULSE.start()
    print('LIFE_PULSE started')
    
    import time
    time.sleep(2)
    
    snap = LIFE_PULSE.snapshot()
    print('Snapshot continuous_runner:', snap.get('continuous_runner'))

asyncio.run(test_lifespan())