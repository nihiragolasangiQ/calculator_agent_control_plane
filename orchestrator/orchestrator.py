import os
from pathlib import Path

import yaml
from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool

from .config import settings
from .agent_from_manifest import validate_manifest, merge_config, build_agent_from_manifest

_MANIFEST_DIR = Path(settings.manifest.manifest_path).parent
_ORCH_MANIFEST_PATH = Path(
    os.getenv("ORCHESTRATOR_MANIFEST_PATH") or str(_MANIFEST_DIR / "orchestrator_manifest.yaml")
)


def _discover_agent_manifests(manifest_dir: Path) -> list[Path]:
    found = sorted(manifest_dir.glob("*_manifest.yaml"))
    return [p for p in found if p.name != _ORCH_MANIFEST_PATH.name]


def _build_routing_block(agent_manifests: list[Path]) -> str:
    if not agent_manifests:
        return "You have no specialist agents available. Politely tell the user you cannot help."

    lines = ["You have the following specialist agents available:\n"]
    for path in agent_manifests:
        with open(path) as f:
            m = yaml.safe_load(f)
        identity = m.get("identity", {})
        name = identity.get("name", path.stem)
        description = identity.get("description", "No description provided.").strip()
        lines.append(f"- {name}: {description}")

    lines.append(
        "\nRoute each user request to the most appropriate agent based on the descriptions above."
        "\nIf a request could match multiple agents, pick the most specific one."
        "\nIf no agent is relevant, pass it to the closest match — it will handle the refusal."
    )
    return "\n".join(lines)


def _inject_sub_agents(manifest: dict, agent_manifests: list[Path]) -> dict:
    sub_agent_tools = []
    for path in agent_manifests:
        with open(path) as f:
            m = yaml.safe_load(f)
        identity = m.get("identity", {})
        sub_agent_tools.append({
            "tool_id":      identity.get("name", path.stem),
            "type":         "sub_agent",
            "display_name": identity.get("display_name", identity.get("name", path.stem)),
            "description":  identity.get("description", ""),
            "manifest_path": str(path),
            "allowed":      True,
        })
        print(f"  Discovered agent: {identity.get('name', path.stem)} ({path.name})")

    manifest.setdefault("capabilities", {})["tools"] = sub_agent_tools
    routing_block = _build_routing_block(agent_manifests)
    manifest["instruction"] = manifest.get("instruction", "").replace(
        "{agent_routing_block}", routing_block
    )
    return manifest


def _build_orchestrator() -> Agent:
    print("\n  Orchestrator mode — auto-discovering specialist agents...")
    agent_manifests = _discover_agent_manifests(_MANIFEST_DIR)
    print(f"  Found {len(agent_manifests)} specialist agent(s) in {_MANIFEST_DIR}\n")

    with open(_ORCH_MANIFEST_PATH) as f:
        manifest = yaml.safe_load(f)

    manifest = _inject_sub_agents(manifest, agent_manifests)
    validate_manifest(manifest)
    merged = merge_config(manifest)
    return build_agent_from_manifest(merged)


root_agent = _build_orchestrator()
