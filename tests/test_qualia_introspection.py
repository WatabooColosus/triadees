from triade.qualia import NeuronExperience, QualiaIntrospector, QualiaState


def test_introspection_detects_novelty_gap_and_asks_question():
    state = QualiaState(
        run_id="run-intro-1",
        curiosity=0.8,
        confidence=0.4,
        coherence=0.7,
        novelty=0.9,
    )
    experience = NeuronExperience(
        run_id="run-intro-1",
        mission="comprender señal nueva",
        observation="Apareció un patrón no visto antes",
        extracted_pattern="patrón emergente",
        confidence=0.4,
        evidence_refs=["run:intro:1"],
    )

    report = QualiaIntrospector().reflect(
        run_id=state.run_id,
        state=state,
        experiences=[experience],
    )

    assert report.trigger == "novelty"
    assert report.status == "hypothesis"
    assert report.requires_verification is True
    assert "investigate_novelty" in report.recommended_actions
    assert report.self_questions
    assert report.evidence_refs == ["run:intro:1"]


def test_introspection_quarantines_unreferenced_learning():
    state = QualiaState(run_id="run-intro-2", confidence=0.8, coherence=0.8)
    experience = NeuronExperience(
        run_id=state.run_id,
        mission="evaluar conclusión",
        observation="La prueba terminó",
        proposed_learning="Este resultado siempre es correcto",
        evidence_refs=[],
    )

    report = QualiaIntrospector().reflect(
        run_id=state.run_id,
        state=state,
        experiences=[experience],
    )

    assert "quarantine_unreferenced_learning" in report.recommended_actions
    assert any("sin referencias" in gap for gap in report.knowledge_gaps)
    assert report.status == "hypothesis"


def test_introspection_detects_opposed_observations():
    state = QualiaState(run_id="run-intro-3", confidence=0.6, coherence=0.5)
    experiences = [
        NeuronExperience(
            run_id=state.run_id,
            mission="salud del worker",
            observation="El worker funciona correctamente",
            evidence_refs=["event:1"],
        ),
        NeuronExperience(
            run_id=state.run_id,
            mission="salud del worker",
            observation="El worker no funciona y falla",
            evidence_refs=["event:2"],
        ),
    ]

    report = QualiaIntrospector().reflect(
        run_id=state.run_id,
        state=state,
        experiences=experiences,
    )

    assert report.trigger == "contradiction"
    assert report.contradictions
    assert "request_independent_verification" in report.recommended_actions
    assert set(report.evidence_refs) == {"event:1", "event:2"}


def test_introspection_never_claims_stable_knowledge():
    state = QualiaState(run_id="run-intro-4", confidence=1.0, coherence=1.0)
    report = QualiaIntrospector().reflect(
        run_id=state.run_id,
        state=state,
        experiences=[],
    )

    assert report.status == "hypothesis"
    assert report.requires_verification is True
