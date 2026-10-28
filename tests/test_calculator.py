"""Unit tests for the safe calculator."""

import time

import pytest

from agentforge.calculator import CalculatorError, calculate


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2 + 2", "4"),
        ("0.15 * 1240", "186"),
        ("(2 + 3) ** 2", "25"),
        ("10 / 4", "2.5"),
        ("7 // 2", "3"),
        ("7 % 3", "1"),
        ("-5 + +3", "-2"),
        ("2 ** -1", "0.5"),
        ("0.1 + 0.2", "0.3"),
        ("1 / 3", "0.333333333333"),
        ("6 × 7", "42"),
        ("84 ÷ 2", "42"),
        ("2 ** 64", "18446744073709551616"),
    ],
)
def test_valid_expressions(expression, expected):
    assert calculate(expression) == expected


@pytest.mark.parametrize("expression", ["1 / 0", "5 // 0", "5 % 0", "1 / (2 - 2)"])
def test_division_by_zero_is_reported(expression):
    with pytest.raises(CalculatorError, match="Division by zero"):
        calculate(expression)


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('ls')",  # code injection
        "abs(-3)",  # function calls
        "x + 1",  # names
        "(1).real",  # attribute access
        "[1, 2][0]",  # subscripts
        "'a' * 3",  # strings
        "True + True",  # booleans
        "1j * 2",  # complex numbers
        "1 < 2",  # comparisons
        "lambda: 1",
    ],
)
def test_non_arithmetic_is_rejected(expression):
    with pytest.raises(CalculatorError):
        calculate(expression)


@pytest.mark.parametrize("expression", ["", "   ", "2 +", "((1)", "15% of 1240"])
def test_invalid_syntax_is_rejected(expression):
    with pytest.raises(CalculatorError):
        calculate(expression)


def test_helpful_messages_for_common_mistakes():
    with pytest.raises(CalculatorError, match=r"\*\*"):
        calculate("2 ^ 3")
    with pytest.raises(CalculatorError, match="Commas"):
        calculate("1,240 * 2")


@pytest.mark.parametrize(
    "expression", ["9 ** 9 ** 9 ** 9", "10 ** 100000", "2 ** 1000", "(10 ** 40) * (10 ** 40)", "1e308 * 10"]
)
def test_huge_results_are_refused_quickly(expression):
    start = time.perf_counter()
    with pytest.raises(CalculatorError):
        calculate(expression)
    assert time.perf_counter() - start < 1.0


def test_overlong_expression_is_rejected():
    with pytest.raises(CalculatorError, match="too long"):
        calculate("1+" * 150 + "1")


def test_non_string_input_is_rejected():
    with pytest.raises(CalculatorError):
        calculate(42)  # type: ignore[arg-type]


def test_fractional_power_of_negative_number_is_rejected():
    with pytest.raises(CalculatorError, match="negative"):
        calculate("(-8) ** 0.5")
