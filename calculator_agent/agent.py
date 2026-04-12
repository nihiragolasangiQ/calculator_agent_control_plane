# calculator_agent/agent.py
# Entry point for `adk web` — builds root_agent from the YAML manifest.

from google.adk.agents import Agent
from .tools import add, subtract, multiply, divide, escalate
from .config import settings

import yaml

with open(settings.manifest.manifest_path, "r") as _f:
    _manifest = yaml.safe_load(_f)

_instruction = _manifest.get("instruction", "").strip()
if not _instruction:
    raise ValueError("Manifest is missing required field: 'instruction'")

root_agent = Agent(
    name=_manifest["identity"]["name"],
    model=settings.agent.model_name
          if "AGENT_MODEL_NAME" in __import__("os").environ
          else _manifest["model"]["base_model_id"],
    description=_manifest["identity"]["description"],
    instruction=_instruction,
    tools=[add, subtract, multiply, divide, escalate],
)