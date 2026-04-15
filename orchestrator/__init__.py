# orchestrator/__init__.py
# Lazy import — only triggers agent.py (and the full validation pipeline)
# when root_agent is actually accessed (e.g. by ADK web).
# Importing orchestrator.calculator_agent.tools or orchestrator.palindrome_agent.tools
# directly will NOT trigger agent construction.
#
# Mode switch:
#   ORCHESTRATOR_MODE=false (default) → single agent from MANIFEST_PATH
#   ORCHESTRATOR_MODE=true            → orchestrator + specialist sub-agents


def __getattr__(name: str):
    if name == "root_agent":
        import os
        if os.getenv("ORCHESTRATOR_MODE", "false").lower() == "true":
            from .orchestrator import root_agent  # noqa: PLC0415
        else:
            from .agent import root_agent          # noqa: PLC0415
        return root_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")