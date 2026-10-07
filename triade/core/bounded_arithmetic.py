"""Evaluate small integer expressions as data, never Python code or SQL.

No names other than supplied integer inputs, calls, attributes, powers, strings,
containers or floating point. Explicit bounds prevent resource exhaustion.
"""
from __future__ import annotations
import ast
import operator

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}
_LIMIT = 10**12


def evaluate_integer_expression(expression: str, inputs: dict[str, int]) -> int:
    if not isinstance(expression, str) or len(expression) > 256:
        raise ValueError('expression_size_limit')
    if any(not isinstance(key, str) or not key.isidentifier() or type(value) is not int or abs(value) > _LIMIT
           for key, value in inputs.items()):
        raise ValueError('invalid_integer_inputs')
    try:
        tree = ast.parse(expression, mode='eval')
    except (SyntaxError, RecursionError) as exc:
        raise ValueError('invalid_expression') from exc
    if len(list(ast.walk(tree))) > 64:
        raise ValueError('expression_node_limit')

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            value = node.value
        elif isinstance(node, ast.Name) and node.id in inputs:
            value = inputs[node.id]
        elif isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            value = _OPS[type(node.op)](visit(node.left), visit(node.right))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        else:
            raise ValueError('expression_operation_denied')
        if abs(value) > _LIMIT:
            raise ValueError('expression_value_limit')
        return value

    return visit(tree.body)
