# calculator_agent/agent_from_manifest.py

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool import MCPToolset
from google.adk.tools.mcp_tool import StreamableHTTPConnectionParams
from google.genai.types import Content, Part

from calculator_agent.config import settings
from calculator_agent.tools import add, subtract, multiply, divide, escalate
from calculator_agent.palindrome_tools import (
    is_palindrome,
    longest_palindrome_substring,
    make_palindrome,
    palindrome_score,
)


# ---------------------------------------------------------------------------
# TOOL REGISTRY
# Maps tool_id strings (from manifest) → Python callables.
# Used for type: function and type: human_in_loop tools.
# For type: mcp_server tools, McpToolset is constructed directly from the
# manifest URL — no entry in this registry is needed.
# ---------------------------------------------------------------------------

TOOL_REGISTRY = {
    # Calculator tools
    "add": add,
    "subtract": subtract,
    "multiply": multiply,
    "divide": divide,
    # Palindrome tools
    "is_palindrome": is_palindrome,
    "longest_palindrome_substring": longest_palindrome_substring,
    "make_palindrome": make_palindrome,
    "palindrome_score": palindrome_score,
    # Shared
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
    # tools (resolved callables or McpToolset objects)
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
# STEP 1b — MANIFEST VALIDATOR
# Structural validation at startup — before any agent construction.
# Catches config errors early rather than at first user request.
# Does NOT make network calls (MCP server reachability is a runtime concern).
# ---------------------------------------------------------------------------

def validate_manifest(manifest: dict) -> None:
    """Validates manifest structure. Raises ValueError on hard errors, prints WARNs."""
    print("\n  Validating manifest...")

    # Required top-level keys
    required_keys = ["identity", "instruction", "model", "capabilities", "policy"]
    for key in required_keys:
        if key not in manifest:
            raise ValueError(f"Manifest validation FAILED: missing required key '{key}'")

    errors = []
    warnings = []

    tools = manifest.get("capabilities", {}).get("tools", [])
    for tool in tools:
        tool_id   = tool.get("tool_id", "<unknown>")
        tool_type = tool.get("type", "function")
        allowed   = tool.get("allowed", False)
        version   = tool.get("version")

        if not allowed:
            print(f"    [SKIP] {tool_id} (allowed: false)")
            continue

        if version is None:
            warnings.append(f"{tool_id}: no 'version' field (informational)")

        if tool_type == "mcp_server":
            url = tool.get("url", "").strip()
            if not url:
                errors.append(f"{tool_id}: type=mcp_server but 'url' is missing or empty")
            else:
                print(f"    [PASS] {tool_id} (mcp_server → {url})")

            fallback_id = tool.get("fallback_tool_id", "").strip()
            if fallback_id and fallback_id not in TOOL_REGISTRY:
                warnings.append(
                    f"{tool_id}: fallback_tool_id='{fallback_id}' not found in TOOL_REGISTRY — fallback will be skipped"
                )

        elif tool_type in ("function", "human_in_loop"):
            if tool_id not in TOOL_REGISTRY:
                errors.append(
                    f"{tool_id}: type={tool_type} but tool_id not found in TOOL_REGISTRY"
                )
            else:
                print(f"    [PASS] {tool_id} (function in TOOL_REGISTRY)")

        else:
            warnings.append(f"{tool_id}: unknown type '{tool_type}' — skipped validation")

    if not tools:
        warnings.append("No tools declared — agent will run on model knowledge only (no tool calls possible)")

    for w in warnings:
        print(f"    [WARN] {w}")

    if errors:
        raise ValueError("Manifest validation FAILED:\n  " + "\n  ".join(errors))

    print(f"  Manifest valid  : {len(tools)} tools checked, {len(warnings)} warnings\n")


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
        settings.agent.model_name
        if "AGENT_MODEL_NAME" in os.environ
        else manifest["model"]["base_model_id"]
    )

    # --- policy: env var wins, then YAML, then settings default ---
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

    # --- rate limits: env var wins, then YAML, then settings default ---
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

    # --- lifecycle: env var wins, then YAML, then settings default ---
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
# AUTH HELPER (used by _load_tools for mcp_server tools)
# Reads credentials from env vars — secrets never live in the manifest YAML.
# ---------------------------------------------------------------------------

def _resolve_auth_headers(auth_config: dict) -> dict:
    """Resolves MCP auth credentials from env vars named in secret_ref.

    Auth types:
      none     → {} (no credential)
      api_key  → {"X-API-Key": os.getenv(secret_ref)}
      bearer   → {"Authorization": "Bearer " + os.getenv(secret_ref)}

    The credential is read once at agent startup and baked into McpToolset.
    If the credential rotates, restart the process.
    """
    auth_type  = auth_config.get("type", "none")
    secret_ref = auth_config.get("secret_ref", "").strip()

    if auth_type == "none" or not secret_ref:
        return {}

    credential = os.getenv(secret_ref, "")
    if not credential:
        print(f"    Auth WARNING: env var '{secret_ref}' is not set or empty")

    if auth_type == "api_key":
        return {"X-API-Key": credential}
    elif auth_type == "bearer":
        return {"Authorization": f"Bearer {credential}"}

    return {}


# ---------------------------------------------------------------------------
# TOOL LOADER (internal helper used by merge_config)
# Routes tool declarations to the correct loading path:
#   type: mcp_server       → McpToolset (remote, URL-based)
#   type: function         → TOOL_REGISTRY lookup (local Python callable)
#   type: human_in_loop    → TOOL_REGISTRY lookup (local Python callable)
# ---------------------------------------------------------------------------

def _load_tools(manifest: dict) -> list:
    """Resolves tool declarations from the manifest into ADK tool objects.

    McpToolset.__init__ is synchronous-safe — it only instantiates a
    MCPSessionManager and stores connection params. No I/O happens here.
    The actual async HTTP connection to the MCP server is deferred until
    ADK calls get_tools() during the first agent invocation.

    on_unavailable behaviour:
      "fail" → raise RuntimeError if tool cannot be loaded
      "warn" → log a warning and skip the tool (agent starts with partial tools)
    """
    allowed_tools = []

    for tool in manifest["capabilities"]["tools"]:
        tool_id          = tool["tool_id"]
        tool_type        = tool.get("type", "function")
        on_unavailable   = tool.get("on_unavailable", "fail")

        if not tool["allowed"]:
            print(f"    Tool disabled: {tool_id}")
            continue

        # ── MCP server path ──────────────────────────────────────────────────
        if tool_type == "mcp_server":
            url              = tool.get("url", "").strip()
            allowed_tool_ids = tool.get("allowed_tool_ids") or None  # None = allow all
            auth_config      = tool.get("auth", {"type": "none", "secret_ref": ""})
            fallback_tool_id = tool.get("fallback_tool_id", "").strip() or None

            try:
                headers = _resolve_auth_headers(auth_config)
                toolset = MCPToolset(
                    connection_params=StreamableHTTPConnectionParams(
                        url=url,
                        headers=headers if headers else None,
                    ),
                    tool_filter=allowed_tool_ids,
                )
                allowed_tools.append(toolset)
                filter_note = f"filter={allowed_tool_ids}" if allowed_tool_ids else "no filter"
                print(f"    Tool loaded  : {tool_id} (mcp_server @ {url}, {filter_note})")

            except Exception as exc:
                msg = f"MCP toolset '{tool_id}' failed to load: {exc}"
                if on_unavailable == "fail":
                    raise RuntimeError(msg) from exc

                # on_unavailable == "warn" — try local fallback before giving up
                print(f"    [WARN] {msg}")
                if fallback_tool_id and fallback_tool_id in TOOL_REGISTRY:
                    allowed_tools.append(TOOL_REGISTRY[fallback_tool_id])
                    print(f"    [FALLBACK] {tool_id} unreachable → using local '{fallback_tool_id}' function")
                else:
                    print(f"    [WARN] No fallback for '{tool_id}' — tool unavailable this session")

        # ── Function / human_in_loop path ────────────────────────────────────
        else:
            if tool_id in TOOL_REGISTRY:
                allowed_tools.append(TOOL_REGISTRY[tool_id])
                print(f"    Tool loaded  : {tool_id}")
            else:
                print(f"    Tool missing in registry: {tool_id}")

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
# Load → Validate → Merge → Enforce policy → Build → Run
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
# Pipeline: load → validate → merge → build → REPL loop
# The entire REPL runs inside a single asyncio.run() so MCPToolset
# connections persist across questions (not torn down per-question).
# ---------------------------------------------------------------------------

async def _repl(merged: MergedConfig, agent: Agent):
    print(f"\n  {merged.display_name} (terminal mode)")
    print("   Type your problem and press Enter")
    print("   Type 'exit' to quit")
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
    merged = merge_config(manifest)
    agent = build_agent_from_manifest(merged)

    asyncio.run(_repl(merged, agent))
