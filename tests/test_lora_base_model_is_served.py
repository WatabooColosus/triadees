"""Un adaptador que no se puede activar es trabajo tirado antes de empezar.

Medido el 2026-08-27: `GovernedLoraJobRunner` entrenaba por defecto contra
`Qwen/Qwen2.5-0.5B-Instruct` mientras el runtime servía `qwen2.5:3b-instruct`.
`normalize_model_id` reducía la base a `qwen2.50.5binstruct` y **ninguno** de
los cinco modelos servidos reducía a esa clave.

La consecuencia no era un adaptador peor: era que `activate()` lo rechazaba
siempre —correctamente— y el entrenamiento entero se perdía. `goal_lora_train`
y `governed_peft_active_slot` estaban muertos por la misma razón que lo estuvo
el circuito de automejora: no podían empezar.
"""

from __future__ import annotations

from pathlib import Path

from triade.training.governed_lora import (
    GovernedLoraJobRunner,
    default_base_model,
    served_model_labels,
)
from triade.training.serving_governance import normalize_model_id

RAIZ = Path(__file__).resolve().parents[1]
YML = RAIZ / "triade.yml"


def test_la_base_por_defecto_es_un_modelo_realmente_servido():
    """La invariante entera: lo que se entrena tiene que poder activarse."""
    base = default_base_model(YML)
    servidos = served_model_labels(YML)
    assert base, "sin base derivada no se puede entrenar nada activable"
    assert servidos, "sin modelos servidos declarados no hay contra qué comparar"

    clave = normalize_model_id(base)
    assert any(normalize_model_id(m) == clave for m in servidos), (
        f"la base {base!r} (clave {clave!r}) no casa con ninguno de {servidos}"
    )


def test_la_base_sale_del_modelo_que_responde():
    """Se deriva de `models.roles.central`, no de una constante escrita a mano."""
    assert default_base_model(YML) == "Qwen/Qwen2.5-3B-Instruct"


def test_una_base_no_servida_se_bloquea_antes_de_gastar_gpu(tmp_path):
    """El rechazo llegaba al final, tras entrenar. Ahora llega antes.

    Se usa la base vieja a propósito: es exactamente la que estaba puesta por
    defecto y la que nunca podría activarse.
    """
    # Se resuelve igual que el código, no desde `RAIZ`: `governed_lora` compara
    # contra `Path("data/lora").resolve()`, que depende del cwd.
    dataset = Path("data/lora").resolve()
    dataset.mkdir(parents=True, exist_ok=True)
    fichero = dataset / "test-base-no-servida.jsonl"
    fichero.write_text('{"text": "x"}\n', encoding="utf-8")
    try:
        resultado = GovernedLoraJobRunner(tmp_path / "triade.db").run(
            {
                "human_approved": True,
                "approved_by": "test",
                "dataset_path": str(fichero),
                "base_model": "Qwen/Qwen2.5-0.5B-Instruct",
            }
        )
        assert resultado["status"] == "blocked"
        assert resultado["reason"] == "base_model_not_served"
        assert resultado["base_model"] == "Qwen/Qwen2.5-0.5B-Instruct"
    finally:
        fichero.unlink(missing_ok=True)


def test_sin_aprobacion_humana_se_bloquea_antes_que_nada(tmp_path):
    """La compuerta humana sigue siendo la primera. Este arreglo no la mueve."""
    resultado = GovernedLoraJobRunner(tmp_path / "triade.db").run({})
    assert resultado["status"] == "blocked"
    assert resultado["reason"] == "explicit_human_approval_required"
