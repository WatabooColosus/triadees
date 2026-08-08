"""La documentación es representación derivada; el código es la fuente.

Regla del proyecto: **código + tests + runtime + base = fuente primaria;
documentación = representación derivada y verificable**. Nunca al revés.

Este módulo la hace exigible en CI. No valida prosa —eso no se puede— sino las
afirmaciones comprobables: si un documento nombra un fichero, un módulo o un
comando, tiene que existir. Un documento que cita lo que ya no está no es
documentación desactualizada: es documentación falsa, y se lee igual que la
buena.

Empezó como un gate mínimo a propósito. Añadir comprobaciones aquí es barato;
lo caro es descubrir que `main` lleva semanas con código nuevo y docs viejas.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Documentos que describen el estado **actual**. Los históricos se excluyen a
#: propósito: pueden citar lo que existía entonces, y esa es su función.
_HISTORICOS = {
    "AUDIT_REPORT.md",
    "AUDIT_FIXES.md",
    "PR9_AUDIT_REPORT.md",
    "T001_SPEC.md",
    "RELEASE_LOCAL_1_0.md",
    "PLAN.md",
    "ROADMAP.md",
}


#: Drift **conocido y pendiente de reparar**, no perdonado. Cada par es una
#: afirmación falsa que hoy vive en `main`: el documento cita un módulo que se
#: borró en `93496c8` (31 módulos sin importador) o en `aa001f3` (consolidación
#: de las superficies FastAPI en `single_port_app`).
#:
#: Está aquí y no excluido en silencio para que se vea y se cierre: quitar una
#: línea de esta lista es la definición de «arreglar ese documento». Lo que el
#: gate impide desde ya es que la lista **crezca**.
_DRIFT_CONOCIDO = {
    ("ARCHITECTURE_MAP.md", "triade/federation/merge.py"),
    ("ARCHITECTURE_MAP.md", "apps/api_app.py"),
    ("ARCHITECTURE_MAP.md", "apps/chat_ui_app.py"),
    ("ARCHITECTURE_MAP.md", "apps/chat_ui_router_app.py"),
    ("ARCHITECTURE_MAP.md", "apps/ui_html.py"),
    ("ARCHITECTURE_MAP.md", "apps/model_router_api.py"),
    ("TECHNICAL_DEBT.md", "triade/sandbox/secure_executor_v2.py"),
    ("TECHNICAL_DEBT.md", "triade/workers/state_machine.py"),
    ("TECHNICAL_DEBT.md", "triade/workers/lease_retry_breaker.py"),
    ("TECHNICAL_DEBT.md", "triade/federation/merge.py"),
}

#: Módulos retirados con copia y verificación el 2026-08-08. La comprobación de
#: existencia los ignora **a propósito**: quien gobierna si pueden nombrarse es
#: `test_no_se_documentan_modulos_retirados`, que exige que el texto explique la
#: retirada. Un concepto, un dueño — dos tests peleándose por el mismo hecho es
#: como se pierden los contratos en este repositorio.
_RETIRADOS = (
    "triade/core/plan_step.py",
    "triade/core/hierarchical_pulse.py",
    # El contrato de certificación por manifiesto firmado, sustituido por
    # `stable_neuron_audit`, que juzga sobre evidencia medida.
    "triade/neuron_factory/certification.py",
    "scripts/run_phase_12_neuron_certification.py",
    "tests/test_neuron_certification.py",
)

#: Un documento se declara histórico con esta marca en su propio texto. No se
#: excluye por ruta: quien escribe decide, y queda escrito en el documento.
_MARCA_HISTORICA = "<!-- HISTORICO -->"


def _es_historico(doc: Path, texto: str) -> bool:
    return _MARCA_HISTORICA in texto


def _docs_actuales() -> list[Path]:
    rutas = [p for p in REPO_ROOT.glob("*.md") if p.name not in _HISTORICOS]
    rutas += [p for p in (REPO_ROOT / "docs").rglob("*.md") if "audits" not in p.parts]
    return sorted(
        p for p in rutas if not _es_historico(p, p.read_text(encoding="utf-8"))
    )


def test_los_ficheros_citados_existen() -> None:
    """Citar un fichero que ya no está es afirmar algo falso sobre el sistema."""
    ausentes: list[str] = []
    patron = re.compile(
        r"`((?:triade|apps|scripts|tests|docs)/[\w./-]+\.(?:py|sh|md))`"
    )
    for doc in _docs_actuales():
        for ruta in patron.findall(doc.read_text(encoding="utf-8")):
            nombre = str(doc.relative_to(REPO_ROOT))
            if (nombre, ruta) in _DRIFT_CONOCIDO or ruta in _RETIRADOS:
                continue
            if not (REPO_ROOT / ruta).exists():
                ausentes.append(f"{nombre} → {ruta}")

    assert not ausentes, "documentación que cita ficheros inexistentes:\n" + "\n".join(
        ausentes
    )


def test_no_se_documentan_modulos_retirados() -> None:
    """Lo retirado no puede seguir descrito como si estuviera vivo.

    `plan_step.py` y `hierarchical_pulse.py` se retiraron el 2026-08-08 con
    copia y verificación. Si un documento vuelve a presentarlos como parte del
    sistema, o bien alguien los revivió sin decirlo, o bien la documentación
    quedó atrás.
    """
    vivos: list[str] = []
    for doc in _docs_actuales():
        texto = doc.read_text(encoding="utf-8")
        for modulo in _RETIRADOS:
            # Mencionarlo explicando que se retiró es correcto; presentarlo
            # como existente, no. La marca es que el propio texto lo diga.
            if (
                modulo in texto
                and not (REPO_ROOT / modulo).exists()
                and not re.search(r"retirad|archivad|elimina", texto, re.IGNORECASE)
            ):
                vivos.append(f"{doc.relative_to(REPO_ROOT)} → {modulo}")

    assert not vivos, "documentación que presenta módulos retirados:\n" + "\n".join(
        vivos
    )


def test_claude_no_figura_como_parte_de_triade() -> None:
    """Claude es herramienta externa de desarrollo, no un órgano.

    El supervisor se retiró en el PR #79. Que vuelva a aparecer como agente,
    neurona o autoridad dentro de la arquitectura es una regresión de diseño, no
    un descuido de redacción.
    """
    prohibido = re.compile(
        r"claude\s+(?:es|como)\s+(?:un[ao]?\s+)?"
        r"(?:supervisor|agente|neurona|autoridad|parte)",
        re.IGNORECASE,
    )
    apariciones = [
        f"{doc.relative_to(REPO_ROOT)}: {m.group(0)}"
        for doc in _docs_actuales()
        for m in prohibido.finditer(doc.read_text(encoding="utf-8"))
    ]

    assert not apariciones, "Claude presentado dentro de Tríade:\n" + "\n".join(
        apariciones
    )
