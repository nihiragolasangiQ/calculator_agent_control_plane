# calculator_agent/__init__.py
# Lazy import — only triggers agent.py (and the full validation pipeline)
# when root_agent is actually accessed (e.g. by ADK web).
# Importing calculator_agent.tools or calculator_agent.palindrome_tools
# directly will NOT trigger agent construction.


def __getattr__(name: str):
    if name == "root_agent":
        from .agent import root_agent  # noqa: PLC0415
        return root_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")