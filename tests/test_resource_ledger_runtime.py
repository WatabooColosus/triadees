from triade.runtime.resource_ledger import (
    DEFAULT_BUDGET,
    ResourceLedger,
    load_runtime_budget,
)


def _gastar(ledger, task_class, veces):
    for i in range(veces):
        ledger.record(
            task_id=f"{task_class}-{i}",
            worker_id="w",
            success=True,
            task_class=task_class,
        )


def test_ledger_aggregates_and_degrades_at_thresholds(tmp_path):
    ledger = ResourceLedger(tmp_path / "ledger.db", {"cpu_minutes_daily": 1})
    ledger.record(task_id="t", worker_id="w", cpu_seconds=43, success=True)
    assert ledger.policy()["mode"] == "cost_reduced"
    assert ledger.allows("deep_evaluation") is False
    ledger.record(task_id="t2", worker_id="w", cpu_seconds=18, success=True)
    policy = ledger.policy()
    assert policy["mode"] == "observe_only"
    assert policy["allowed_classes"] == ["heartbeat", "maintenance", "safety"]


def test_ledger_records_all_resource_dimensions(tmp_path):
    ledger = ResourceLedger(tmp_path / "ledger.db")
    entry = ledger.record(
        task_id="t",
        worker_id="w",
        neuron_id="n",
        cpu_seconds=2,
        gpu_seconds=3,
        ram_peak_mb=10,
        vram_peak_mb=11,
        tokens_input=12,
        tokens_output=13,
        network_bytes=14,
        disk_bytes_read=15,
        disk_bytes_written=16,
        duration_seconds=17,
        model="local",
        estimated_energy_wh=18,
        temperature_peak_c=45,
        success=False,
        task_class="research",
    )
    assert entry > 0
    usage = ledger.daily_usage()
    assert usage["research_tasks_daily"] == 1
    assert usage["gpu_minutes_daily"] == 3 / 60


def test_declared_quota_is_spendable_to_its_limit(tmp_path):
    """El límite declarado tiene que ser alcanzable, no un techo teórico.

    Antes la clase se prohibía a sí misma al 70 % de su propia línea: con
    `deep_evaluations_daily=12` el organismo hacía 9 y se paraba. La base tiene
    tres días seguidos con exactamente 9 `stable_consolidation_review`.
    """
    ledger = ResourceLedger(tmp_path / "ledger.db", {"deep_evaluations_daily": 12})
    for gastadas in range(12):
        assert ledger.allows("deep_evaluation") is True, (
            f"la clase se bloqueó tras {gastadas} de 12 evaluaciones declaradas"
        )
        _gastar(ledger, "deep_evaluation", 1)
    assert ledger.allows("deep_evaluation") is False
    assert ledger.policy()["exhausted_quotas"] == ["deep_evaluation"]


def test_quota_of_one_class_does_not_gate_another(tmp_path):
    """Gastar investigación no puede apagar la evaluación profunda.

    Medido en vivo el 2026-08-10: 32 investigaciones de 40 (0.80) dejaban sin
    revisar a un candidato con evidencia `improved` y tres usos causales cuyo
    propio cupo iba por 9 de 12.
    """
    ledger = ResourceLedger(
        tmp_path / "ledger.db",
        {"research_tasks_daily": 40, "deep_evaluations_daily": 12},
    )
    _gastar(ledger, "research", 32)
    politica = ledger.policy()
    assert politica["quotas"]["research"]["ratio"] == 0.8
    assert politica["mode"] == "normal", "un cupo por clase no es presión física"
    assert ledger.allows("deep_evaluation") is True
    assert ledger.allows("research") is True


def test_exhausted_quota_blocks_only_its_own_class(tmp_path):
    ledger = ResourceLedger(tmp_path / "ledger.db", {"research_tasks_daily": 2})
    _gastar(ledger, "research", 2)
    assert ledger.allows("research") is False
    assert ledger.allows("deep_evaluation") is True
    assert ledger.allows("light") is True
    assert ledger.allows("heartbeat") is True


def test_spending_the_single_install_does_not_stop_the_organism(tmp_path):
    """`model_installs_daily=1`: gastar el permiso presupuestado ponía la razón
    en 1.0 y con ella todo el organismo en `observe_only` hasta medianoche."""
    ledger = ResourceLedger(tmp_path / "ledger.db")
    _gastar(ledger, "model_install", 1)
    politica = ledger.policy()
    assert politica["mode"] == "normal"
    assert ledger.allows("model_install") is False
    assert ledger.allows("deep_evaluation") is True
    assert ledger.allows("research") is True


def test_physical_pressure_still_degrades_every_expensive_class(tmp_path):
    """La escalera sobre recursos compartidos sigue intacta: es escasez real."""
    ledger = ResourceLedger(tmp_path / "ledger.db", {"cpu_minutes_daily": 1})
    ledger.record(task_id="t", worker_id="w", cpu_seconds=43, success=True)
    politica = ledger.policy()
    assert politica["mode"] == "cost_reduced"
    assert politica["exhausted_quotas"] == []
    assert ledger.allows("deep_evaluation") is False
    assert ledger.allows("research") is True


def test_runtime_budget_is_read_from_declared_config(tmp_path):
    """`runtime_budget` llevaba declarado en `triade.yml` sin lector."""
    yml = tmp_path / "triade.yml"
    yml.write_text("runtime_budget:\n  deep_evaluations_daily: 7\n", encoding="utf-8")
    presupuesto = load_runtime_budget(yml)
    assert presupuesto["deep_evaluations_daily"] == 7.0
    assert presupuesto["cpu_minutes_daily"] == DEFAULT_BUDGET["cpu_minutes_daily"]
    assert load_runtime_budget(tmp_path / "no-existe.yml") == DEFAULT_BUDGET


def test_la_cpu_se_mide_por_hilo_no_por_proceso():
    """`RUSAGE_SELF` cuenta todo el proceso, y los workers son hilos.

    Medido el 2026-08-26 en producción: 5.912 de 6.484 entradas del día
    declaraban más CPU que duración —media de 1,65 núcleos aparentes, pico de
    4,7— porque la ventana de cada tarea se quedaba también con la CPU de las
    demás. `cpu_minutes_daily` llegó a 713 sobre un presupuesto de 600 y
    `policy()` puso el organismo en `observe_only`, que excluye la clase
    `light`: la cadena de aprendizaje entera parada por una cifra irreal.

    Con varios hilos quemando CPU a la vez, ninguno puede declarar más de un
    núcleo: bajo el GIL el bucle de Python puro no se paraleliza.
    """
    import threading
    import time

    from triade.runtime.resource_ledger import ResourceMeasurementCollector

    medidas: dict[int, tuple[float, float]] = {}

    def medir(indice: int) -> None:
        collector = ResourceMeasurementCollector()
        fin = time.monotonic() + 0.4
        while time.monotonic() < fin:
            pass
        recibo = collector.finish()
        cpu = recibo.value("cpu_user") + recibo.value("cpu_system")
        medidas[indice] = (cpu, recibo.value("wall_time"))

    hilos = [threading.Thread(target=medir, args=(i,)) for i in range(4)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert len(medidas) == 4
    for indice, (cpu, wall) in medidas.items():
        nucleos = cpu / wall if wall else 0.0
        assert nucleos <= 1.2, (
            f"el hilo {indice} declara {nucleos:.2f} núcleos: está contando"
            " la CPU de los otros hilos"
        )
