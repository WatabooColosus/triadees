"""Un contrato tiene que poder ser falso, o no es un contrato: es una excusa.

Esta capa es la que decide qué inactividad deja de contar como deuda, así que es
exactamente donde más barato sale hacer trampa: bastaría con una lista de nombres
disfrazada. Lo que lo impide no es la buena voluntad de quien escriba el YAML,
son estas pruebas.

Las tres que importan:

- una declaración **sin evidencia** no carga (sería una exclusión por nombre);
- una evidencia que deja de cumplirse devuelve el sujeto a `REAL_BROKEN`, y dice
  cuál se cayó;
- clasificar **no baja** el total observado: lo que se separa sigue contándose
  aparte, a la vista.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.observability.activation_contracts import (
    CLASSIFICATIONS,
    Contract,
    ContractVerifier,
    _contract,
    load_contracts,
)

ROOT = Path(__file__).resolve().parents[1]


def _declarar(subject: str, classification: str, evidence: tuple[str, ...]) -> Contract:
    return _contract(
        subject,
        classification,
        decided_at="2026-08-08",
        reason="declaración de prueba",
        evidence=evidence,
    )


# --- Lo que no llega ni a cargarse -------------------------------------------


def test_un_contrato_sin_evidencia_no_carga(tmp_path: Path) -> None:
    """Es la trampa que esta capa viene a impedir, así que falla al leer.

    Sin evidencia, «esto no es deuda» es una afirmación sobre un nombre. Con
    evidencia es una afirmación sobre la estructura, y por tanto comprobable.
    """
    with pytest.raises(ValueError, match="exclusión por nombre"):
        _declarar("table:lo_que_sea", "HUMAN_GATED", ())


def test_una_clasificacion_inventada_no_carga(tmp_path: Path) -> None:
    """El vocabulario de clasificaciones es cerrado y está declarado."""
    with pytest.raises(ValueError, match="clasificación desconocida"):
        _declarar("table:t", "NO_ES_DEUDA_PORQUE_YO_LO_DIGO", ("rows_present=t",))


def test_deuda_real_no_se_puede_declarar() -> None:
    """No es una categoría que se pida: es lo que queda cuando ninguna se sostiene."""
    assert "REAL_BROKEN" not in CLASSIFICATIONS
    assert set(CLASSIFICATIONS) | {"REAL_BROKEN"} == {
        "REAL_BROKEN",
        "EXPECTED_EMPTY",
        "ON_DEMAND",
        "HUMAN_GATED",
        "FUTURE_DECLARED",
        "LEGACY_RETIRE",
        "MANUAL_TOOL",
        "TEST_ONLY",
    }


# --- Falsabilidad: la propiedad que sostiene todo lo demás --------------------


def test_si_desaparece_el_gate_el_sujeto_vuelve_al_contador(tmp_path: Path) -> None:
    """La prueba central. Borrar el gate declarado devuelve la tabla a deuda.

    Sin esto, un contrato sería una exención permanente: se escribe una vez
    cuando la cadena existe y sobrevive a que alguien la desmonte. Con esto, el
    contrato es una afirmación que el detector vuelve a comprobar cada vez.
    """
    gate = tmp_path / "store.py"
    gate.write_text(
        "TABLA = 'propuestas'\ndef approve(approved_by: str) -> None: ...\n",
        encoding="utf-8",
    )
    contrato = _declarar(
        "table:propuestas", "HUMAN_GATED", ("human_gate=store.py::approve",)
    )
    verificador = ContractVerifier(tmp_path, reachable={"store.py"})

    assert verificador.verify(contrato).holds

    # Alguien retira el gate: la firma humana ya no gobierna nada.
    gate.write_text("TABLA = 'propuestas'\n", encoding="utf-8")
    otro = ContractVerifier(tmp_path, reachable={"store.py"})
    veredicto = otro.verify(contrato)

    assert not veredicto.holds
    assert veredicto.to_dict()["classification"] == "REAL_BROKEN"
    assert veredicto.failed == ("human_gate=store.py::approve",)


def test_un_escritor_que_deja_de_ser_alcanzable_rompe_el_contrato(
    tmp_path: Path,
) -> None:
    """«Hay escritor» es una frase sobre ficheros; «lo ejecuta algo», sobre el sistema.

    Es la distinción que costó las auditorías de agosto: módulos con importadores
    que a su vez no ejecutaba nadie.
    """
    (tmp_path / "writer.py").write_text(
        "SQL = 'INSERT INTO propuestas VALUES (?)'\n", encoding="utf-8"
    )
    contrato = _declarar(
        "table:propuestas", "ON_DEMAND", ("writer_reachable=writer.py",)
    )

    assert ContractVerifier(tmp_path, reachable={"writer.py"}).verify(contrato).holds
    assert not ContractVerifier(tmp_path, reachable=set()).verify(contrato).holds


def test_aparecer_filas_rompe_un_contrato_que_las_negaba(tmp_path: Path) -> None:
    """`rows_absent` es una afirmación sobre la base viva, y caduca sola.

    Si una capacidad que se declaró «todavía no ha ocurrido» empieza a ocurrir,
    el contrato deja de describir la realidad y hay que volver a mirarla.
    """
    db = tmp_path / "triade.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE propuestas (id INTEGER)")
    contrato = _declarar("table:propuestas", "HUMAN_GATED", ("rows_absent=propuestas",))

    assert ContractVerifier(tmp_path, db_path=db).verify(contrato).holds

    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO propuestas VALUES (1)")

    assert not ContractVerifier(tmp_path, db_path=db).verify(contrato).holds


def test_una_bitacora_que_empieza_a_mutarse_deja_de_serlo(tmp_path: Path) -> None:
    """`append_only` se comprueba, no se promete.

    Lo que distingue una bitácora de una tabla de estado que nadie lee es que a
    la bitácora sólo se le añade. En cuanto aparece un `UPDATE`, es otra cosa.
    """
    writer = tmp_path / "ledger.py"
    writer.write_text("SQL = 'INSERT INTO actas VALUES (?)'\n", encoding="utf-8")
    contrato = _declarar("table:actas", "ON_DEMAND", ("append_only=ledger.py",))

    assert ContractVerifier(tmp_path).verify(contrato).holds

    writer.write_text(
        "SQL = 'INSERT INTO actas VALUES (?)'\nFIX = 'UPDATE actas SET x=1'\n",
        encoding="utf-8",
    )

    assert not ContractVerifier(tmp_path).verify(contrato).holds


# --- Nada se esconde ----------------------------------------------------------


def test_clasificar_no_baja_el_total_observado() -> None:
    """El contador principal separa; no tapa.

    Un informe que bajara su cifra al clasificar sería indistinguible de uno que
    esconde categorías, que es justo lo que este repositorio ya sufrió cuando
    tres tablas salieron del recuento **por degradación** al perder su escritor.
    """
    from triade.observability.introspection import build_debt_report

    informe = build_debt_report(
        ROOT,
        ROOT / "triade/memory/triade.db",
        ROOT / "artifacts/internal_graphs",
        max_age_seconds=float("inf"),
        allow_build=False,
    )
    if informe["status"] != "measured":
        pytest.skip("no hay grafos generados en este entorno")

    observado = sum(entry["count"] for entry in informe["items"].values())
    clasificados = sum(
        len(entry.get("classified", {})) for entry in informe["items"].values()
    )

    assert informe["debt_items_total"] == observado
    assert informe["debt_real_total"] == observado - clasificados
    assert informe["by_classification"].get("REAL_BROKEN") == informe["debt_real_total"]


# --- El fichero real ----------------------------------------------------------


def test_todos_los_contratos_declarados_son_validos_hoy() -> None:
    """Un contrato que miente es peor que no tenerlo: da permiso sin evidencia.

    Esto convierte las declaraciones en código verificado. Si alguien nombra un
    gate que no existe, un escritor que ningún entrypoint alcanza o una prueba
    borrada, CI lo dice aquí y no seis semanas después, cuando alguien se
    pregunte por qué una tabla rota no aparecía en el panel.

    **Sólo la evidencia estructural.** En CI no hay base de producción, ni debe
    haberla: una CI que dependiera de la memoria de producción mediría otra cosa
    cada día, y la primera vez que alguien aprobara una propuesta de mejora se
    pondría roja sin que nada estuviera mal.

    La consecuencia hay que decirla en voz alta: un contrato que mintiera sobre
    filas pasaría por aquí. Lo caza el detector, que reverifica **todo** sobre la
    base real en cada medición y devuelve el sujeto a `REAL_BROKEN` si falla. Aquí
    se comprueba que el contrato es *válido*; allí, que además es *cierto*.
    """
    contratos = load_contracts()
    assert contratos, "no hay ningún contrato declarado"

    verificador = ContractVerifier(ROOT)
    rotos = {
        nombre: verificador.verify(contrato, structural_only=True).failed
        for nombre, contrato in contratos.items()
        if not verificador.verify(contrato, structural_only=True).holds
    }

    assert not rotos, f"contratos declarados que no se sostienen: {rotos}"


def test_la_evidencia_de_runtime_no_se_comprueba_sin_base() -> None:
    """El límite de la prueba anterior, escrito para que no se olvide.

    Si `structural_only` comprobara también las filas, este gate sería imposible
    de pasar en CI; si no existiera la distinción, alguien lo habría desactivado.
    """
    from triade.observability.activation_contracts import (
        RUNTIME_EVIDENCE,
        STRUCTURAL_EVIDENCE,
    )

    assert not set(RUNTIME_EVIDENCE) & set(STRUCTURAL_EVIDENCE)
    contrato = _declarar(
        "table:inventada", "ON_DEMAND", ("rows_present=no_existe_esta_tabla",)
    )
    verificador = ContractVerifier(ROOT)

    # Sin base: no se afirma nada, así que no se acusa.
    assert verificador.verify(contrato, structural_only=True).holds
    # Con base: la evidencia se comprueba y no se sostiene.
    assert not verificador.verify(contrato).holds


# ── §16/§17: una retirada completada no es deuda ────────────────────────────


def test_una_tabla_retirada_satisface_rows_absent(tmp_path):
    """`_rows()` devolvía `None` tanto si la tabla faltaba como si no se pudo mirar.

    Medido el 2026-08-26: `table:goals` figuraba como contrato incumplido
    —`failed=('rows_absent=goals',)`— cuando la migración `036_retire_goals.sql`
    ya se había aplicado y la tabla no existía. La retirada estaba hecha y el
    detector la seguía contando como rotura: una tabla que no existe no tiene
    filas, que es exactamente lo que `LEGACY_RETIRE` persigue.
    """
    import sqlite3

    from triade.observability.activation_contracts import ContractVerifier

    db = tmp_path / "triade.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE viva (id TEXT)")

    verificador = ContractVerifier(ROOT, db_path=db)
    assert verificador._sin_filas("retirada") is True, "tabla ausente = sin filas"
    assert verificador._sin_filas("viva") is True, "tabla vacía = sin filas"

    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO viva VALUES ('x')")
    assert verificador._sin_filas("viva") is False


def test_sin_base_no_se_afirma_ausencia(tmp_path):
    """No poder mirar no autoriza a concluir. Es la mitad que faltaba.

    Sin esta distinción, arreglar el caso de la tabla retirada habría hecho que
    cualquier contrato `rows_absent` se diera por bueno en CI, donde no hay base.
    """
    from triade.observability.activation_contracts import ContractVerifier

    verificador = ContractVerifier(ROOT, db_path=tmp_path / "no-existe.db")
    assert verificador._sin_filas("lo_que_sea") is False


def test_todos_los_contratos_declarados_se_sostienen_en_la_base_viva():
    """Un contrato que explica un vacío inexistente no es evidencia de nada.

    Cuatro declaraban `rows_absent` sobre tablas que ya producían —`auto_identity`
    con 106 filas, y las tres de automejora—. Pasar a `rows_present` no relaja
    nada: es una afirmación más falsable, porque se cae sola si dejan de escribirse.
    """
    from triade.observability.activation_contracts import (
        ContractVerifier,
        load_contracts,
    )

    # Absoluta desde `ROOT`: con ruta relativa el test se saltaba en silencio
    # según desde dónde se invocara pytest, que es la peor forma de no probar.
    db = ROOT / "triade" / "memory" / "triade.db"
    if not db.is_file():
        import pytest

        pytest.skip("sin base viva: la evidencia de runtime no se puede comprobar")

    contratos = load_contracts()
    verificador = ContractVerifier(ROOT, db_path=db)
    caidos = {
        sujeto: verificador.verify(contrato).failed
        for sujeto, contrato in contratos.items()
        if not verificador.verify(contrato).holds
    }
    assert not caidos, f"contratos que dejaron de sostenerse: {caidos}"
