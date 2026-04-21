# orchestrator/agent.py
# Entry point for `adk web` — builds root_agent from the YAML manifest.

import yaml
from .config import settings
from .agent_from_manifest import validate_manifest, merge_config, build_agent_from_manifest

with open(settings.manifest.manifest_path, "r") as _f:
    _manifest = yaml.safe_load(_f)

validate_manifest(_manifest)
_merged = merge_config(_manifest)
root_agent = build_agent_from_manifest(_merged)
