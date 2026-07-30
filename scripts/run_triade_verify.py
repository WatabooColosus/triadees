#!/usr/bin/env python3
"""Generate a TRIADE-VERIFY-v1 evidence bundle."""

from __future__ import annotations

import argparse
from pathlib import Path

from triade.verification import TriadeVerifier


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = TriadeVerifier(root).generate(args.output)
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
