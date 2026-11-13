from triade.learning.local_corpus import CASES, RUBRIC_VERSION, evaluate, get_case


def test_corpus_is_versioned_and_distinct():
    assert RUBRIC_VERSION
    assert len({case.case_id for case in CASES}) == len(CASES)
    assert all(case.expected != case.negative_control for case in CASES)


def test_evaluation_is_exact_and_does_not_use_negative_control():
    assert evaluate("python-len", "3")["pass"] is True
    assert evaluate("python-len", "La respuesta es 3")["pass"] is False
    assert evaluate("python-len", "4")["pass"] is False
    assert len(str(evaluate("python-len", "3")["answer_digest"])) == 64


def test_unknown_case_fails_closed():
    try:
        get_case("missing")
    except ValueError as exc:
        assert "desconocido" in str(exc)
    else:
        raise AssertionError("unknown case was accepted")
