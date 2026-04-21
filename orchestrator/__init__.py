import os


def __getattr__(name: str):
    if name == "root_agent":
        if os.getenv("ORCHESTRATOR_MODE", "false").lower() == "true":
            from .orchestrator import root_agent  # noqa: PLC0415
        else:
            from .agent import root_agent          # noqa: PLC0415
        return root_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
