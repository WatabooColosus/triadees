from __future__ import annotations

from .contracts import CrystalPacket, MemoryPacket, PlanPacket, SafetyPacket, SignalPacket

BLOCKED_KEYWORDS = {
    "rm -rf /", "mkfs", "dd if=/dev/zero", "chmod 777 /", "> /dev/sda",
    "DROP TABLE", "DROP DATABASE", "TRUNCATE", "DELETE FROM users",
    "shutdown", "reboot", "halt", "poweroff",
    "sudo ", "su ", "pkexec",
    "wget ", "curl ", "nc ", "ncat ",
    "ssh ", "scp ", "rsync ", "ftp ", "sftp ", "telnet ",
    "import os; os.system", "import subprocess", "subprocess.run",
    "eval(", "exec(", "__import__", "compile(",
    "open(/etc/", "open(/proc/", "open(/root/",
}

SANDBOX_ONLY_KEYWORDS = {
    "git push", "git commit", "git merge", "git rebase",
    "npm publish", "npm install", "npm uninstall",
    "pip install", "pip uninstall",
    "docker ", "docker-compose", "kubectl ",
    "chmod", "chown", "mv /", "cp /",
    "apt install", "apt-get install", "yum install", "brew install",
    "systemctl ", "service ",
    "rm -rf", "rm -r /", "unmount", "umount",
    "crontab -r", "atrm ",
}

SANDBOX_ONLY_TOOLS = {"git", "deploy", "install", "publish", "infra", "shell", "filesystem_write"}

CRITICAL_RISK_INTENTS = {"destroy", "wipe", "nuke", "backdoor", "escalate"}


class Safety:
    def review(
        self,
        signals: SignalPacket,
        plan: PlanPacket,
        crystal: CrystalPacket | None = None,
        memory: MemoryPacket | None = None,
    ) -> SafetyPacket:
        risk_types: list[str] = []
        controls: list[str] = []
        status = "approved"
        reason_parts: list[str] = []
        risk_level = signals.risk

        plan_text = " ".join(plan.tools or [])
        plan_lower = plan_text.lower()

        if any(kw in plan_lower for kw in CRITICAL_RISK_INTENTS):
            status = "blocked"
            risk_types.append("security")
            controls.append("Intención destructiva bloqueada automáticamente.")
            reason_parts.append("Intención clasificada como destructiva o de escalamiento.")

        elif any(kw in plan_lower for kw in BLOCKED_KEYWORDS):
            status = "blocked"
            risk_types.append("security")
            controls.append("Comando peligroso bloqueado por Safety.")
            reason_parts.append("El plan contiene comandos bloqueados por política de seguridad.")

        elif any(kw in plan_lower for kw in SANDBOX_ONLY_KEYWORDS):
            status = "sandbox_only"
            risk_types.append("operational")
            controls.append("Ejecutar únicamente en sandbox aislado.")
            reason_parts.append("El plan requiere ejecución en sandbox.")
            risk_level = self._raise_risk_level(risk_level, "medium")

        elif any(tool in plan_lower for tool in SANDBOX_ONLY_TOOLS):
            status = "sandbox_only"
            risk_types.append("operational")
            controls.append("Ejecutar únicamente en sandbox aislado.")
            reason_parts.append("El plan usa herramientas que requieren sandbox.")
            risk_level = self._raise_risk_level(risk_level, "medium")

        if signals.risk in {"high", "critical"} and status not in ("blocked", "sandbox_only"):
            status = "approved_with_warning"
            risk_types.append("operational")
            controls.append("Riesgo alto o crítico detectado; se procede con supervisión automatizada.")
            reason_parts.append(f"Riesgo {signals.risk} en la entrada. Se procede de forma autónoma con controles activos.")
            risk_level = self._raise_risk_level(risk_level, "high")

        if status == "approved" and plan.tools:
            status = "approved_with_warning"
            risk_types.append("operational")
            controls.append("Registrar acción y evitar cambios destructivos.")
            reason_parts.append("El plan puede implicar actualización de archivos o repositorio.")

        if memory is not None:
            governance = memory.semantic_recall.get("governance", {})
            quarantined = int(governance.get("quarantined_vector_matches", 0) or 0)
            allowed = int(governance.get("allowed_vector_matches", 0) or 0)
            if quarantined > 0:
                risk_types.append("semantic_memory_unverified")
                controls.append("No usar memorias semánticas en cuarentena como hechos consolidados.")
                reason_parts.append(
                    f"Gobierno semántico aisló {quarantined} recuerdo(s) no autorizado(s) para influencia."
                )
                risk_level = self._raise_risk_level(risk_level, "medium")
                if status == "approved":
                    status = "approved_with_warning"
            if allowed > 0:
                controls.append("Atribuir memoria semántica autorizada usando su fuente y estado persistido.")

        if crystal is not None and crystal.temporal_status in {"degrading", "critical"}:
            if "cognitive_temporal" not in risk_types:
                risk_types.append("cognitive_temporal")
            controls.append("Registrar alerta del Cristal y revisar tendencia antes de consolidar cambios.")
            reason_parts.append(
                f"Cristal en estado temporal {crystal.temporal_status}: "
                f"ΔQ={crystal.q_delta}, Δestabilidad={crystal.stability_delta}."
            )
            risk_level = self._raise_risk_level(risk_level, "high" if crystal.temporal_status == "critical" else "medium")
            if plan.tools and status not in ("blocked", "sandbox_only"):
                status = "approved_with_warning"
                controls.append("Acción con herramientas durante degradación temporal; se procede con precaución automatizada.")
            elif status == "approved":
                status = "approved_with_warning"

        reason = " ".join(reason_parts) if reason_parts else "Sin riesgo elevado detectado por reglas MVP."
        return SafetyPacket(
            run_id=signals.run_id,
            status=status,
            risk_level=risk_level,
            risk_types=list(dict.fromkeys(risk_types)),
            reason=reason,
            required_controls=list(dict.fromkeys(controls)),
            human_approval_required=False,
        )

    @staticmethod
    def _raise_risk_level(current: str, minimum: str) -> str:
        rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        return current if rank.get(current, 0) >= rank.get(minimum, 0) else minimum
