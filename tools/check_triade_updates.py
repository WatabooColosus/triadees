#!/usr/bin/env python3
"""Busca actualizaciones de Tríade en el manifiesto remoto, no en Colab."""
from __future__ import annotations
import argparse,json,subprocess,urllib.request
from pathlib import Path
URL="https://raw.githubusercontent.com/WatabooColosus/triadees/codex/triade-5.8.0-runtime-recovery/releases/manifest.json"
def local(root):
    try:
        return subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
    except Exception:
        return None
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",default=".");a=ap.parse_args()
    with urllib.request.urlopen(URL,timeout=15) as r: remote=json.load(r)
    head=local(Path(a.root))
    result={"status":"ok","remote":remote,"local_commit":head,"update_available":bool(head and head!=remote["commit"]),"source":URL}
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
