# calculator_agent/agent.py
# Entry point for `adk web` — builds root_agent from the YAML manifest.
# Tools are loaded dynamically from TOOL_REGISTRY based on the manifest,
# so swapping MANIFEST_PATH switches the agent completely (tools + model + instruction).

import yaml
from google.adk.agents import Agent

from .config import settings
from .agent_from_manifest import _load_tools, validate_manifest

with open(settings.manifest.manifest_path, "r") as _f:
    _manifest = yaml.safe_load(_f)

validate_manifest(_manifest)

_instruction = _manifest.get("instruction", "").strip()
if not _instruction:
    raise ValueError("Manifest is missing required field: 'instruction'")

_tools = _load_tools(_manifest)

root_agent = Agent(
    name=_manifest["identity"]["name"],
    model=settings.agent.model_name
          if "AGENT_MODEL_NAME" in __import__("os").environ
          else _manifest["model"]["base_model_id"],
    description=_manifest["identity"]["description"],
    instruction=_instruction,
    tools=_tools,
)