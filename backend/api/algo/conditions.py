"""
Condition evaluator — recursive AND/OR/NOT boolean tree evaluation.

Conditions are stored as JSON in the Agent.conditions column.
Evaluated against a context dict built from market data each refresh cycle.

Simple condition:
  {"field": "day_change_val", "op": "<", "value": -50000}

Boolean group:
  {"operator": "and", "rules": [
    {"field": "day_change_val", "op": "<", "value": -50000},
    {"field": "account", "op": "==", "value": "TOTAL"}
  ]}

Nested:
  {"operator": "or", "rules": [
    {"operator": "and", "rules": [...]},
    {"field": "cash", "op": "<", "value": 0}
  ]}
"""

from dataclasses import dataclass


@dataclass
class EvalResult:
    triggered: bool
    condition_text: str
    detail: dict


_OPS = {
    ">":    lambda a, b: a > b,
    "<":    lambda a, b: a < b,
    ">=":   lambda a, b: a >= b,
    "<=":   lambda a, b: a <= b,
    "==":   lambda a, b: a == b,
    "!=":   lambda a, b: a != b,
    "in":   lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
}


def _fmt_value(val) -> str:
    """Format a value for human-readable display."""
    if isinstance(val, float):
        if abs(val) >= 1000:
            return f"₹{val:,.0f}"
        return f"{val:.2f}"
    return str(val)


def _eval_leaf(rule: dict, context: dict) -> EvalResult:
    """Evaluate a single field comparison."""
    field = rule.get("field", "")
    op = rule.get("op", "==")
    expected = rule.get("value")

    actual = context.get(field)
    if actual is None:
        return EvalResult(False, f"{field} not available", {})

    op_fn = _OPS.get(op)
    if not op_fn:
        return EvalResult(False, f"unknown operator {op}", {})

    try:
        triggered = op_fn(float(actual) if isinstance(expected, (int, float)) else actual, expected)
    except (ValueError, TypeError):
        triggered = False

    text = f"{field} {_fmt_value(actual)} {op} {_fmt_value(expected)}"
    return EvalResult(triggered, text, {"field": field, "actual": actual, "expected": expected, "op": op})


def evaluate(condition: dict, context: dict) -> EvalResult:
    """
    Recursively evaluate a condition tree against context data.

    Returns EvalResult with triggered flag and human-readable condition_text.
    """
    if not condition:
        return EvalResult(False, "no conditions", {})

    operator = condition.get("operator")

    if operator:
        rules = condition.get("rules", [])
        if not rules:
            return EvalResult(False, "empty group", {})

        results = [evaluate(r, context) for r in rules]

        if operator == "and":
            triggered = all(r.triggered for r in results)
            text = " AND ".join(r.condition_text for r in results)
        elif operator == "or":
            triggered = any(r.triggered for r in results)
            text = " OR ".join(r.condition_text for r in results)
        elif operator == "not":
            triggered = not results[0].triggered
            text = f"NOT ({results[0].condition_text})"
        else:
            return EvalResult(False, f"unknown operator {operator}", {})

        return EvalResult(triggered, text, {"operator": operator, "results": [r.detail for r in results]})

    # Leaf node
    return _eval_leaf(condition, context)
