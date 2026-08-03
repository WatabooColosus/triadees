"""Resuelve peticiones accionables contra capacidades ejecutables reales."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class CapabilityResolution:
    actionable: bool
    capability: str
    available: bool
    execution_mode: str
    worker_task_type: str | None
    command_key: str | None
    requires_human_approval: bool
    risk: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


class CapabilityResolver:
    """Clasificador conservador: solo delega órdenes explícitamente accionables."""

    ACTION = re.compile(
        r"\b(haz|haga|crea|crear|construye|construir|repara|reparar|corrige|corregir|"
        r"instala|instalar|descarga|descargar|prueba|probar|ejecuta|ejecutar|"
        r"investiga|investigar|busca|buscar|diagnostica|diagnosticar|audita|auditar|compila|compilar)\b",
        re.IGNORECASE,
    )

    #: Verbos de redacción. `corrige`/`repara` quedan fuera a propósito: son
    #: modificación de código y tienen que seguir cayendo en `repo_modification`,
    #: que exige aprobación humana. Enrutar «corrige el archivo x.py» a la
    #: escritura de texto saltaría esa puerta.
    ESCRITURA = re.compile(
        r"\b(escribe|escribir|redacta|redactar|documenta|documentar|"
        r"anota|anotar|genera|generar|crea|crear)\b",
        re.IGNORECASE,
    )
    #: Sustantivos que nombran un entregable, no una respuesta de chat. Fuera
    #: quedan «resumen», «nota» y «texto» a propósito: «escribe un resumen» se
    #: pide en conversación y contestarlo con un fichero sorprendería. Fuera
    #: también «archivo» y «fichero», porque cualquier `.py` lo es y eso volvería
    #: a cruzarse con la modificación de código.
    ARTEFACTO_TEXTO = re.compile(
        r"\b(documento|informe|reporte|acta|minuta|artefacto)\b",
        re.IGNORECASE,
    )

    def resolve(self, request: str) -> CapabilityResolution:
        text = " ".join(str(request).strip().split())
        low = text.lower()
        if not text:
            return self._none("No es una orden operativa explícita.")

        # La única forma de activar esta capacidad era escribir su identificador
        # interno literal en la petición: `if "write_governed_text_artifact" in
        # low`. Nadie pide nada así, y por eso el tipo de tarea acumulaba cero
        # ejecuciones teniendo handler, política de concurrencia y clave de
        # exclusión. Estaba muerta por construcción, no por falta de código.
        #
        # Va antes de la compuerta `ACTION` en vez de añadir los verbos de
        # redacción a esa lista: ampliarla haría accionables peticiones que hoy
        # son conversación, y todas acabarían en `unsupported_action` creando un
        # goal bloqueado. Esta regla es más estricta que `ACTION`, no más laxa:
        # exige verbo de redacción **y** sustantivo de entregable.
        if "write_governed_text_artifact" in low or (
            self.ESCRITURA.search(low) and self.ARTEFACTO_TEXTO.search(low)
        ):
            return CapabilityResolution(
                True,
                "write_governed_text_artifact",
                True,
                "worker",
                "write_governed_text_artifact",
                None,
                False,
                "low",
                "Escritura de texto limitada a una raíz autorizada y con rollback.",
            )

        if not self.ACTION.search(text):
            return self._none("No es una orden operativa explícita.")

        if re.search(
            r"\b(instala|instalar|descarga|descargar|pip|npm|apt|paquete|dependencia|driver)\b",
            low,
        ):
            return CapabilityResolution(
                True,
                "environment_install",
                False,
                "human_approval",
                None,
                None,
                True,
                "high",
                "Instalar o descargar cambia el entorno y requiere propuesta y aprobación.",
            )
        if re.search(
            r"\b(investiga|investigar|busca|buscar|averigua|fuentes|documentación|documentacion)\b",
            low,
        ):
            return CapabilityResolution(
                True,
                "web_research",
                True,
                "worker",
                "goal_research",
                None,
                False,
                "low",
                "Investigación web gobernada disponible.",
            )
        if re.search(r"\b(prueba|probar|tests?|pytest)\b", low):
            return CapabilityResolution(
                True,
                "test_suite",
                True,
                "worker",
                "goal_safe_command",
                "test_quick",
                False,
                "medium",
                "Suite de pruebas disponible por Safe Shell.",
            )
        if re.search(r"\b(compila|compilar|build|frontend)\b", low):
            return CapabilityResolution(
                True,
                "project_build",
                True,
                "worker",
                "goal_safe_command",
                "frontend_build",
                False,
                "medium",
                "Build gobernado disponible por Safe Shell.",
            )
        if re.search(
            r"\b(diagnostica|diagnosticar|audita|auditar|estado|repositorio)\b", low
        ):
            return CapabilityResolution(
                True,
                "diagnostic",
                True,
                "worker",
                "goal_safe_command",
                "git_status_branch",
                False,
                "low",
                "Diagnóstico de repositorio disponible.",
            )
        if re.search(
            r"\b(repara|reparar|corrige|corregir|crea|crear|construye|construir)\b", low
        ):
            return CapabilityResolution(
                True,
                "repo_modification",
                False,
                "human_approval",
                None,
                None,
                True,
                "high",
                "Modificar código requiere alcance, workspace candidato y aprobación humana.",
            )
        return CapabilityResolution(
            True,
            "unsupported_action",
            False,
            "blocked",
            None,
            None,
            False,
            "medium",
            "No existe todavía un ejecutor gobernado para esta acción.",
        )

    @staticmethod
    def _none(reason: str) -> CapabilityResolution:
        return CapabilityResolution(
            False, "conversation", True, "direct", None, None, False, "low", reason
        )
