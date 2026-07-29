#!/usr/bin/env python3
"""Prepara instalación systemd; dry-run predeterminado, sin shell."""

import argparse
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="copiar unidades; no habilita ni inicia servicios")
    parser.add_argument("--target", default="/etc/systemd/system")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / "deploy/systemd"
    target = Path(args.target).resolve()
    units = sorted(source.glob("triade-*.service")) + sorted(source.glob("triade-*.timer"))
    for unit in units:
        destination = target / unit.name
        print(f"{'COPY' if args.apply else 'WOULD_COPY'} {unit} -> {destination}")
        if args.apply:
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(unit, destination)
    if not args.apply:
        print("dry-run: use --apply explicitly; daemon-reload/enable/start remain manual")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
