"""Runner del ciclo cognitivo mínimo de Tríade Ω."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .bodega import Bodega
from .central import Central
from .contracts import InputPacket
from .crystal import Crystal
from .hypothalamus import Hypothalamus
from .safety import Safety
from .verification import Verifier


class TriadeRunner:
    """Ejecuta el ciclo mínimo: input → señales → memoria → cristal → plan → safety → output → reporte."""

    def __init__(self, runs_dir: str | Path = "runs") -> None:
        self.runs_dir = Path(runs_dir)
        self.hypothalamus = Hypothalamus()
        self.bodega = Bodega()
        self.crystal = Crystal()
        self.central = Central()
        self.safety = Safety()
        self.verifier = Verifier()

    def run(self, user_input: str, source: str = "console") -> dict[str, Any]:
        input_packet = InputPacket(user_input=user_input, source=source)
        run_path = self.runs_dir / input_packet.run_id
        run_path.mkdir(parents=True, exist_ok=True)

        signals = self.hypothalamus.analyze(input_packet)
        memory = self.bodega.recall(input_packet)
        crystal = self.crystal.regulate(signals, memory)
        plan = self.central.plan(input_packet, signals, memory, crystal)
        safety = self.safety.review(signals, plan)

        if safety.status == "blocked":
            response = "La acción fue bloqueada por Safety."
            output = self.central.respond(input_packet, signals, memory, crystal, plan)
            output.response = response
            output.status = "blocked"
        else:
            output = self.central.respond(input_packet, signals, memory, crystal, plan)

        memory_diff = self.bodega.diff_from_output(output)
        output.memory_diff = memory_diff
        report = self.verifier.verify(output, safety)

        artifacts = {
            "input.json": input_packet.to_dict(),
            "signals.json": signals.to_dict(),
            "memory.json": memory.to_dict(),
            "crystal.json": crystal.to_dict(),
            "plan.json": plan.to_dict(),
            "safety.json": safety.to_dict(),
            "output.json": output.to_dict(),
            "memory_diff.json": memory_diff,
            "report.json": report.to_dict(),
        }

        for filename, payload in artifacts.items():
            self._write_json(run_path / filename, payload)

        integrity = {
            "run_id": input_packet.run_id,
            "status": report.status,
            "artifacts": sorted(artifacts.keys()),
            "closed": True,
        }
        self._write_json(run_path / "integrity.json", integrity)
        (run_path / "CLOSED").write_text("closed\n", encoding="utf-8")

        return {
            "run_id": input_packet.run_id,
            "response": output.response,
            "safety": safety.to_dict(),
            "report": report.to_dict(),
            "run_path": str(run_path),
        }

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
