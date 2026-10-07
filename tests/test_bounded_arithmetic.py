import pytest
from triade.core.bounded_arithmetic import evaluate_integer_expression


def test_transfers_unseen_rules_without_embedded_algorithm():
    assert evaluate_integer_expression('(units * 9 + 2) % 41', {'units': 12}) == 28
    assert evaluate_integer_expression('-(units // 4) + 7', {'units': 12}) == 4


@pytest.mark.parametrize('expression', [
    '__import__("os").system("whoami")', 'amount.__class__', '[1]*999999',
    '2**10000000', 'True', '1.5', 'unknown+1', '"text"',
    '1'*257, '(1+1)'*64, '1000000000001',
])
def test_denies_code_and_unbounded_operations(expression):
    with pytest.raises(ValueError):
        evaluate_integer_expression(expression, {'amount': 4})


def test_denies_bool_inputs_and_zero_division():
    with pytest.raises(ValueError):
        evaluate_integer_expression('amount', {'amount': True})
    with pytest.raises(ZeroDivisionError):
        evaluate_integer_expression('amount % 0', {'amount': 4})
