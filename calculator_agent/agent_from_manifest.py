# calculator_agent/agent_from_manifest.py

import asyncio
from dataclasses import dataclass
from pathlib import Path

import yaml
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from calculator_agent.config import settings
from calculator_agent.tools import add, subtract, multiply, divide, escalate


# ---------------------------------------------------------------------------
# TOOL REGISTRY
# Maps tool_id strings (from manifest) → actual Python callables.
# Only tools declared in the manifest AND marked allowed:true are loaded.
# ---------------------------------------------------------------------------

TOOL_REGISTRY = {
    "add": add,
    "subtract": subtract,
    "multiply": multiply,
    "divide": divide,
    "escalate": escalate,
}


# ---------------------------------------------------------------------------
# MERGED CONFIG
# Holds the final resolved values after env-var layer and YAML layer are
# combined.  Env var wins → YAML wins → hardcoded default.
# ---------------------------------------------------------------------------

@dataclass
class MergedConfig:
    """Resolved runtime config: env-var layer merged with YAML layer."""
    # identity
    agent_id: str
    name: str
    display_name: str
    description: str
    # instruction (system prompt — lives in YAML, not code)
    instruction: str
    # model
    model_name: str
    # policy
    confidence_threshold: float
    allowed_problem_types: tuple[str, ...]
    denied_problem_types: tuple[str, ...]
    # rate limits
    requests_per_minute: int
    max_concurrent_sessions: int
    # lifecycle
    max_turns: int
    session_timeout: int
    # tools (resolved callables)
    tools: list


# ---------------------------------------------------------------------------
# STEP 1 — MANIFEST LOADER
# Reads YAML from the path resolved by config.py (env var > default).
# ---------------------------------------------------------------------------

def load_manifest() -> dict:
    path: Path = settings.manifest.manifest_path
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found at: {path}")

    with open(path, "r") as f:
        manifest = yaml.safe_load(f)

    print(f"  Manifest loaded : {manifest['identity']['display_name']} v{manifest['identity']['version']}")
    return manifest


# ---------------------------------------------------------------------------
# STEP 2 — CONFIG MERGER
# Applies env-var layer on top of YAML values.
# Resolution order: Env Var > YAML > hardcoded default
# ---------------------------------------------------------------------------

def merge_config(manifest: dict) -> MergedConfig:
    """Merge settings (env layer) with manifest (YAML layer)."""

    yaml_policy      = manifest.get("policy", {})
    yaml_rate_limits = yaml_policy.get("rate_limits", {})
    yaml_lifecycle   = manifest.get("deployment", {}).get("lifecycle", {})

    # --- model: env var wins, then YAML, then settings default ---
    model_name = (
        settings.agent.model_name                          # env: AGENT_MODEL_NAME
        if "AGENT_MODEL_NAME" in __import__("os").environ
        else manifest["model"]["base_model_id"]            # yaml value
    )

    # --- policy: env var wins, then YAML, then settings default ---
    confidence_threshold = (
        settings.policy.confidence_threshold
        if "CONFIDENCE_THRESHOLD" in __import__("os").environ
        else float(yaml_policy.get("confidence_threshold", settings.policy.confidence_threshold))
    )

    allowed_problem_types = (
        settings.policy.allowed_problem_types
        if "ALLOWED_PROBLEM_TYPES" in __import__("os").environ
        else tuple(yaml_policy.get("allowed_problem_types", list(settings.policy.allowed_problem_types)))
    )

    denied_problem_types = (
        settings.policy.denied_problem_types
        if "DENIED_PROBLEM_TYPES" in __import__("os").environ
        else tuple(yaml_policy.get("denied_problem_types", list(settings.policy.denied_problem_types)))
    )

    # --- rate limits: env var wins, then YAML, then settings default ---
    requests_per_minute = (
        settings.rate_limits.requests_per_minute
        if "RATE_LIMIT_RPM" in __import__("os").environ
        else int(yaml_rate_limits.get("requests_per_minute", settings.rate_limits.requests_per_minute))
    )

    max_concurrent_sessions = (
        settings.rate_limits.max_concurrent_sessions
        if "MAX_CONCURRENT_SESSIONS" in __import__("os").environ
        else int(yaml_rate_limits.get("max_concurrent_sessions", settings.rate_limits.max_concurrent_sessions))
    )

    # --- lifecycle: env var wins, then YAML, then settings default ---
    max_turns = (
        settings.agent.max_turns
        if "MAX_TURNS" in __import__("os").environ
        else int(yaml_lifecycle.get("max_turns", settings.agent.max_turns))
    )

    session_timeout = (
        settings.agent.session_timeout
        if "SESSION_TIMEOUT" in __import__("os").environ
        else int(yaml_lifecycle.get("session_timeout_seconds", settings.agent.session_timeout))
    )

    # --- tools: always resolved from manifest ---
    tools = _load_tools(manifest)

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
    )

    print(f"  Config merged   : model={merged.model_name} | "
          f"rpm={merged.requests_per_minute} | "
          f"max_turns={merged.max_turns} | "
          f"confidence≥{merged.confidence_threshold}")
    return merged


# ---------------------------------------------------------------------------
# TOOL LOADER (internal helper used by merge_config)
# ---------------------------------------------------------------------------

def _load_tools(manifest: dict) -> list:
    allowed_tools = []
    for tool in manifest["capabilities"]["tools"]:
        tool_id = tool["tool_id"]
        if tool["allowed"]:
            if tool_id in TOOL_REGISTRY:
                allowed_tools.append(TOOL_REGISTRY[tool_id])
                print(f"    Tool loaded  : {tool_id}")
            else:
                print(f"    Tool missing in registry: {tool_id}")
        else:
            print(f"    Tool disabled: {tool_id}")
    return allowed_tools


# ---------------------------------------------------------------------------
# STEP 3 — POLICY ENFORCER
# Validates every request against merged config before it reaches the agent.
# Control plane responsibility — agent code knows nothing about this.
# ---------------------------------------------------------------------------

def enforce_policy(problem: str, merged: MergedConfig) -> dict:
    for denied in merged.denied_problem_types:
        if denied.lower() in problem.lower():
            return {
                "allowed": False,
                "reason": f"Problem type '{denied}' is not allowed per policy.",
            }

    # Rate limits — stub; production wires this to a counter service
    print(f"  Rate limit check: {merged.requests_per_minute} rpm (not enforced locally)")

    return {"allowed": True, "reason": None}


# ---------------------------------------------------------------------------
# STEP 4 — AGENT BUILDER
# Constructs the ADK Agent from merged config.
# ---------------------------------------------------------------------------

def build_agent_from_manifest(merged: MergedConfig) -> Agent:
    print(f"\n  Building agent  : {merged.display_name}")

    agent = Agent(
        name=merged.name,
        model=merged.model_name,
        description=merged.description,
        instruction=merged.instruction,
        tools=merged.tools,
    )

    print(f"  Model           : {merged.model_name}")
    print(f"  Tools           : {len(merged.tools)} loaded")
    return agent


# ---------------------------------------------------------------------------
# ORCHESTRATOR
# Load → Merge → Enforce policy → Build → Run
# ---------------------------------------------------------------------------

async def run_from_manifest(problem: str, merged: MergedConfig, agent: Agent):
    print(f"\n  Problem: {problem}")

    policy_result = enforce_policy(problem, merged)
    if not policy_result["allowed"]:
        print(f"  Blocked by policy: {policy_result['reason']}")
        return

    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=merged.name,
        user_id="user_001",
    )

    runner = Runner(
        agent=agent,
        app_name=merged.name,
        session_service=session_service,
    )

    message = Content(role="user", parts=[Part(text=problem)])

    print(f"\n  Agent response:")
    async for event in runner.run_async(
        user_id="user_001",
        session_id=session.id,
        new_message=message,
    ):
        if event.is_final_response():
            print(event.content.parts[0].text)


# ---------------------------------------------------------------------------
# ENTRY POINT — terminal mode
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\nInitializing Calculator Agent Control Plane...")

    # 1. Load manifest (path from config → env var or default)
    manifest = load_manifest()

    # 2. Merge env-var layer with YAML layer → single resolved config
    merged = merge_config(manifest)

    # 3. Build agent once; reuse across the REPL loop
    agent = build_agent_from_manifest(merged)

    print("\n🧮 Calculator Agent (terminal mode)")
    print("   Type your math problem and press Enter")
    print("   Type 'exit' to quit")
    print("-" * 50)

    while True:
        try:
            problem = input("\n> ").strip()

            if problem.lower() == "exit":
                print("👋 Bye!")
                break

            if not problem:
                continue

            asyncio.run(run_from_manifest(problem, merged, agent))

        except KeyboardInterrupt:
            print("\n👋 Bye!")
            break
