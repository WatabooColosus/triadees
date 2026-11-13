"""Small, versioned held-out corpus for local functional regression."""

from __future__ import annotations

from dataclasses import dataclass

RUBRIC_VERSION = "local-corpus-1"


@dataclass(frozen=True, slots=True)
class LocalCase:
    case_id: str
    domain: str
    question: str
    expected: str
    negative_control: str


CASES: tuple[LocalCase, ...] = (
    LocalCase("python-len", "python_text", "¿Cuánto es len([1,2,3])?", "3", "4"),
    LocalCase("python-floor", "python_text", "¿Cuánto es 9 // 2?", "4", "5"),
    LocalCase("visual-red", "visual_text", "Código hexadecimal de rojo puro.", "#ff0000", "#00ff00"),
    LocalCase("visual-contrast", "visual_text", "Texto con más contraste sobre blanco.", "negro", "blanco"),
    LocalCase("android-devices", "android_cli_text", "Comando para listar dispositivos ADB.", "adb devices", "adb list"),
)

CASES_BY_ID = {case.case_id: case for case in CASES}


def get_case(case_id: str) -> LocalCase:
    try:
        return CASES_BY_ID[case_id]
    except KeyError as exc:
        raise ValueError(f"Caso local desconocido: {case_id}") from exc


def evaluate(case_id: str, answer: str) -> dict[str, object]:
    case = get_case(case_id)
    observed = " ".join(str(answer).strip().lower().split())
    expected = " ".join(case.expected.lower().split())
    return {
        "case_id": case.case_id,
        "domain": case.domain,
        "score": 1.0 if observed == expected else 0.0,
        "pass": observed == expected,
        "rubric_version": RUBRIC_VERSION,
    }
