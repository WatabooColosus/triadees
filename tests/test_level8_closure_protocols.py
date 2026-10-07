from pathlib import Path
import pytest
from scripts.run_level8_learning_transfer import checksum_from_response
from scripts.run_level8_task_recovery import run
from scripts.run_level8_soak import summarize
from triade.runtime.task_leases import AutonomousTaskStore

def test_real_process_crash_recovers_committed_effect_and_fences_old_owner(tmp_path):
    result=run(tmp_path)
    assert result['truth']
    assert result['duplicate_effects']==0
    assert result['lease_after']['attempt']==2
    old=result['lease_before']
    store=AutonomousTaskStore(tmp_path/'recovery.db')
    assert not store.complete(old['task_id'],old['worker_id'],old['lease_generation'],str(tmp_path/'receipt.json'))

@pytest.mark.parametrize('response',['{"checksum":null}','{"checksum":true}','71','{"checksum":"71"}'])
def test_unsupported_model_outputs_do_not_become_success(response):
    with pytest.raises(ValueError):checksum_from_response(response)

def sample(cycles,tasks,alive=True):
    return {'process':{'alive':alive,'rss_kb':102400},'supervision':{'url_available':True},'integrity_check':'ok','metabolic_cycles':cycles,'db_bytes':100,'tasks_by_status':{'completed':tasks},'learning_events':0}

@pytest.mark.parametrize('duration,unchanged,progress,alive',[(30,True,True,True),(1800,False,True,True),(1800,True,False,True),(1800,True,True,False)])
def test_soak_rejects_short_stale_idle_or_failed_observations(duration,unchanged,progress,alive):
    samples=[sample(1,2),sample(2 if progress else 1,3 if progress else 2,alive)]
    assert not summarize(samples,duration,unchanged)['truth']
