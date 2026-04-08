# calculator_agent/tools.py

def add(a: float, b: float) -> dict:
    """Adds two numbers together."""
    result = a + b
    return {"operation": "addition", "a": a, "b": b, "result": result}


def subtract(a: float, b: float) -> dict:
    """Subtracts b from a."""
    result = a - b
    return {"operation": "subtraction", "a": a, "b": b, "result": result}


def multiply(a: float, b: float) -> dict:
    """Multiplies two numbers together."""
    result = a * b
    return {"operation": "multiplication", "a": a, "b": b, "result": result}


def divide(a: float, b: float) -> dict:
    """Divides a by b. Returns error if b is zero."""
    if b == 0:
        return {"operation": "division", "a": a, "b": b, "result": None, "error": "Cannot divide by zero"}
    result = a / b
    return {"operation": "division", "a": a, "b": b, "result": result}


def escalate(reason: str) -> dict:
    """
    Escalates the problem to human review when the agent
    is not confident or the problem is too complex.
    """
    print(f"\n⚠️  ESCALATION TRIGGERED: {reason}\n")
    return {"escalated": True, "reason": reason}