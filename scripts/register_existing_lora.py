"""Registra datasets y adaptadores existentes sin activarlos."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from triade.core.governed_datasets import GovernedDatasets


def main():
 g=GovernedDatasets(); source=Path("data/lora/triade_continuity_smoke.jsonl")
 existing=next((d for d in g.list_datasets() if d.source==str(source)),None)
 if existing: ds=existing
 else:
  ds=g.create_dataset("Triade continuity governed","Dataset smoke de continuidad","memory_continuity",str(source),
    {"allowed_uses":["lora_training"],"requires_consent":False,"source_sha256":hashlib.sha256(source.read_bytes()).hexdigest()})
  rows=sum(1 for line in source.read_text().splitlines() if line.strip())
  ds=g.update_dataset(ds.dataset_id,{"row_count":rows,"schema_json":{"format":"jsonl","required":["instruction","response"]},"status":"training_ready"})
 registered=[]
 known={a.name:a for a in g.list_adapters()}
 for manifest_path in Path("artifacts/adapters").glob("*/triade_adapter_manifest.json"):
  name=manifest_path.parent.name; manifest=json.loads(manifest_path.read_text())
  if name in known: registered.append(known[name].adapter_id);continue
  adapter=g.create_adapter(name,manifest["base_model"],ds.dataset_id,manifest.get("config",{}))
  metrics={**manifest.get("metrics",{}),"artifact_path":str(manifest_path.parent),"adapter_sha256":manifest.get("adapter_sha256"),"automatic_activation":False}
  g.update_adapter_status(adapter.adapter_id,"evaluated",metrics);registered.append(adapter.adapter_id)
 print(json.dumps({"status":"completed","dataset_id":ds.dataset_id,"adapters":registered,"activated":False},indent=2))
if __name__=="__main__":main()
