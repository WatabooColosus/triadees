from triade.learning.knowledge_probe import _arithmetic_probe


def test_equation_probe_tests_application_and_preserves_negative_control():
    probe = _arithmetic_probe('unit', 'ledger quantity: total=(units*9+2)%41. Observed constraint.')
    assert probe is not None
    assert '(units*9+2)%41' not in probe.question
    assert probe.expected not in probe.question
    assert probe.evaluator('{"expression":"(units*9+2)%41"}')
    assert not probe.evaluator('{"expression":"units*9+2%41"}')
    assert not probe.evaluator('{"expression":null}')
    assert not probe.evaluator('{"expression":"__import__(\"os\")"}')


def test_unsupported_equations_are_not_certified():
    for content in ('x=__import__("os")', 'x=a+b.', 'x=a**99999.', 'x=a//2.', 'x=1.5.', 'x=a*1.5.', 'x=a[0].', 'status=ready.'):
        assert _arithmetic_probe('unit', content) is None
