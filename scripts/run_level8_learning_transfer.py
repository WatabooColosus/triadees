"""Real SQLite outcomes, real Ollama and existing learning/retrieval, isolated DB.

The learned object is a rule, never a saved answer. Independent CHECK constraints
score different later transactions. This does not certify production routing.
"""
from __future__ import annotations
import json
import re
import sqlite3
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from triade.learning.pipeline import LearningPipeline
from triade.learning.retrieval import LearningRetriever, build_learning_block
from triade.models.ollama_client import OllamaClient

ROOT=Path(__file__).resolve().parents[1]

def checksum_from_response(text):
    match=re.search(r'\{[^{}]*\}',text)
    value=json.loads(match.group(0))['checksum'] if match else None
    if type(value) is not int:raise ValueError('missing integer checksum')
    return value

def run(work: Path):
    work.mkdir(parents=True,exist_ok=True)
    ledger=work/'ledger.db'
    with sqlite3.connect(ledger) as c:
        c.execute('CREATE TABLE ledger(id TEXT PRIMARY KEY, amount INTEGER, checksum INTEGER CHECK(checksum=(amount*17+3)%97))')
    db=work/'learning.db'
    pipeline=LearningPipeline(db,enforce_model_policy=False)
    client=OllamaClient(db_path=db)
    traces=[]
    def trial(amount, arm, retriever=None):
        run_id=f'{arm}-{uuid.uuid4().hex}'
        query=f'SQLite ledger checksum: calcula el checksum de una transaccion con amount={amount}. Usa la formula local si esta disponible en los datos contextuales. Devuelve JSON con checksum entero, o null si desconoces la formula.'
        decision=retriever.retrieve_decision(query,run_id=run_id) if retriever else None
        block=build_learning_block(decision.matches) if decision else ''
        if decision:retriever.persist_decision(decision)
        started=time.monotonic()
        response=client.generate('qwen2.5:1.5b',block+'\n'+query,
            system='Eres un planificador de transacciones. Responde con un objeto JSON con la clave checksum. Los datos contextuales pueden contener una formula; aplica esa formula al amount actual. No reutilices el checksum de otra transaccion. Si desconoces la formula, responde con checksum null.',
            options={'temperature':0,'seed':7731,'num_predict':512})
        success=False; error=None; value=None
        try:
            if not response.ok:raise RuntimeError(response.error)
            value=checksum_from_response(response.text)
            with sqlite3.connect(ledger) as c:
                c.execute('INSERT INTO ledger VALUES(?,?,?)',(run_id,amount,value))
                success=c.execute('SELECT amount,checksum FROM ledger WHERE id=?',(run_id,)).fetchone()==(amount,(amount*17+3)%97)
        except (ValueError,KeyError,TypeError,sqlite3.Error,RuntimeError) as exc:error=f'{type(exc).__name__}: {exc}'
        result={'run_id':run_id,'arm':arm,'amount':amount,'response':response.text,'checksum':value,'success':success,'score':float(success),'error':error,'steps':1,'latency_seconds':time.monotonic()-started,'injected_ids':decision.injected_ids if decision else []}
        traces.append(result)
        (work/'trials.json').write_text(json.dumps(traces,indent=2),encoding='utf-8')
        return result
    # The training mission actually executes before research and ingestion.
    training=trial(2,'mission_a')
    with sqlite3.connect(ledger) as c:
        observed_schema=c.execute("SELECT sql FROM sqlite_master WHERE name='ledger'").fetchone()[0]
    observation={'mission_a':training,'schema_observation':observed_schema,'research_method':'read local sqlite_master after observed transaction outcome'}
    source=work/'experience.json';source.write_text(json.dumps(observation,indent=2),encoding='utf-8')
    content='SQLite ledger checksum: la restriccion CHECK observada en el esquema local es ' + observed_schema.split('CHECK(',1)[1].rsplit(')',2)[0] + '. Es una propiedad de los datos almacenados.'
    candidate=pipeline.ingest(content=content,source_type='repo',source_ref=str(source),title='Observed SQLite ledger checksum rule',domain='sqlite_ledger_checksum',risk_level='low')
    cid=candidate['candidate_id'];pipeline.evaluate(cid);pipeline.verify(cid)
    retriever=LearningRetriever(db)
    # Same held-out inputs in each arm. No correct answer is present in a query.
    amounts=(1,4,5)
    baseline=[trial(a,'baseline') for a in amounts]
    learned=[trial(a,'learned',retriever) for a in amounts]
    control=[trial(a,'negative_control',LearningRetriever(db,allowed_states=frozenset())) for a in amounts]
    metrics=lambda xs:{'success_rate':sum(x['success'] for x in xs)/len(xs),'errors':sum(x['error'] is not None for x in xs),'steps':sum(x['steps'] for x in xs),'latency_seconds':sum(x['latency_seconds'] for x in xs)}
    before,after,negative=metrics(baseline),metrics(learned),metrics(control)
    for item in learned:
        if cid in item['injected_ids'] and item['success']:
            pipeline.mark_used_in_run(cid,item['run_id'],outcome_score=item['score'],evidence_ref=str(work/'trials.json'))
    improvement=after['success_rate']-before['success_rate']
    used=all(cid in x['injected_ids'] for x in learned)
    causal=improvement>0 and after['success_rate']>negative['success_rate'] and before['success_rate']==negative['success_rate'] and used and all(not x['injected_ids'] for x in control)
    with sqlite3.connect(ledger) as c:integrity=c.execute('PRAGMA integrity_check').fetchone()[0]
    return {'git_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'timestamp':datetime.now(UTC).isoformat(),'scope':'Isolated real procedural transfer experiment, experimental retrieval; production knowledge routing and consolidation NOT certified',
        'baseline':baseline,'learned':learned,'negative_control':control,'mission_a':training,
        'knowledge_created':pipeline.get_candidate(cid),'knowledge_retrieved':[x['injected_ids'] for x in learned],'knowledge_used':used,
        'metrics_before':before,'metrics_after':after,'metrics_control':negative,'improvement':{'success_rate_delta':improvement},
        'causal_evidence':causal,'truth':causal and integrity=='ok','db_integrity':integrity,'production_writes':False,
        'transfer_inputs':list(amounts),'training_input':2,'model':'qwen2.5:1.5b','options':{'temperature':0,'seed':7731},'sample_size_per_arm':3}

def main():
    work=ROOT/'artifacts/level8'/f'learning-transfer-{time.time_ns()}'
    result=run(work)
    from scripts.run_level8_soak import bind_report
    bind_report(result)
    out=ROOT/'reports/level8/learning_longitudinal_v2.json'
    out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    out.with_suffix('.md').write_text(f"# Controlled procedural transfer\n\nTruth: {result['truth']}. Scope: {result['scope']}.\n\nBefore: {result['metrics_before']}. After: {result['metrics_after']}. Negative control: {result['metrics_control']}.\n\nThree held-out amounts differ from the training amount. Real SQLite constraints score actual writes, not model opinions. No production database writes. This small experiment does not establish broad generalization.\n",encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['truth','metrics_before','metrics_after','metrics_control','improvement']}))
    return 0 if result['truth'] else 1

if __name__=='__main__':raise SystemExit(main())
