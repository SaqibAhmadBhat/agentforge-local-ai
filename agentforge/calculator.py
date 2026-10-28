"""A safe arithmetic evaluator.

The expression is parsed into a Python syntax tree (AST) and only number
literals and arithmetic operators are evaluated. Names, function calls,
attribute access and everything else are rejected, so text written by the
model can never run as Python code. Python's `eval()` is never used.

Size limits stop expressions such as `9**9**9**9` from freezing the computer.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable
from typing import Any

from agentforge.errors import ToolExecutionError

MAX_EXPRESSION_LENGTH = 200
MAX_ABS_VALUE = 1e50  # largest magnitude allowed for any intermediate or final value
MAX_EXPONENT = 1000

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[Any], Any]] = {ast.UAdd: operator.pos, ast.USub: operator.neg}

Number = int | float


class CalculatorError(ToolExecutionError):
    """The expression is invalid or cannot be evaluated safely."""


def evaluate(expression: str) -> Number:
    """Evaluate an arithmetic expression such as '0.15 * 1240' or '(2 + 3) ** 2'.

    Supported: numbers, + - * / // % **, unary minus/plus and parentheses.

    Raises:
        CalculatorError: for anything unsupported, too large, or mathematically undefined.
    """
    if not isinstance(expression, str):
        raise CalculatorError("The expression must be text, for example '2 + 2'.")
    text = expression.strip().replace("×", "*").replace("÷", "/")
    if not text:
        raise CalculatorError("The expression is empty.")
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise CalculatorError(f"The expression is too long (maximum {MAX_EXPRESSION_LENGTH} characters).")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        raise CalculatorError(f"'{text}' is not a valid arithmetic expression.") from None
    return _evaluate_node(tree.body)


def format_number(value: Number) -> str:
    """Turn a result into readable text: 186.0 -> '186', 0.1 + 0.2 -> '0.3'."""
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.12g}"
    return str(value)


def calculate(expression: str) -> str:
    """Evaluate an expression and return the formatted result (used by the calculator tool)."""
    return format_number(evaluate(expression))


def _check_size(value: Number) -> Number:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise CalculatorError("The result is not a finite number.")
    if abs(value) > MAX_ABS_VALUE:
        raise CalculatorError("The result is too large for this calculator.")
    return value


def _safe_power(base: Number, exponent: Number) -> Number:
    """Compute base ** exponent only when the result is guaranteed to stay small."""
    if abs(exponent) > MAX_EXPONENT:
        raise CalculatorError(f"Exponents larger than {MAX_EXPONENT} are not allowed.")
    if base == 0 and exponent < 0:
        raise CalculatorError("Zero cannot be raised to a negative power.")
    if abs(base) > 1 and exponent > 0 and exponent * math.log10(abs(base)) > math.log10(MAX_ABS_VALUE):
        raise CalculatorError("The result is too large for this calculator.")
    if base < 0 and not float(exponent).is_integer():
        raise CalculatorError("A negative number cannot be raised to a fractional power.")
    return base**exponent


def _evaluate_node(node: ast.AST) -> Number:
    """Recursively evaluate one AST node, allowing only numbers and arithmetic."""
    if isinstance(node, ast.Constant):
        # bool is a subclass of int in Python, so exclude it explicitly.
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return _check_size(node.value)
        raise CalculatorError("Only numbers are allowed in expressions.")

    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_evaluate_node(node.operand))

    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise CalculatorError("Division by zero is not allowed.")
        try:
            if isinstance(node.op, ast.Pow):
                result = _safe_power(left, right)
            else:
                result = _BINARY_OPERATORS[type(node.op)](left, right)
        except OverflowError:
            raise CalculatorError("The result is too large for this calculator.") from None
        return _check_size(result)

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitXor):
        raise CalculatorError("'^' is not a power operator here. Use ** instead, for example 2 ** 3.")
    if isinstance(node, ast.Tuple):
        raise CalculatorError("Commas are not allowed. Write 1240 instead of 1,240.")
    raise CalculatorError("Only numbers, + - * / // % **, and parentheses are allowed.")
