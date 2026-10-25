#!/usr/bin/env python3
"""Optional real functional battery; independent of internal worker scores.

Run only in private Colab. Phase 'pre' must truly happen BEFORE a new lesson.
A 'post' battery uses a session ID and refuses runs predating the lesson.
This runner neither changes stable memory nor certifies causal improvement.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sqlite3
import sys


def main(argv=None):
    p=argparse.ArgumentParser(description="Tríade Ω R6.3 · prueba funcional real")
    p.add_argument('--neuron',type=int,required=True)
    p.add_argument('--phase',choices=['pre','post'],required=True)
    p.add_argument('--session',default=None)
    p.add_argument('--limit',type=int,default=5)
    p.add_argument('--dry-run',action='store_true')
    a=p.parse_args(argv)
    if not 1<=a.limit<=5: p.error('--limit debe estar entre 1 y 5')
    if (a.phase=='post') != bool(a.session):p.error('post exige --session; pre no acepta --session')
    root=Path(__file__).resolve().parents[1]
    db=root/'triade/memory/triade.db'
    if not db.is_file():p.error('Bodega R5 no localizada')
    from triade.neurons.functional_evidence import CASES,supported_domain,register_actual_probe,functional_comparison
    with sqlite3.connect(db) as c:
        neuron=c.execute('SELECT name,domain FROM neurons WHERE id=?',(a.neuron,)).fetchone()
        if neuron is None:p.error('Neurona no existe')
        dom=supported_domain(neuron[0],neuron[1])
        if dom is None:p.error('Aún no existe una suite funcional fiable para este dominio')
        if a.session:
            ses=c.execute('SELECT neuron_id,created_at FROM neuron_education_sessions WHERE session_id=?',(a.session,)).fetchone()
            if ses is None or int(ses[0])!=a.neuron:p.error('Sesión no pertenece a la neurona')
    chosen=[c for c in CASES if c.domain==dom][:a.limit]
    print('TRÍADE Ω R6.3',json.dumps({'neuron':a.neuron,'domain':dom,'phase':a.phase,'cases':[c.id for c in chosen],'functional_not_image_processing':dom=='visual_text'},ensure_ascii=False))
    if a.dry_run:
        print('Modo lectura. Ningún modelo llamado ni fila escrita.');return 0
    from triade.core.runner import TriadeRunner
    runner=TriadeRunner(runs_dir=root/'runs',db_path=db,use_ollama=True)
    accepted=0
    for idx,case in enumerate(chosen,1):
        print(f'[{idx}/{len(chosen)}] Caso {case.id}: generando respuesta real…',flush=True)
        # Declared domain informs the neuron routing, not the answer key.
        prompt=f'{case.question}\nContexto de dominio: {neuron[1]}.'
        try:
            result=runner.run(user_input=prompt,source='neuron_functional_probe',context={'semantic_domain':str(neuron[1]),'functional_probe_case':case.id},propose_neurons=False)
            runid=str(result.get('run_id') or '')
            if not runid: raise RuntimeError('Sin run_id, no medible')
            answer=str(result.get('response') or '')
            out=register_actual_probe(db,run_id=runid,neuron_id=a.neuron,case_id=case.id,phase=a.phase,session_id=a.session,answer=answer)
            accepted += int(out['status'] in ('recorded','already_recorded'))
            print(f"✓ {case.id} resultado={out['score']} run={runid} (se registra solo si la neurona intervino)",flush=True)
        except Exception as exc:
            print(f'! {case.id} no acreditado: {type(exc).__name__}: {str(exc)[:260]}',flush=True)
    print(json.dumps({'cases_attempted':len(chosen),'valid_functional_probes':accepted,'learned_proven':False,'causal_proof':False},ensure_ascii=False))
    if a.session:
        with sqlite3.connect(db) as c:
            date=c.execute('SELECT created_at FROM neuron_education_sessions WHERE session_id=?',(a.session,)).fetchone()[0]
            print('A/B:',json.dumps(functional_comparison(c,neuron_id=a.neuron,session_id=a.session,lesson_at=date),ensure_ascii=False))
    return 0


if __name__=='__main__':raise SystemExit(main())