"""Bounded transport diagnosis of the existing failed experiment, not certification."""
from __future__ import annotations
import hashlib
import argparse
import json
import subprocess
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from triade.learning.retrieval import LearningRetriever, build_learning_block
from scripts.run_level8_learning_transfer import checksum_from_response

ROOT = Path(__file__).resolve().parents[1]
TRIADE_ENTRYPOINT_KIND = 'manual_diagnostic'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='qwen2.5:1.5b', choices=['qwen2.5:1.5b', 'qwen2.5-coder:3b'])
    args = parser.parse_args()
    prior = json.loads((ROOT / 'reports/level8/learning_longitudinal_v2.json').read_text())
    candidate = prior['knowledge_created']
    db = Path(candidate['source_ref']).parent / 'learning.db'
    amount = 4
    query = f'SQLite ledger checksum: calcula el checksum de una transaccion con amount={amount}. Usa la formula local si esta disponible en los datos contextuales. Devuelve JSON con checksum entero, o null si desconoces la formula.'
    decision = LearningRetriever(db).retrieve_decision(query, run_id='diagnostic-only')
    block = build_learning_block(decision.matches)
    system = 'Eres un planificador de transacciones. Responde con un objeto JSON con la clave checksum. Los datos contextuales pueden contener una formula; aplica esa formula al amount actual. No reutilices el checksum de otra transaccion. Si desconoces la formula, responde con checksum null.'
    schema = {'type':'object','properties':{'checksum':{'type':['integer','null']}},'required':['checksum'],'additionalProperties':False}
    observations = []
    for framing, output_format in [('original', schema), ('original', 'json'), ('original', None)]:
        payload = {'model': args.model, 'prompt': block+'\n'+query, 'system': system,
                   'stream':False, 'keep_alive':0, 'options':{'temperature':0,'seed':7731,'num_predict':512,'num_ctx':2048}}
        if output_format is not None:
            payload['format'] = output_format
        started = time.monotonic()
        try:
            request = urllib.request.Request('http://127.0.0.1:11434/api/generate', data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.load(response)
            try:
                actual = checksum_from_response(body.get('response',''))
            except (ValueError, KeyError, TypeError):
                actual = None
            observations.append({'request':payload,'response':body,'actual':actual,'expected':71,
                                 'success':actual==71,'seconds':time.monotonic()-started})
        except (OSError, ValueError) as exc:
            observations.append({'request':payload,'error':str(exc),'seconds':time.monotonic()-started,'success':False})
    report = {'timestamp':datetime.now(UTC).isoformat(),
              'git_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'scope':'Diagnostic replay, one input; no learning certification or production writes',
              'candidate_id':candidate['candidate_id'], 'stored_content':candidate['content'],
              'retrieved_ids':decision.injected_ids, 'context':block,
              'context_sha256':hashlib.sha256(block.encode()).hexdigest(),
              'complete_rule_in_context':candidate['content'] in block,
              'central_invoked':False,'max_llm_calls':3,'observations':observations}
    out = ROOT / ('reports/evolution/learning_diagnosis_coder.json' if args.model != prior['model'] else 'reports/evolution/learning_diagnosis.json')
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'complete_rule_in_context':report['complete_rule_in_context'],
                      'results':[(x['request'].get('format'),x.get('actual'),x['success']) for x in observations]}))


if __name__ == '__main__':
    main()
