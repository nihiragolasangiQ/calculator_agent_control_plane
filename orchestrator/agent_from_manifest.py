import asyncio
import importlib
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool import MCPToolset, StreamableHTTPConnectionParams, StdioConnectionParams
from google.adk.tools.agent_tool import AgentTool
from google.genai.types import Content, Part
from mcp import StdioServerParameters

from .config import settings
from .incident_agent.tools import (
    fetch_ai_analysis,
    fetch_incident_details,
    list_columns,
    build_triage_dashboard,
    fetch_incidents_by_date,
)

TOOL_REGISTRY = {
    "fetch_ai_analysis": fetch_ai_analysis,
    "fetch_incident_details": fetch_incident_details,
    "list_columns": list_columns,
    "build_triage_dashboard": build_triage_dashboard,
    "fetch_incidents_by_date": fetch_incidents_by_date,
}


@dataclass
class MergedConfig:
    agent_id: str
    name: str
    display_name: str
    description: str
    instruction: str
    model_name: str
    confidence_threshold: float
    allowed_problem_types: tuple[str, ...]
    denied_problem_types: tuple[str, ...]
    requests_per_minute: int
    max_concurrent_sessions: int
    max_turns: int
    session_timeout: int
    tools: list
    sub_agents: list
    after_model_callback: object = None
    after_tool_callback: object = None


def load_manifest() -> dict:
    path: Path = settings.manifest.manifest_path
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found at: {path}")
    with open(path) as f:
        manifest = yaml.safe_load(f)
    print(f"  Manifest loaded : {manifest['identity']['display_name']} v{manifest['identity']['version']}")
    return manifest


def validate_manifest(manifest: dict) -> None:
    print("\n  Validating manifest...")

    for key in ["identity", "instruction", "model", "capabilities", "policy"]:
        if key not in manifest:
            raise ValueError(f"Manifest validation FAILED: missing required key '{key}'")

    errors = []
    warnings = []
    tools = manifest.get("capabilities", {}).get("tools", [])

    for tool in tools:
        tool_id   = tool.get("tool_id", "<unknown>")
        tool_type = tool.get("type", "function")
        allowed   = tool.get("allowed", False)

        if not allowed:
            print(f"    [SKIP] {tool_id} (allowed: false)")
            continue

        if tool.get("version") is None:
            warnings.append(f"{tool_id}: no 'version' field (informational)")

        if tool_type == "mcp_server":
            transport = tool.get("transport", "http").strip().lower()
            if transport == "stdio":
                command = tool.get("command", "").strip()
                if not command:
                    errors.append(f"{tool_id}: transport=stdio but 'command' is missing or empty")
                else:
                    args = tool.get("args", [])
                    print(f"    [PASS] {tool_id} (mcp_server/stdio → {command} {' '.join(args)})")
            else:
                url = tool.get("url", "").strip()
                if not url:
                    errors.append(f"{tool_id}: type=mcp_server but 'url' is missing or empty")
                else:
                    print(f"    [PASS] {tool_id} (mcp_server/http → {url})")

            fallback_id = tool.get("fallback_tool_id", "").strip()
            if fallback_id and fallback_id not in TOOL_REGISTRY:
                warnings.append(
                    f"{tool_id}: fallback_tool_id='{fallback_id}' not found in TOOL_REGISTRY"
                )

        elif tool_type in ("function", "human_in_loop"):
            if tool_id not in TOOL_REGISTRY:
                errors.append(f"{tool_id}: type={tool_type} but tool_id not found in TOOL_REGISTRY")
            else:
                print(f"    [PASS] {tool_id} (function in TOOL_REGISTRY)")

        elif tool_type == "sub_agent":
            manifest_path = tool.get("manifest_path", "").strip()
            if not manifest_path:
                errors.append(f"{tool_id}: type=sub_agent but 'manifest_path' is missing or empty")
            else:
                resolved = Path(manifest_path)
                if not resolved.is_absolute():
                    resolved = Path(settings.manifest.manifest_path).parent.parent.parent / manifest_path
                if not resolved.exists():
                    errors.append(f"{tool_id}: sub_agent manifest not found at '{manifest_path}'")
                else:
                    skills = tool.get("skills", [])
                    print(f"    [PASS] {tool_id} (sub_agent → {manifest_path}, skills={skills})")
        else:
            warnings.append(f"{tool_id}: unknown type '{tool_type}' — skipped validation")

    if not tools:
        warnings.append("No tools declared — agent will run on model knowledge only")

    for w in warnings:
        print(f"    [WARN] {w}")

    if errors:
        raise ValueError("Manifest validation FAILED:\n  " + "\n  ".join(errors))

    print(f"  Manifest valid  : {len(tools)} tools checked, {len(warnings)} warnings\n")


def merge_config(manifest: dict) -> MergedConfig:
    yaml_policy      = manifest.get("policy", {})
    yaml_rate_limits = yaml_policy.get("rate_limits", {})
    yaml_lifecycle   = manifest.get("deployment", {}).get("lifecycle", {})

    model_name = (
        settings.agent.model_name
        if "AGENT_MODEL_NAME" in os.environ
        else manifest["model"]["base_model_id"]
    )
    confidence_threshold = (
        settings.policy.confidence_threshold
        if "CONFIDENCE_THRESHOLD" in os.environ
        else float(yaml_policy.get("confidence_threshold", settings.policy.confidence_threshold))
    )
    allowed_problem_types = (
        settings.policy.allowed_problem_types
        if "ALLOWED_PROBLEM_TYPES" in os.environ
        else tuple(yaml_policy.get("allowed_problem_types", list(settings.policy.allowed_problem_types)))
    )
    denied_problem_types = (
        settings.policy.denied_problem_types
        if "DENIED_PROBLEM_TYPES" in os.environ
        else tuple(yaml_policy.get("denied_problem_types", list(settings.policy.denied_problem_types)))
    )
    requests_per_minute = (
        settings.rate_limits.requests_per_minute
        if "RATE_LIMIT_RPM" in os.environ
        else int(yaml_rate_limits.get("requests_per_minute", settings.rate_limits.requests_per_minute))
    )
    max_concurrent_sessions = (
        settings.rate_limits.max_concurrent_sessions
        if "MAX_CONCURRENT_SESSIONS" in os.environ
        else int(yaml_rate_limits.get("max_concurrent_sessions", settings.rate_limits.max_concurrent_sessions))
    )
    max_turns = (
        settings.agent.max_turns
        if "MAX_TURNS" in os.environ
        else int(yaml_lifecycle.get("max_turns", settings.agent.max_turns))
    )
    session_timeout = (
        settings.agent.session_timeout
        if "SESSION_TIMEOUT" in os.environ
        else int(yaml_lifecycle.get("session_timeout_seconds", settings.agent.session_timeout))
    )

    tools      = _load_tools(manifest)
    sub_agents = _load_sub_agents(manifest)
    after_model_cb, after_tool_cb = _resolve_callbacks(manifest)

    instruction = manifest.get("instruction", "").strip()
    if not instruction:
        raise ValueError("Manifest is missing required field: 'instruction'")

    merged = MergedConfig(
        agent_id=manifest["identity"]["agent_id"],
        name=manifest["identity"]["name"],
        display_name=manifest["identity"]["display_name"],
        description=manifest["identity"]["description"],
        instruction=instruction,
        model_name=model_name,
        confidence_threshold=confidence_threshold,
        allowed_problem_types=allowed_problem_types,
        denied_problem_types=denied_problem_types,
        requests_per_minute=requests_per_minute,
        max_concurrent_sessions=max_concurrent_sessions,
        max_turns=max_turns,
        session_timeout=session_timeout,
        tools=tools,
        sub_agents=sub_agents,
        after_model_callback=after_model_cb,
        after_tool_callback=after_tool_cb,
    )
    print(
        f"  Config merged   : model={merged.model_name} | "
        f"rpm={merged.requests_per_minute} | "
        f"max_turns={merged.max_turns} | "
        f"confidence≥{merged.confidence_threshold}"
    )
    return merged


def _resolve_auth_headers(auth_config: dict) -> dict:
    auth_type  = auth_config.get("type", "none")
    secret_ref = auth_config.get("secret_ref", "").strip()

    if auth_type == "none" or not secret_ref:
        return {}

    credential = os.getenv(secret_ref, "")
    if not credential:
        print(f"    Auth WARNING: env var '{secret_ref}' is not set or empty")

    if auth_type == "api_key":
        return {"X-API-Key": credential}
    if auth_type == "bearer":
        return {"Authorization": f"Bearer {credential}"}
    return {}


def _resolve_callbacks(manifest: dict) -> tuple:
    callbacks      = manifest.get("capabilities", {}).get("callbacks", {})
    after_model_cb = None
    after_tool_cb  = None

    for cb_key, target in [
        ("after_model_callback", "after_model_cb"),
        ("after_tool_callback",  "after_tool_cb"),
    ]:
        ref = callbacks.get(cb_key, "").strip()
        if not ref:
            continue
        try:
            module_path, factory_name = ref.rsplit(":", 1)
            factory = getattr(importlib.import_module(module_path), factory_name)
            cb = factory()
            if cb_key == "after_model_callback":
                after_model_cb = cb
            else:
                after_tool_cb = cb
            print(f"    Callback loaded: {cb_key} → {ref}")
        except Exception as exc:
            print(f"    [WARN] Failed to load callback '{cb_key}' ({ref}): {exc}")

    return after_model_cb, after_tool_cb


def _load_tools(manifest: dict) -> list:
    allowed_tools = []

    for tool in manifest["capabilities"]["tools"]:
        tool_id        = tool["tool_id"]
        tool_type      = tool.get("type", "function")
        on_unavailable = tool.get("on_unavailable", "fail")

        if not tool["allowed"]:
            print(f"    Tool disabled: {tool_id}")
            continue

        if tool_type == "mcp_server":
            transport        = tool.get("transport", "http").strip().lower()
            allowed_tool_ids = tool.get("allowed_tool_ids") or None
            fallback_tool_id = tool.get("fallback_tool_id", "").strip() or None

            try:
                if transport == "stdio":
                    command  = tool.get("command", "").strip()
                    args     = tool.get("args", [])
                    tool_env = {k: os.path.expandvars(v) for k, v in tool.get("env", {}).items()}
                    if not command:
                        raise ValueError(f"{tool_id}: transport=stdio but 'command' is missing")
                    connection_params = StdioConnectionParams(
                        server_params=StdioServerParameters(
                            command=command,
                            args=args,
                            env=tool_env if tool_env else None,
                        )
                    )
                    filter_note = f"filter={allowed_tool_ids}" if allowed_tool_ids else "no filter"
                    print(f"    Tool loaded  : {tool_id} (stdio → {command} {' '.join(args)}, {filter_note})")
                else:
                    url         = tool.get("url", "").strip()
                    auth_config = tool.get("auth", {"type": "none", "secret_ref": ""})
                    if not url:
                        raise ValueError(f"{tool_id}: transport=http but 'url' is missing")
                    headers = _resolve_auth_headers(auth_config)
                    connection_params = StreamableHTTPConnectionParams(
                        url=url,
                        headers=headers if headers else None,
                    )
                    filter_note = f"filter={allowed_tool_ids}" if allowed_tool_ids else "no filter"
                    print(f"    Tool loaded  : {tool_id} (http @ {url}, {filter_note})")

                allowed_tools.append(MCPToolset(
                    connection_params=connection_params,
                    tool_filter=allowed_tool_ids,
                ))

            except Exception as exc:
                msg = f"MCP toolset '{tool_id}' failed to load: {exc}"
                if on_unavailable == "fail":
                    raise RuntimeError(msg) from exc
                print(f"    [WARN] {msg}")
                if fallback_tool_id and fallback_tool_id in TOOL_REGISTRY:
                    allowed_tools.append(TOOL_REGISTRY[fallback_tool_id])
                    print(f"    [FALLBACK] {tool_id} unreachable → using local '{fallback_tool_id}'")
                else:
                    print(f"    [WARN] No fallback for '{tool_id}' — tool unavailable this session")

        else:
            if tool_id in TOOL_REGISTRY:
                allowed_tools.append(TOOL_REGISTRY[tool_id])
                print(f"    Tool loaded  : {tool_id}")
            else:
                print(f"    Tool missing in registry: {tool_id}")

    return allowed_tools


def _load_sub_agents(manifest: dict) -> list:
    sub_agents = []

    for tool in manifest["capabilities"]["tools"]:
        if not tool.get("allowed", False) or tool.get("type") != "sub_agent":
            continue

        tool_id       = tool["tool_id"]
        manifest_path = tool.get("manifest_path", "").strip()

        resolved = Path(manifest_path)
        if not resolved.is_absolute():
            resolved = Path(settings.manifest.manifest_path).parent.parent.parent / manifest_path

        with open(resolved) as f:
            sub_manifest = yaml.safe_load(f)

        print(f"\n  Loading sub-agent: {tool_id}")
        validate_manifest(sub_manifest)
        sub_merged = merge_config(sub_manifest)
        sub_agent  = build_agent_from_manifest(sub_merged)
        sub_agents.append(AgentTool(agent=sub_agent))
        print(f"  Sub-agent ready : {tool_id} (AgentTool, skills={tool.get('skills', [])})")

    return sub_agents


def enforce_policy(problem: str, merged: MergedConfig) -> dict:
    for denied in merged.denied_problem_types:
        if denied.lower() in problem.lower():
            return {"allowed": False, "reason": f"Problem type '{denied}' is not allowed per policy."}
    print(f"  Rate limit check: {merged.requests_per_minute} rpm (not enforced locally)")
    return {"allowed": True, "reason": None}


def build_agent_from_manifest(merged: MergedConfig) -> Agent:
    print(f"\n  Building agent  : {merged.display_name}")

    all_tools   = merged.tools + merged.sub_agents
    agent_kwargs = dict(
        name=merged.name,
        model=merged.model_name,
        description=merged.description,
        instruction=merged.instruction,
        tools=all_tools,
    )
    if merged.after_model_callback:
        agent_kwargs["after_model_callback"] = merged.after_model_callback
        print("  Callback        : after_model_callback attached")
    if merged.after_tool_callback:
        agent_kwargs["after_tool_callback"] = merged.after_tool_callback
        print("  Callback        : after_tool_callback attached")

    agent = Agent(**agent_kwargs)
    print(f"  Model           : {merged.model_name}")
    print(f"  Tools           : {len(merged.tools)} function/mcp tools + {len(merged.sub_agents)} agent tools = {len(all_tools)} total")
    return agent


async def run_from_manifest(problem: str, merged: MergedConfig, agent: Agent):
    print(f"\n  Problem: {problem}")
    policy_result = enforce_policy(problem, merged)
    if not policy_result["allowed"]:
        print(f"  Blocked by policy: {policy_result['reason']}")
        return

    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name=merged.name, user_id="user_001")
    runner  = Runner(agent=agent, app_name=merged.name, session_service=session_service)
    message = Content(role="user", parts=[Part(text=problem)])

    print("\n  Agent response:")
    async for event in runner.run_async(
        user_id="user_001",
        session_id=session.id,
        new_message=message,
    ):
        if event.is_final_response():
            print(event.content.parts[0].text)


async def _repl(merged: MergedConfig, agent: Agent):
    print(f"\n  {merged.display_name} (terminal mode)")
    print("  Type your message and press Enter. Type 'exit' to quit.")
    print("-" * 50)

    while True:
        try:
            problem = input("\n> ").strip()
            if problem.lower() == "exit":
                print("Bye!")
                break
            if not problem:
                continue
            await run_from_manifest(problem, merged, agent)
        except KeyboardInterrupt:
            print("\nBye!")
            break


if __name__ == "__main__":
    print("\nInitializing Agent Control Plane...")
    manifest = load_manifest()
    validate_manifest(manifest)
    merged   = merge_config(manifest)
    agent    = build_agent_from_manifest(merged)
    asyncio.run(_repl(merged, agent))
