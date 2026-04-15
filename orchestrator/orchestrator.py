# orchestrator/orchestrator.py
# Entry point for orchestrator mode — builds root_agent from the orchestrator manifest.
# The orchestrator agent routes requests to specialist sub-agents based on skills.
# Sub-agents are declared in the orchestrator manifest as type: sub_agent.
#
# Activated via: ORCHESTRATOR_MODE=true (adk web or terminal)

import os
import yaml
from google.adk.agents import Agent

from .config import settings
from .agent_from_manifest import (
    validate_manifest,
    merge_config,
    build_agent_from_manifest,
)

# ---------------------------------------------------------------------------
# Resolve orchestrator manifest path
# Defaults to orchestrator/manifest/orchestrator_manifest.yaml
# Override via ORCHESTRATOR_MANIFEST_PATH env var
# ---------------------------------------------------------------------------
_DEFAULT_ORCH_MANIFEST = (
    settings.manifest.manifest_path.parent / "orchestrator_manifest.yaml"
)
_ORCH_MANIFEST_PATH = os.getenv("ORCHESTRATOR_MANIFEST_PATH") or str(_DEFAULT_ORCH_MANIFEST)

with open(_ORCH_MANIFEST_PATH, "r") as _f:
    _manifest = yaml.safe_load(_f)

validate_manifest(_manifest)

_merged = merge_config(_manifest)
root_agent = build_agent_from_manifest(_merged)
