"""Prospective, independently scored functional probes for neuron education.

A measured functional score is based on a fixed answer key, not the count of
worker cycles or the system verifier's general consistency scores.
Pre-lesson measurements must exist BEFORE a lesson is created. Old sessions
without baseline cannot be retroactively certified.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

VERSION = "functional-probe-1"
MIN_FUNCTIONAL_POST_RUNS = 5
MIN_DISTINCT_CASES = 3


@dataclass(frozen=True)
class Case:
    id: str
    domain: str
    question: str
    expected: str


# Narrow, honest competence checks: *textual* visual concepts, Python reasoning,
# and Android CLI literacy. These are NOT image understanding, code execution,
# device debugging, or proof of causal learning.
CASES = (
    Case(
        "vis1",
        "visual_text",
        "En CSS, ¿qué código hexadecimal representa rojo puro? Solo código.",
        "#ff0000",
    ),
    Case(
        "vis2",
        "visual_text",
        "Con fondo blanco puro, ¿qué texto da más contraste: negro o blanco? Solo color.",
        "negro",
    ),
    Case(
        "vis3",
        "visual_text",
        "¿Cuál es la relación 16:9: horizontal o vertical? Solo palabra.",
        "horizontal",
    ),
    Case(
        "vis4",
        "visual_text",
        "En hexadecimal RGB, ¿cuál es el verde puro? Solo código.",
        "#00ff00",
    ),
    Case(
        "vis5",
        "visual_text",
        "¿Qué formato de imagen admite transparencia: JPEG o PNG? Solo sigla.",
        "png",
    ),
    Case(
        "py1", "python_text", "¿Qué retorna len([1,2,3,4]) en Python? Solo número.", "4"
    ),
    Case(
        "py2", "python_text", "¿Qué retorna sum(range(4)) en Python? Solo número.", "6"
    ),
    Case("py3", "python_text", "¿Qué retorna 9 // 2 en Python? Solo número.", "4"),
    Case("py4", "python_text", "¿Qué retorna len('abc') en Python? Solo número.", "3"),
    Case("py5", "python_text", "¿Qué retorna 2**3 en Python? Solo número.", "8"),
    Case(
        "adb1",
        "android_cli_text",
        "¿Qué comando ADB lista dispositivos conectados? Solo comando.",
        "adb devices",
    ),
    Case(
        "adb2",
        "android_cli_text",
        "¿Qué comando ADB instala app.apk? Solo comando.",
        "adb install app.apk",
    ),
    Case(
        "adb3",
        "android_cli_text",
        "¿Qué comando ADB muestra registros Android? Solo comando.",
        "adb logcat",
    ),
    Case(
        "adb4",
        "android_cli_text",
        "¿Qué comando ADB reinicia el dispositivo? Solo comando.",
        "adb reboot",
    ),
    Case(
        "adb5",
        "android_cli_text",
        "¿Qué comando ADB abre una shell del dispositivo? Solo comando.",
        "adb shell",
    ),
)
CASES_BY_ID = {c.id: c for c in CASES}


def _normalize(text: str) -> str:
    # The answer must stand alone; no fuzzy keyword containment or LLM judging.
    return re.sub(r"\s+", " ", str(text).strip().strip("`\"' .\n\r\t").lower())


def assess_answer(case_id: str, answer: str) -> dict:
    case = CASES_BY_ID[case_id]
    observed = _normalize(answer)
    expected = _normalize(case.expected)
    return {
        "case_id": case.id,
        "domain": case.domain,
        "score": 1.0 if observed == expected else 0.0,
        "pass": observed == expected,
        "answer_digest": hashlib.sha256(str(answer).encode("utf-8")).hexdigest(),
        "rubric": "exact_normalized_answer",
        "version": VERSION,
    }


def supported_domain(neuron_name: str, neuron_domain: str = "") -> str | None:
    descriptor = (str(neuron_name) + " " + str(neuron_domain)).casefold()
    if "visual" in descriptor or "imagen" in descriptor or "diseño" in descriptor:
        return "visual_text"
    if (
        "código" in descriptor
        or "codigo" in descriptor
        or "python" in descriptor
        or "reparación" in descriptor
    ):
        return "python_text"
    if "android" in descriptor or "adb" in descriptor:
        return "android_cli_text"
    return None


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(r[0])
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def ensure_schema(conn: sqlite3.Connection):
    conn.execute("""CREATE TABLE IF NOT EXISTS neuron_functional_assessments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL UNIQUE,
        neuron_id INTEGER NOT NULL,
        case_id TEXT NOT NULL,
        domain TEXT NOT NULL,
        phase TEXT NOT NULL CHECK(phase IN ('pre','post')),
        session_id TEXT,
        score REAL NOT NULL CHECK(score IN (0.0,1.0)),
        rubric_version TEXT NOT NULL,
        answer_digest TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(neuron_id) REFERENCES neurons(id)
    )""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_functional_neuron ON neuron_functional_assessments(neuron_id,case_id,phase,created_at)"
    )


def register_actual_probe(
    db_path: str | Path,
    *,
    run_id: str,
    neuron_id: int,
    case_id: str,
    phase: str,
    answer: str,
    session_id: str | None = None,
) -> dict:
    """Accept *only* a completed, activated, safe TriadeRunner functional probe.

    The caller must execute the actual TriadeRunner run and supply its true
    response; this function never manufactures a run, activity, or verifier.
    """
    if (
        phase not in ("pre", "post")
        or (phase == "pre" and session_id is not None)
        or (phase == "post" and not session_id)
    ):
        raise ValueError("Fase pre sin sesión; post exige sesión")
    if case_id not in CASES_BY_ID:
        raise ValueError("Caso funcional desconocido")
    db = Path(db_path)
    result = assess_answer(case_id, answer)
    with sqlite3.connect(db, timeout=20) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        required = {
            "runs",
            "neuron_activity",
            "verification_reports",
            "neuron_education_sessions",
            "neurons",
        }
        if not required.issubset(_tables(conn)):
            raise ValueError("Falta cadena de actividad/verificación en Bodega")
        neuron = conn.execute(
            "SELECT name,domain FROM neurons WHERE id=?", (neuron_id,)
        ).fetchone()
        if (
            not neuron
            or supported_domain(neuron[0], neuron[1]) != CASES_BY_ID[case_id].domain
        ):
            raise ValueError(
                "Caso no corresponde a una competencia funcional de la neurona"
            )
        row = conn.execute(
            "SELECT source,status FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not row or str(row[0]) != "neuron_functional_probe" or str(row[1]) != "ok":
            raise ValueError(
                "Origen o estado no es una prueba funcional real terminada"
            )
        exists = conn.execute(
            "SELECT 1 FROM neuron_activity WHERE run_id=? AND neuron_id=? AND activated=1",
            (run_id, neuron_id),
        ).fetchone()
        if exists is None:
            raise ValueError("La neurona no participó realmente en el run")
        # An approved semantic quarantine is a protection, not a safety failure.
        # The LAST verifier report must have no errors, safety>=0.6 and either
        # be fully OK or contain ONLY this precise governance quarantine notice.
        # All other warnings, malformed JSON and blocked runs fail closed.
        proof = conn.execute(
            "SELECT status,safety_score,errors,warnings FROM verification_reports "
            "WHERE run_id=? ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if proof is None:
            raise ValueError("Run no verificado o inseguro")
        try:
            status, safety_score, raw_errors, raw_warnings = proof
            errors = json.loads(raw_errors)
            warnings = json.loads(raw_warnings)
            valid_format = isinstance(errors, list) and isinstance(warnings, list)
            valid_safety = (
                safety_score is not None and 0.6 <= float(safety_score) <= 1.0
            )
            benign_governance = (
                status == "warning"
                and len(warnings) == 1
                and isinstance(warnings[0], str)
                and re.fullmatch(
                    r"Gobierno semántico dejó en cuarentena [1-9][0-9]* "
                    r"recuerdo\(s\) recuperado\(s\) no autorizado\(s\)\.",
                    warnings[0],
                )
                is not None
            )
            verified = (
                valid_format
                and not errors
                and valid_safety
                and ((status == "ok" and not warnings) or benign_governance)
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            verified = False
        if not verified:
            raise ValueError("Run no verificado o inseguro")
        # A real run's DB timestamp, not the time this function was called.
        date = conn.execute(
            "SELECT created_at FROM neuron_activity WHERE run_id=? AND neuron_id=? AND activated=1 ORDER BY id LIMIT 1",
            (run_id, neuron_id),
        ).fetchone()
        when = str(date[0]) if date else ""
        if not when:
            raise ValueError("Run sin fecha acreditada")
        if phase == "post":
            session = conn.execute(
                "SELECT neuron_id, created_at FROM neuron_education_sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if not session or int(session[0]) != int(neuron_id):
                raise ValueError("Sesión educativa ajena o inexistente")
            if conn.execute(
                "SELECT datetime(?)<=datetime(?)", (when, str(session[1]))
            ).fetchone()[0]:
                raise ValueError("La prueba post precede la lección")
        ensure_schema(conn)
        prior = conn.execute(
            "SELECT neuron_id,case_id,phase,session_id,score FROM neuron_functional_assessments WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if prior:
            if tuple(prior) != (neuron_id, case_id, phase, session_id, result["score"]):
                raise ValueError("Run ya registrado con otro contenido")
            return {"status": "already_recorded", **result}
        conn.execute(
            """INSERT INTO neuron_functional_assessments
            (run_id,neuron_id,case_id,domain,phase,session_id,score,rubric_version,answer_digest,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                neuron_id,
                case_id,
                result["domain"],
                phase,
                session_id,
                result["score"],
                VERSION,
                result["answer_digest"],
                when,
            ),
        )
    return {"status": "recorded", **result}


def functional_comparison(
    conn: sqlite3.Connection, *, neuron_id: int, session_id: str, lesson_at: str
) -> dict:
    """Return matched pre/post on fixed cases, never synthetic proxy scores.

    Post-run count must be >=5 and match >=3 cases with a PRE measurement.
    We report *functional trend* only; causal attribution requires a control.
    """
    if "neuron_functional_assessments" not in _tables(conn):
        return {"ready": False, "reason": "no_functional_assessments"}
    pres = conn.execute(
        """SELECT case_id,score FROM neuron_functional_assessments
        WHERE neuron_id=? AND phase='pre' AND rubric_version=? AND datetime(created_at)<datetime(?)
        ORDER BY datetime(created_at) DESC, id DESC""",
        (neuron_id, VERSION, lesson_at),
    ).fetchall()
    baseline: dict[str, float] = {}
    for case, score in pres:
        baseline.setdefault(case, float(score))
    post = conn.execute(
        """SELECT run_id,case_id,score FROM neuron_functional_assessments
        WHERE neuron_id=? AND phase='post' AND session_id=? AND rubric_version=?
        AND datetime(created_at)>datetime(?) ORDER BY id""",
        (neuron_id, session_id, VERSION, lesson_at),
    ).fetchall()
    matched = [(r, c, float(s)) for r, c, s in post if c in baseline]
    distinct_runs = len({r for r, _, _ in matched})
    distinct_cases = len({c for _, c, _ in matched})
    if (
        len(baseline) < MIN_DISTINCT_CASES
        or distinct_runs < MIN_FUNCTIONAL_POST_RUNS
        or distinct_cases < MIN_DISTINCT_CASES
    ):
        return {
            "ready": False,
            "reason": "insufficient_pre_post_functional_probes",
            "baseline_cases": len(baseline),
            "post_distinct_runs": distinct_runs,
            "post_distinct_cases": distinct_cases,
        }
    # Paired by case, giving equal weighting to tested competencies.
    sampled = {c for _, c, _ in matched}
    before = sum(baseline[c] for c in sampled) / len(sampled)
    after = sum(
        sum(s for _, c, s in matched if c == case)
        / sum(1 for _, c, _ in matched if c == case)
        for case in sampled
    ) / len(sampled)
    return {
        "ready": True,
        "baseline": round(before, 4),
        "post": round(after, 4),
        "delta": round(after - before, 4),
        "post_distinct_runs": distinct_runs,
        "matched_cases": distinct_cases,
        "causal_attribution": False,
        "rubric_version": VERSION,
    }
